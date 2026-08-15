from __future__ import annotations

import asyncio
import random
import re
from pathlib import Path

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
import astrbot.api.message_components as Comp

from .image_judge import prompts
from .image_judge import renderer as card_renderer
from .image_judge.cooldown import DailyQuota, UserCooldown
from .image_judge.image_utils import (
    DEFAULT_USER_AGENT,
    extract_image_urls,
    normalize_image_ref,
)
from .image_judge.judge import parse_judgement


class ImageJudgePlugin(Star):
    """对群友发的图片调用多模态模型打分并吐槽（纯娱乐）。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._template = (
            Path(__file__).parent / "templates" / "judge_card.html"
        ).read_text(encoding="utf-8")
        self._keywords_re = self._compile_keywords()
        self._style_re = re.compile(
            "|".join(re.escape(style) for style in prompts.STYLES)
        )
        self._theme_re = re.compile(
            "|".join(re.escape(theme) for theme in card_renderer.THEME_ALIASES)
        )
        self._cooldown = UserCooldown(
            self._config_int("user_cooldown_seconds", 60, 0, 86400)
        )
        self._auto_cooldown = UserCooldown(
            self._config_int("auto_trigger_cooldown_seconds", 300, 0, 86400)
        )
        self._quota = DailyQuota(self._config_int("daily_limit", 20, 0, 10000))

    def _compile_keywords(self) -> re.Pattern:
        raw = str(
            self.config.get("trigger_keywords", "打分|鉴图|点评|评价|锐评") or ""
        ).strip()
        keywords = [part.strip() for part in re.split(r"[|\s]+", raw) if part.strip()]
        if not keywords:
            keywords = ["打分", "鉴图"]
        return re.compile("|".join(re.escape(keyword) for keyword in keywords))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if self._is_self_message(event):
            return
        handled = False
        auto_mode = False
        try:
            handled, auto_mode = await self._match_trigger(event)
            if not handled:
                return
            async for result in self._handle_judge(event, auto_mode):
                yield result
        except Exception:
            logger.exception("AI 鉴图发生未预期错误")
            if not auto_mode and bool(self.config.get("show_error_message", True)):
                yield event.plain_result("鉴图失败，请稍后重试。")
        finally:
            # 关键词触发时用户意图明确，终止事件传播；自动触发不打扰主 agent。
            if handled and not auto_mode:
                event.stop_event()

    async def _match_trigger(self, event: AstrMessageEvent) -> tuple[bool, bool]:
        """返回 (是否处理本条消息, 是否为自动触发模式)。"""
        text = event.message_str or ""
        if self._keywords_re.search(text):
            return True, False

        if not bool(self.config.get("enable_auto_trigger", False)):
            return False, False
        group_id = self._group_id(event)
        if not group_id:
            return False, False
        allowlist = str(self.config.get("group_allowlist", "") or "").strip()
        if allowlist:
            allowed = {g.strip() for g in allowlist.split(",") if g.strip()}
            if group_id not in allowed:
                return False, False
        probability = self._config_int("auto_trigger_probability", 20, 0, 100)
        if probability <= 0 or random.randint(1, 100) > probability:
            return False, False
        if not await self._auto_cooldown.is_ok(f"group\x1f{group_id}"):
            return False, False
        return True, True

    async def _handle_judge(self, event: AstrMessageEvent, auto_mode: bool):
        if auto_mode:
            group_id = self._group_id(event)
            if group_id:
                await self._auto_cooldown.mark(f"group\x1f{group_id}")

        images = await self._collect_images(event)
        max_images = self._config_int("max_images_per_message", 1, 1, 10)
        images = images[:max_images]
        if not images:
            if auto_mode:
                return
            yield event.plain_result("请回复一张图片（或直接发图），再发送“打分”触发鉴图。")
            return

        user_key = self._user_key(event)
        if not await self._cooldown.is_ok(user_key):
            yield event.plain_result("你鉴图太频繁啦，歇一会儿再来。")
            return
        if not await self._quota.can_use(user_key):
            yield event.plain_result("今天的鉴图次数用完啦，明天再来。")
            return

        session = await self._get_session()
        max_bytes = self._config_int("max_image_mb", 8, 1, 50) * 1024 * 1024
        ignore_gif = bool(self.config.get("ignore_gif", True))
        normalized = []
        for ref in images:
            image = await normalize_image_ref(
                ref,
                session,
                max_bytes=max_bytes,
                timeout_seconds=20.0,
                first_frame_gif=not ignore_gif,
            )
            if image is None:
                continue
            if ignore_gif and image.is_gif:
                continue
            normalized.append(image)
        if not normalized:
            yield event.plain_result("图片下载失败或格式不支持，换个图试试？")
            return

        style = self._detect_style(event.message_str or "")
        try:
            text = await self._call_llm(event, normalized, style)
        except Exception as exc:
            logger.exception("AI 鉴图：模型调用失败")
            if bool(self.config.get("show_error_message", True)):
                yield event.plain_result(self._friendly_error(exc))
            return
        if not (text or "").strip():
            yield event.plain_result("模型没有给出结果，再试一次？")
            return

        judgement = parse_judgement(text)
        # 成功调用模型后才计时冷却、消耗配额。
        await self._cooldown.mark(user_key)
        await self._quota.consume(user_key)

        if not judgement.is_structured:
            yield event.plain_result((text or "").strip())
            return

        if self.config.get("render_mode", "text") == "card":
            theme = self._detect_theme(event.message_str or "")
            try:
                image_path = await self._render_card(
                    judgement, style, normalized[0].data_url, theme
                )
                yield event.chain_result(
                    [
                        Comp.Image.fromFileSystem(image_path),
                        Comp.Plain(card_renderer.build_text_result(judgement, style)),
                    ]
                )
                return
            except Exception:
                logger.exception("AI 鉴图：评分卡片渲染失败，降级为文本")
        yield event.plain_result(card_renderer.build_text_result(judgement, style))

    async def _collect_images(self, event: AstrMessageEvent) -> list[str]:
        """收集待鉴图图片：优先当前消息中的图，其次被回复消息中的图。"""
        refs: list[str] = []
        try:
            message_parts = event.get_messages()
        except (AttributeError, TypeError):
            message_parts = []
        ignore_sticker = bool(self.config.get("ignore_sticker", True))
        for comp in message_parts:
            if not isinstance(comp, Comp.Image):
                continue
            if ignore_sticker and self._is_sticker(comp):
                continue
            ref = self._image_ref(comp)
            if ref:
                refs.append(ref)
        if refs:
            return refs
        return await self._collect_replied_image_refs(event, ignore_sticker)

    async def _collect_replied_image_refs(
        self, event: AstrMessageEvent, ignore_sticker: bool
    ) -> list[str]:
        """取被回复消息中的图片（回复图片 + 打分指令场景）。

        三级策略：
        1. AstrBot 适配器解析回复段时已自动调用 get_msg，被回复消息的
           组件就绪在 Reply.chain 里；
        2. 部分平台会把被回复消息内嵌进 reply 段的原始 JSON，递归挖掘；
        3. 兜底：手动调用 OneBot get_msg 动作（仅 OneBot 适配器可用）。
        """
        reply = None
        try:
            message_parts = event.get_messages()
        except (AttributeError, TypeError):
            message_parts = []
        for comp in message_parts:
            if isinstance(comp, Comp.Reply):
                reply = comp
                break
        if reply is not None:
            refs = self._image_refs_from_chain(reply.chain, ignore_sticker)
            if refs:
                return refs

        refs = extract_image_urls(getattr(event.message_obj, "raw_message", None))
        if refs:
            return refs

        if reply is None:
            return []
        message_id = getattr(reply, "id", None)
        if message_id in (None, ""):
            return []
        bot = getattr(event, "bot", None)
        call_action = getattr(bot, "call_action", None) or getattr(
            getattr(bot, "api", None), "call_action", None
        )
        if not callable(call_action):
            return []
        routing: dict[str, str] = {}
        try:
            self_id = event.get_self_id()
            if self_id:
                routing["self_id"] = self_id
        except Exception:
            pass
        try:
            result = await call_action("get_msg", message_id=int(message_id), **routing)
        except Exception as exc:
            logger.warning(f"AI 鉴图：获取被回复消息失败：{exc}")
            return []
        data = result.get("data") if isinstance(result, dict) and "data" in result else result
        refs = []
        for segment in (data or {}).get("message", []) or []:
            if not isinstance(segment, dict) or segment.get("type") != "image":
                continue
            segment_data = segment.get("data") or {}
            for key in ("url", "file"):
                value = str(segment_data.get(key) or "").strip()
                if value:
                    refs.append(value)
                    break
        return refs

    @classmethod
    def _image_refs_from_chain(
        cls, chain, ignore_sticker: bool, _seen: set[int] | None = None
    ) -> list[str]:
        """递归取组件链里的图片引用，处理嵌套 Reply/Node/Nodes。"""
        _seen = set() if _seen is None else _seen
        refs: list[str] = []
        node_comp = getattr(Comp, "Node", None)
        nodes_comp = getattr(Comp, "Nodes", None)
        for comp in chain or []:
            if id(comp) in _seen:
                continue
            _seen.add(id(comp))
            if isinstance(comp, Comp.Image):
                if ignore_sticker and cls._is_sticker(comp):
                    continue
                ref = cls._image_ref(comp)
                if ref:
                    refs.append(ref)
            elif isinstance(comp, Comp.Reply):
                refs.extend(cls._image_refs_from_chain(comp.chain, ignore_sticker, _seen))
            elif node_comp is not None and isinstance(comp, node_comp):
                refs.extend(cls._image_refs_from_chain(comp.content, ignore_sticker, _seen))
            elif nodes_comp is not None and isinstance(comp, nodes_comp):
                for node in comp.nodes or []:
                    refs.extend(cls._image_refs_from_chain(node.content, ignore_sticker, _seen))
        return refs

    @staticmethod
    def _is_sticker(comp) -> bool:
        sub_type = str(getattr(comp, "sub_type", "") or "").lower()
        summary = str(getattr(comp, "summary", "") or "")
        return any(
            keyword in sub_type for keyword in ("face", "sticker", "emoji")
        ) or "表情" in summary

    @staticmethod
    def _image_ref(comp) -> str | None:
        value = str(comp.file or comp.url or "").strip()
        return value or None

    def _detect_style(self, text: str) -> str:
        match = self._style_re.search(text)
        if match:
            return match.group(0)
        configured = str(self.config.get("style", "毒舌") or "").strip()
        return configured if configured in prompts.STYLES else "毒舌"

    def _detect_theme(self, text: str) -> str:
        match = self._theme_re.search(text)
        if match:
            return card_renderer.THEME_ALIASES.get(match.group(0), "neon")
        configured = str(self.config.get("card_theme", "霓虹") or "").strip()
        return card_renderer.THEME_ALIASES.get(configured, "neon")

    async def _call_llm(self, event: AstrMessageEvent, normalized, style: str) -> str:
        provider_id = str(self.config.get("vision_provider_id", "") or "").strip()
        if not provider_id:
            provider_id = await self.context.get_current_chat_provider_id(
                umo=event.unified_msg_origin
            )
        timeout = self._config_int("timeout_seconds", 60, 5, 600)
        temperature = self._config_float("temperature", 0.9)
        custom_prompt = str(self.config.get("custom_prompt", "") or "")
        response = await asyncio.wait_for(
            self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompts.USER_PROMPT,
                image_urls=[image.data_url for image in normalized],
                system_prompt=prompts.system_prompt(style, custom_prompt),
                temperature=temperature,
            ),
            timeout=timeout,
        )
        return response.completion_text or ""

    async def _render_card(self, judgement, style: str, image_src: str, theme: str) -> str:
        context = card_renderer.build_card_context(
            judgement, style, image_src=image_src, theme=theme
        )
        return await self.html_render(
            self._template,
            context,
            return_url=False,
            options={
                "type": "jpeg",
                "quality": 90,
                "full_page": True,
                "animations": "disabled",
                "caret": "hide",
                "scale": "css",
            },
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": DEFAULT_USER_AGENT},
                trust_env=True,
            )
        return self._session

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc)
        lowered = message.lower()
        if "provider" in lowered and "not found" in lowered:
            return "未找到可用模型，请在插件配置中选择鉴图专用模型，或检查 AstrBot 的模型配置。"
        if any(
            keyword in lowered
            for keyword in ("vision", "image", "multimodal", "visual", "图片", "看图")
        ):
            return "当前模型可能不支持看图，请在插件配置的“鉴图专用模型”中指定一个支持图片的模型。"
        return "鉴图失败，请稍后重试。"

    def _user_key(self, event: AstrMessageEvent) -> str:
        try:
            sender_id = event.get_sender_id()
        except Exception:
            sender_id = "unknown"
        return f"{event.unified_msg_origin}\x1f{sender_id}"

    @staticmethod
    def _group_id(event: AstrMessageEvent) -> str | None:
        group_id = getattr(event.message_obj, "group_id", None)
        if group_id is None:
            return None
        return str(group_id)

    @staticmethod
    def _is_self_message(event: AstrMessageEvent) -> bool:
        try:
            return event.get_sender_id() == event.get_self_id()
        except Exception:
            return False

    def _config_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    def _config_float(self, key: str, default: float) -> float:
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return value

    async def terminate(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
