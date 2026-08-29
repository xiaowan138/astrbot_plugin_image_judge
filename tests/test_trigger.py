import re
import unittest

from image_judge.trigger import is_command_like, strip_command_words

KEYWORDS = re.compile("|".join(re.escape(word) for word in ("打分", "鉴图", "点评", "评价", "锐评")))
STYLES = re.compile("|".join(re.escape(word) for word in ("毒舌", "客观", "彩虹屁")))
THEMES = re.compile("|".join(re.escape(word) for word in ("霓虹", "极简", "复古", "赛博朋克", "马卡龙")))


def command_like(text: str) -> bool:
    return is_command_like(text, KEYWORDS, STYLES, THEMES)


class StripCommandWordsTests(unittest.TestCase):
    def test_strips_keywords_styles_and_themes(self):
        residual = strip_command_words("打分 毒舌 复古", KEYWORDS, STYLES, THEMES)
        self.assertEqual(residual, "")

    def test_strips_all_keyword_occurrences(self):
        residual = strip_command_words("打分吧打分", KEYWORDS, STYLES, THEMES)
        self.assertEqual(residual, "吧")

    def test_plain_chat_keeps_most_text(self):
        residual = strip_command_words("帮我评价一下这个方案", KEYWORDS, STYLES, THEMES)
        self.assertEqual(residual, "帮我一下这个方案")


class IsCommandLikeTests(unittest.TestCase):
    def test_pure_commands(self):
        for text in ("打分", "鉴图", "锐评吧", "打分 毒舌", "打分 彩虹屁 复古"):
            self.assertTrue(command_like(text), text)

    def test_short_residual_counts_as_command(self):
        # 短残留（“吧”“一下”）仍视为指令，给出用法提示。
        self.assertTrue(command_like("评价一下"))
        self.assertTrue(command_like("点评下"))

    def test_normal_chat_is_not_command(self):
        # 高频词混在普通聊天里不应劫持消息。
        for text in (
            "帮我评价一下这个方案",
            "你怎么看，点评一下昨晚的比赛",
            "老师说这篇作文打分很严格",
        ):
            self.assertFalse(command_like(text), text)

    def test_empty_text_is_not_command(self):
        self.assertFalse(command_like(""))


if __name__ == "__main__":
    unittest.main()
