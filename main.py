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

try:
    from astrbot.api.star import StarTools
except ImportError:  # 兼容无 StarTools 的旧版本
    try:
        from astrbot.core.star.star_tools import StarTools
    except ImportError:
        StarTools = None

from .image_judge import prompts
from .image_judge import renderer as card_renderer
from .image_judge.admin import AdminCommand, parse_admin_command
from .image_judge.cooldown import DailyQuota, UserCooldown
from .image_judge.group_config import GroupConfigStore, effective_settings
from .image_judge.image_utils import (
    DEFAULT_USER_AGENT,
    extract_image_urls,
    is_plausible_image_ref,
    normalize_image_ref,
    qq_avatar_url,
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
        self._group_config = GroupConfigStore(
            self._data_dir() / "group_config.json"
        )

    @staticmethod
    def _data_dir() -> Path:
        try:
            if StarTools is not None:
                return StarTools.get_data_dir("astrbot_plugin_image_judge")
        except Exception:
            pass
        return Path(__file__).parent / "data"

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
            # 管理指令文本含触发词（如“鉴图开启”含“鉴图”），必须先于普通触发解析。
            admin_command = parse_admin_command(event.message_str or "")
            if admin_command is not None:
                async for result in self._exec_admin_command(event, admin_command):
                    yield result
                handled = True
            else:
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
            # 关键词/管理指令触发时用户意图明确，终止事件传播；自动触发不打扰主 agent。
            if handled and not auto_mode:
                event.stop_event()

    async def _match_trigger(self, event: AstrMessageEvent) -> tuple[bool, bool]:
        """返回 (是否处理本条消息, 是否为自动触发模式)。"""
        text = event.message_str or ""
        if not bool(self.config.get("private_enable", True)) and not self._group_id(event):
            return False, False
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
        settings = effective_settings(
            global_enabled=True,
            global_probability=self._config_int(
                "auto_trigger_probability", 20, 0, 100
            ),
            override=self._group_config.get(group_id),
        )
        if not settings.enabled:
            return False, False
        # 自动触发只对可能带图的消息掷概率，纯文本不浪费概率与群冷却。
        if not self._may_carry_image(event):
            return False, False
        if settings.probability <= 0 or random.randint(1, 100) > settings.probability:
            return False, False
        if not await self._auto_cooldown.is_ok(f"group\x1f{group_id}"):
            return False, False
        return True, True

    def _may_carry_image(self, event: AstrMessageEvent) -> bool:
        """轻量判断消息是否可能带图：含图片组件（跳过表情包）或回复组件。"""
        try:
            message_parts = event.get_messages()
        except (AttributeError, TypeError):
            message_parts = []
        ignore_sticker = bool(self.config.get("ignore_sticker", True))
        has_reply = False
        for comp in message_parts:
            if isinstance(comp, Comp.Image):
                if ignore_sticker and self._is_sticker(comp):
                    continue
                return True
            if isinstance(comp, Comp.Reply):
                has_reply = True
        return has_reply

    async def _handle_judge(self, event: AstrMessageEvent, auto_mode: bool):
        images = await self._collect_images(event)
        max_images = self._config_int("max_images_per_message", 1, 1, 10)
        images = images[:max_images]
        if not images:
            if auto_mode:
                return
            yield event.plain_result("请回复一张图片（或直接发图），再发送“打分”触发鉴图。")
            return
        if auto_mode:
            # 确认有图才消耗群冷却，纯文本不烧掉自动触发机会。
            group_id = self._group_id(event)
            if group_id:
                await self._auto_cooldown.mark(f"group\x1f{group_id}")

        user_key = self._user_key(event)
        if not auto_mode:
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
            # 自动触发是插件主动搭话，失败保持沉默只记日志。
            if not auto_mode:
                yield event.plain_result("图片下载失败或格式不支持，换个图试试？")
            return

        style = self._detect_style(event.message_str or "")
        try:
            text = await self._call_llm(event, normalized, style)
        except Exception as exc:
            logger.exception("AI 鉴图：模型调用失败")
            if not auto_mode and bool(self.config.get("show_error_message", True)):
                yield event.plain_result(self._friendly_error(exc))
            return
        if not (text or "").strip():
            if not auto_mode:
                yield event.plain_result("模型没有给出结果，再试一次？")
            return

        judgement = parse_judgement(text)
        # 成功调用模型后才计时冷却、消耗配额；自动触发只受概率与群冷却约束，
        # 不消耗发图者的个人冷却与每日额度。
        if not auto_mode:
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

    async def _exec_admin_command(
        self, event: AstrMessageEvent, command: AdminCommand
    ):
        group_id = self._group_id(event)
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        if command.action == "状态":
            yield event.plain_result(self._describe_group_status(group_id))
            return
        if not self._is_group_admin(event):
            yield event.plain_result("只有群管理员或 Bot 管理员才能操作鉴图设置。")
            return
        try:
            if command.action == "开启":
                self._group_config.set(group_id, enabled=True)
                message = "本群自动鉴图已开启。"
                if not bool(self.config.get("enable_auto_trigger", False)):
                    message += "注意：全局自动鉴图当前是关闭状态，需在 WebUI 配置中开启后才会生效。"
                yield event.plain_result(message)
                return
            if command.action == "关闭":
                self._group_config.set(group_id, enabled=False)
                yield event.plain_result("本群自动鉴图已关闭，关键词触发不受影响。")
                return
            if command.value is None:
                yield event.plain_result("用法：鉴图概率 0-100，如“鉴图概率 50”。")
                return
            if not 0 <= command.value <= 100:
                yield event.plain_result("概率需要在 0-100 之间。")
                return
            self._group_config.set(group_id, probability=command.value)
            yield event.plain_result(f"本群自动鉴图概率已设为 {command.value}%。")
        except OSError:
            logger.exception("AI 鉴图：保存群配置失败")
            yield event.plain_result("保存设置失败，请查看 AstrBot 日志。")

    def _describe_group_status(self, group_id: str) -> str:
        settings = effective_settings(
            global_enabled=bool(self.config.get("enable_auto_trigger", False)),
            global_probability=self._config_int(
                "auto_trigger_probability", 20, 0, 100
            ),
            override=self._group_config.get(group_id),
        )
        lines = [
            f"自动鉴图（本群）：{'开启' if settings.enabled else '关闭'}",
            f"触发概率：{settings.probability}%（{settings.probability_source}）",
            f"触发冷却：{self._config_int('auto_trigger_cooldown_seconds', 300, 0, 86400)} 秒",
            "发送“打分 / 鉴图”等关键词可随时手动触发。",
        ]
        return "\n".join(lines)

    def _is_group_admin(self, event: AstrMessageEvent) -> bool:
        """群主/群管理员，或 AstrBot 全局管理员（admins_id）。"""
        sender_id = ""
        try:
            sender_id = event.get_sender_id() or ""
        except Exception:
            sender_id = ""
        if sender_id:
            try:
                admins = self.context.get_config().get("admins_id", []) or []
                if sender_id in admins:
                    return True
            except Exception:
                pass
        role = str(getattr(event, "role", "") or "")
        if not role:
            sender = getattr(event.message_obj, "sender", None)
            role = str(getattr(sender, "role", "") or "")
        if role:
            return role.lower() in ("admin", "owner", "administrator")
        try:
            return bool(event.is_admin())
        except Exception:
            return False

    async def _collect_images(self, event: AstrMessageEvent) -> list[str]:
        """收集待鉴图图片：当前消息的图 → 被回复消息的图 → @目标的头像。"""
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
        refs = await self._collect_replied_image_refs(event, ignore_sticker)
        if refs:
            return refs
        return self._avatar_refs(message_parts)

    def _avatar_refs(self, message_parts) -> list[str]:
        """“锐评 @某人”：把被 @ 的 QQ 号转成头像直链（主要支持 QQ 平台）。"""
        if not bool(self.config.get("enable_avatar_judge", True)):
            return []
        refs: list[str] = []
        for comp in message_parts or []:
            if not isinstance(comp, Comp.At):
                continue
            qq = str(getattr(comp, "qq", "") or "").strip()
            if not qq.isdigit():
                continue  # 过滤 @全体成员 与非 QQ 平台的用户 ID
            refs.append(qq_avatar_url(qq))
        return refs

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
        # file 可能只是平台缓存文件名（无协议无路径），此时回退用 url。
        file = str(getattr(comp, "file", "") or "").strip()
        url = str(getattr(comp, "url", "") or "").strip()
        for value in (file, url):
            if value and is_plausible_image_ref(value):
                return value
        return file or url or None

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
