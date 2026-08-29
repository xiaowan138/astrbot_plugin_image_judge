import unittest

from image_judge.admin import (
    AdminCommand,
    is_valid_board_scope,
    parse_admin_command,
)


def command(action, value=None, invalid=False, scope=""):
    return AdminCommand(action, value, invalid, scope)


class ParseAdminCommandTests(unittest.TestCase):
    def test_simple_actions(self):
        self.assertEqual(parse_admin_command("鉴图开启"), command("开启"))
        self.assertEqual(parse_admin_command("鉴图关闭"), command("关闭"))
        self.assertEqual(parse_admin_command("鉴图状态"), command("状态"))

    def test_whitespace_is_tolerated(self):
        self.assertEqual(parse_admin_command("  鉴图开启 \n"), command("开启"))

    def test_probability_with_value(self):
        self.assertEqual(parse_admin_command("鉴图概率 50"), command("概率", 50))
        self.assertEqual(parse_admin_command("鉴图概率  0"), command("概率", 0))
        self.assertEqual(parse_admin_command("鉴图概率 100"), command("概率", 100))
        # 无空格也应识别。
        self.assertEqual(parse_admin_command("鉴图概率50"), command("概率", 50))

    def test_probability_without_value_requests_usage(self):
        self.assertEqual(parse_admin_command("鉴图概率"), command("概率", None))

    def test_non_numeric_probability_is_flagged_invalid(self):
        # “鉴图概率 abc”要整体拦下给用法提示，而不是回退成普通鉴图触发。
        parsed = parse_admin_command("鉴图概率 abc")
        self.assertEqual(parsed.action, "概率")
        self.assertTrue(parsed.invalid)
        self.assertIsNone(parsed.value)

    def test_out_of_range_probability_still_parses(self):
        # 999 解析成功即可，范围校验由 main 负责并给出提示。
        self.assertEqual(parse_admin_command("鉴图概率 999"), command("概率", 999))

    def test_board_default_scope_is_today(self):
        self.assertEqual(parse_admin_command("鉴图榜"), command("榜", scope="today"))

    def test_board_scope_aliases(self):
        self.assertEqual(
            parse_admin_command("鉴图榜 今日"), command("榜", scope="today")
        )
        self.assertEqual(
            parse_admin_command("鉴图榜 今天"), command("榜", scope="today")
        )
        self.assertEqual(parse_admin_command("鉴图榜 本周"), command("榜", scope="week"))
        self.assertEqual(parse_admin_command("鉴图榜 周"), command("榜", scope="week"))
        self.assertEqual(parse_admin_command("鉴图榜 总"), command("榜", scope="all"))
        self.assertEqual(parse_admin_command("鉴图榜 历史"), command("榜", scope="all"))

    def test_board_unknown_scope_is_passed_through(self):
        # 未知范围词原样透传，由 main 给出用法提示。
        self.assertEqual(
            parse_admin_command("鉴图榜 明年"), command("榜", scope="明年")
        )
        self.assertFalse(is_valid_board_scope("明年"))

    def test_board_scope_validation(self):
        for scope in ("today", "week", "all"):
            self.assertTrue(is_valid_board_scope(scope))
        for scope in ("", "昨日", "月"):
            self.assertFalse(is_valid_board_scope(scope))

    def test_non_commands_return_none(self):
        for text in (
            "",
            "打分",
            "鉴图",
            "帮我鉴图",
            "鉴图开启一下呗",
            "开启鉴图",
            "/鉴图开启",
        ):
            self.assertIsNone(parse_admin_command(text), text)

    def test_normal_trigger_words_are_not_admin_commands(self):
        # 普通触发不应被管理指令拦截。
        self.assertIsNone(parse_admin_command("打分 毒舌"))
        self.assertIsNone(parse_admin_command("锐评"))


if __name__ == "__main__":
    unittest.main()
