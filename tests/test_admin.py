import unittest

from image_judge.admin import AdminCommand, parse_admin_command


def command(action, value=None):
    return AdminCommand(action, value)


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

    def test_probability_without_value_requests_usage(self):
        self.assertEqual(parse_admin_command("鉴图概率"), command("概率", None))

    def test_out_of_range_probability_still_parses(self):
        # 999 解析成功即可，范围校验由 main 负责并给出提示。
        self.assertEqual(parse_admin_command("鉴图概率 999"), command("概率", 999))

    def test_non_commands_return_none(self):
        for text in (
            "",
            "打分",
            "鉴图",
            "帮我鉴图",
            "鉴图开启一下呗",
            "鉴图概率 abc",
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
