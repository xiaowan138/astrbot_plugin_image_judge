import unittest

from image_judge.admin import (
    DISABLE_WORD,
    FOLLOW_WORD,
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

    def test_space_between_words_is_tolerated(self):
        # 中文输入法常在词间加空格，不能因此把指令当成普通消息。
        self.assertEqual(parse_admin_command("鉴图 开启"), command("开启"))
        self.assertEqual(parse_admin_command("鉴图 关闭"), command("关闭"))
        self.assertEqual(parse_admin_command("鉴图 状态"), command("状态"))
        self.assertEqual(parse_admin_command("鉴图 概率 50"), command("概率", 50))
        self.assertEqual(parse_admin_command("鉴图 榜"), command("榜", scope="today"))
        self.assertEqual(
            parse_admin_command("鉴图  概率   30"), command("概率", 30)
        )

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

    def test_board_with_mention_keeps_scope(self):
        # @提及会被部分平台渲染进 message_str，范围词仍要能解析出来。
        self.assertEqual(
            parse_admin_command("鉴图榜 @张三"), command("榜", scope="today")
        )
        self.assertEqual(
            parse_admin_command("鉴图榜 @张三 本周"), command("榜", scope="week")
        )
        self.assertEqual(
            parse_admin_command("鉴图榜 @张三 总"), command("榜", scope="all")
        )

    def test_board_unknown_scope_yields_empty_scope(self):
        # 空 scope 表示无法识别，由 main 决定是提示用法还是回退今日。
        self.assertEqual(parse_admin_command("鉴图榜 明年"), command("榜", scope=""))
        self.assertFalse(is_valid_board_scope(""))

    def test_board_scope_validation(self):
        for scope in ("today", "week", "all"):
            self.assertTrue(is_valid_board_scope(scope))
        for scope in ("", "昨日", "月"):
            self.assertFalse(is_valid_board_scope(scope))

    def test_mine_command(self):
        self.assertEqual(parse_admin_command("我的鉴图"), command("我的", scope="today"))
        self.assertEqual(parse_admin_command("我的战绩"), command("我的", scope="today"))
        self.assertEqual(parse_admin_command("我的 鉴定"), command("我的", scope="today"))
        self.assertEqual(
            parse_admin_command("我的鉴图 本周"), command("我的", scope="week")
        )
        self.assertEqual(
            parse_admin_command("我的 战绩 总"), command("我的", scope="all")
        )

    def test_mine_unknown_scope_yields_empty_scope(self):
        self.assertEqual(parse_admin_command("我的鉴图 上周"), command("我的", scope=""))

    def test_non_commands_return_none(self):
        for text in (
            "",
            "打分",
            "鉴图",
            "帮我鉴图",
            "鉴图开启一下呗",
            "开启鉴图",
            "/鉴图开启",
            "我的天啊",
            "我的图呢",
        ):
            self.assertIsNone(parse_admin_command(text), text)

    def test_normal_trigger_words_are_not_admin_commands(self):
        # 普通触发不应被管理指令拦截。
        self.assertIsNone(parse_admin_command("打分 毒舌"))
        self.assertIsNone(parse_admin_command("锐评"))

    def test_normal_chat_starting_with_command_prefix_is_not_a_command(self):
        # 只是恰好以指令前缀开头的正常聊天，不能当指令（否则会回用法提示
        # 并 stop_event 拦掉主 agent）。
        for text in (
            "鉴图榜上无名啊",
            "鉴图榜单一出来吓一跳",
            "我的鉴定结果呢",
            "我的战绩不理想",
        ):
            self.assertIsNone(parse_admin_command(text), text)

    def test_scope_without_space_still_parses(self):
        self.assertEqual(parse_admin_command("我的鉴图本周"), command("我的", scope="week"))
        self.assertEqual(parse_admin_command("鉴图榜总"), command("榜", scope="all"))

    def test_help_command(self):
        for text in ("鉴图帮助", "鉴图 帮助", "鉴图用法", "鉴图指令", "鉴图菜单"):
            self.assertEqual(parse_admin_command(text), command("帮助"), text)

    def test_quiet_hours_command(self):
        self.assertEqual(
            parse_admin_command("鉴图免打扰 23:00-08:00"),
            AdminCommand("免打扰", text="23:00-08:00"),
        )
        self.assertEqual(
            parse_admin_command("鉴图 免打扰 12:00-13:30"),
            AdminCommand("免打扰", text="12:00-13:30"),
        )
        self.assertEqual(
            parse_admin_command("鉴图免打扰 关闭"),
            AdminCommand("免打扰", text=DISABLE_WORD),
        )
        self.assertEqual(
            parse_admin_command("鉴图免打扰 跟随"),
            AdminCommand("免打扰", text=FOLLOW_WORD),
        )

    def test_quiet_hours_without_value_requests_usage(self):
        self.assertEqual(parse_admin_command("鉴图免打扰"), AdminCommand("免打扰"))

    def test_invalid_quiet_hours_is_flagged(self):
        for text in ("鉴图免打扰 25:00-08:00", "鉴图免打扰 晚上", "鉴图免打扰 8点"):
            parsed = parse_admin_command(text)
            self.assertEqual(parsed.action, "免打扰", text)
            self.assertTrue(parsed.invalid, text)

    def test_hourly_limit_command(self):
        self.assertEqual(parse_admin_command("鉴图上限 10"), AdminCommand("上限", 10))
        self.assertEqual(parse_admin_command("鉴图 上限 0"), AdminCommand("上限", 0))
        self.assertEqual(
            parse_admin_command("鉴图每小时上限 5"), AdminCommand("上限", 5)
        )
        self.assertEqual(
            parse_admin_command("鉴图上限 跟随"),
            AdminCommand("上限", text=FOLLOW_WORD),
        )

    def test_hourly_limit_without_value_requests_usage(self):
        self.assertEqual(parse_admin_command("鉴图上限"), AdminCommand("上限"))

    def test_non_numeric_hourly_limit_is_flagged(self):
        parsed = parse_admin_command("鉴图上限 很多")
        self.assertEqual(parsed.action, "上限")
        self.assertTrue(parsed.invalid)


if __name__ == "__main__":
    unittest.main()
