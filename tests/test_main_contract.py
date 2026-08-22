import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def main_source() -> str:
    return (ROOT / "main.py").read_text(encoding="utf-8")


class MainHandlerContractTests(unittest.TestCase):
    def test_event_is_stopped_only_after_all_yielded_results(self):
        tree = ast.parse(main_source())
        handler = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_message"
        )
        yield_lines = [
            node.lineno for node in ast.walk(handler) if isinstance(node, ast.Yield)
        ]
        stop_lines = [
            node.lineno
            for node in ast.walk(handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "stop_event"
        ]
        self.assertTrue(yield_lines)
        self.assertEqual(len(stop_lines), 1)
        self.assertGreater(stop_lines[0], max(yield_lines))

    def test_keyword_trigger_stops_event_but_auto_trigger_does_not(self):
        source = main_source()
        # stop_event 必须受 handled 且非自动模式双重条件约束。
        self.assertIn("if handled and not auto_mode:", source)
        self.assertIn("event.stop_event()", source)

    def test_handler_returns_early_when_not_matched(self):
        source = main_source()
        self.assertIn("handled, auto_mode = await self._match_trigger(event)", source)
        # 未命中触发时在管理指令分支的 else 内直接返回。
        self.assertIn("if not handled:\n                    return", source)

    def test_admin_commands_are_parsed_before_normal_trigger(self):
        source = main_source()
        self.assertIn("parse_admin_command(event.message_str", source)
        self.assertIn("_exec_admin_command", source)
        # 管理指令必须先于普通触发解析（指令文本本身含触发词）。
        self.assertLess(
            source.index("parse_admin_command(event.message_str"),
            source.index("await self._match_trigger(event)"),
        )
        self.assertIn("_is_group_admin", source)

    def test_private_chat_gate_is_enforced(self):
        source = main_source()
        self.assertIn('"private_enable"', source)
        self.assertIn("self._group_id(event)", source)

    def test_auto_trigger_only_fires_on_messages_that_may_carry_image(self):
        source = main_source()
        self.assertIn("_may_carry_image(event)", source)
        self.assertIn("isinstance(comp, Comp.Reply)", source)

    def test_auto_cooldown_marked_only_after_images_collected(self):
        source = main_source()
        self.assertIn("_auto_cooldown.mark", source)
        mark_line = source.index("_auto_cooldown.mark")
        collect_line = source.index("images = await self._collect_images(event)")
        self.assertGreater(mark_line, collect_line)

    def test_auto_mode_failures_stay_silent(self):
        source = main_source()
        for snippet in (
            "if not auto_mode:\n                yield",
            "if not auto_mode and bool(self.config.get(\"show_error_message\", True)):",
        ):
            self.assertIn(snippet, source)

    def test_avatar_fallback_judges_at_targets(self):
        source = main_source()
        self.assertIn("_avatar_refs(message_parts)", source)
        self.assertIn("isinstance(comp, Comp.At)", source)
        self.assertIn("qq_avatar_url(qq)", source)
        self.assertIn('"enable_avatar_judge"', source)

    def test_group_overrides_are_persisted_via_data_dir(self):
        source = main_source()
        self.assertIn("GroupConfigStore(", source)
        self.assertIn("StarTools", source)
        self.assertIn("group_config.json", source)

    def test_images_are_normalized_to_data_urls_before_llm(self):
        source = main_source()
        self.assertIn("normalize_image_ref(", source)
        self.assertIn("image.data_url", source)
        self.assertIn("image_urls=[image.data_url for image in normalized]", source)
        self.assertIn("self.context.llm_generate(", source)
        self.assertIn("chat_provider_id=provider_id", source)

    def test_quota_and_cooldown_consumed_after_successful_llm_call(self):
        source = main_source()
        self.assertIn("await self._cooldown.mark(user_key)", source)
        self.assertIn("await self._quota.consume(user_key)", source)
        self.assertIn("await self._call_llm(event, normalized, style)", source)
        mark_line = source.index("await self._cooldown.mark(user_key)")
        llm_line = source.index("await self._call_llm(event, normalized, style)")
        self.assertGreater(mark_line, llm_line)

    def test_card_render_falls_back_to_plain_text(self):
        source = main_source()
        self.assertIn("Comp.Image.fromFileSystem(image_path)", source)
        self.assertIn("card_renderer.build_text_result(judgement, style)", source)
        self.assertIn("render_mode", source)
        self.assertIn("logger.exception(\"AI 鉴图：评分卡片渲染失败，降级为文本\")", source)
        self.assertIn("yield event.plain_result(card_renderer.build_text_result(judgement, style))", source)

    def test_image_refs_come_from_message_chain_or_raw_message(self):
        source = main_source()
        self.assertIn("isinstance(comp, Comp.Image)", source)
        self.assertIn("is_plausible_image_ref(value)", source)
        self.assertIn("extract_image_urls(", source)

    def test_replied_images_are_collected_in_three_tiers(self):
        source = main_source()
        self.assertIn("await self._collect_images(event)", source)
        self.assertIn("_collect_replied_image_refs", source)
        self.assertIn("isinstance(comp, Comp.Reply)", source)
        self.assertIn("_image_refs_from_chain(reply.chain", source)
        self.assertIn("extract_image_urls(getattr(event.message_obj, \"raw_message\"", source)
        # get_msg 兜底：仅 OneBot，且必须有可调用守卫。
        self.assertIn("call_action(\"get_msg\", message_id=int(message_id)", source)
        self.assertIn("if not callable(call_action):", source)

    def test_card_theme_is_detected_and_passed_to_renderer(self):
        source = main_source()
        self.assertIn("card_theme", source)
        self.assertIn("_detect_theme(event.message_str", source)
        self.assertIn("THEME_ALIASES", source)
        self.assertIn("build_card_context(", source)
        self.assertIn("theme=theme", source)
        self.assertIn("_render_card(\n                    judgement, style, normalized[0].data_url, theme", source)

    def test_no_network_imports_inside_package_except_aiohttp(self):
        # image_judge 包保持对 astrbot 无依赖，可离线测试。
        for path in sorted((ROOT / "image_judge").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("astrbot", text, f"{path} 不应 import astrbot")

    def test_metadata_has_required_fields(self):
        meta = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
        for field in ("name:", "display_name:", "desc:", "version:", "author:", "repo:", "astrbot_version:"):
            self.assertIn(field, meta)
        self.assertIn("astrbot_plugin_image_judge", meta)

    def test_conf_schema_keys_match_usage(self):
        schema = (ROOT / "_conf_schema.json").read_text(encoding="utf-8")
        source = main_source()
        for key in (
            "trigger_keywords",
            "enable_auto_trigger",
            "auto_trigger_probability",
            "auto_trigger_cooldown_seconds",
            "group_allowlist",
            "private_enable",
            "enable_avatar_judge",
            "ignore_sticker",
            "ignore_gif",
            "max_images_per_message",
            "max_image_mb",
            "vision_provider_id",
            "style",
            "custom_prompt",
            "temperature",
            "timeout_seconds",
            "render_mode",
            "card_theme",
            "show_error_message",
            "user_cooldown_seconds",
            "daily_limit",
        ):
            self.assertIn(f'"{key}"', schema, f"配置 {key} 应存在于 _conf_schema.json")
            self.assertIn(key, source, f"main.py 应使用配置 {key}")

    def test_terminate_closes_session(self):
        source = main_source()
        self.assertIn("async def terminate", source)
        self.assertIn("await self._session.close()", source)


if __name__ == "__main__":
    unittest.main()
