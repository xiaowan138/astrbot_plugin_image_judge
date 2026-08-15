import unittest

from image_judge.judge import Judgement, parse_judgement


class ParseJudgementTests(unittest.TestCase):
    def test_parses_structured_output(self):
        judgement = parse_judgement(
            "SCORE: 82\nREASON: 构图不错，光影到位。\nROAST: 就是主角的表情像没睡醒。"
        )
        self.assertIsInstance(judgement, Judgement)
        self.assertEqual(judgement.score, 82)
        self.assertEqual(judgement.reason, "构图不错，光影到位。")
        self.assertEqual(judgement.roast, "就是主角的表情像没睡醒。")
        self.assertTrue(judgement.is_structured)

    def test_handles_full_width_colon(self):
        judgement = parse_judgement("SCORE：35\nREASON：内容空洞\nROAST：不知所云")
        self.assertEqual(judgement.score, 35)
        self.assertEqual(judgement.reason, "内容空洞")
        self.assertEqual(judgement.roast, "不知所云")

    def test_clamps_score_to_0_100(self):
        judgement = parse_judgement("SCORE: 250\nROAST: 超纲了")
        self.assertEqual(judgement.score, 100)
        judgement = parse_judgement("SCORE: 0\nROAST: 零分")
        self.assertEqual(judgement.score, 0)
        # 模型不该输出负数；正则匹配不到时按缺失处理。
        judgement = parse_judgement("SCORE: -5\nROAST: 负分")
        self.assertIsNone(judgement.score)

    def test_strips_markdown_fences(self):
        judgement = parse_judgement(
            "```text\nSCORE: 60\nREASON: 及格线\nROAST: 老六\n```"
        )
        self.assertEqual(judgement.score, 60)
        self.assertEqual(judgement.reason, "及格线")

    def test_missing_fields_do_not_raise(self):
        judgement = parse_judgement("模型突然摆烂了")
        self.assertIsNone(judgement.score)
        self.assertFalse(judgement.is_structured)
        self.assertEqual(judgement.raw, "模型突然摆烂了")

    def test_score_with_whitespace_and_text_surrounding(self):
        judgement = parse_judgement("评分结果：SCORE: 77（不错）")
        self.assertEqual(judgement.score, 77)

    def test_reason_only_keeps_first_line(self):
        judgement = parse_judgement("SCORE: 90\nREASON: 第一行\nROAST: 下一段")
        self.assertEqual(judgement.reason, "第一行")


if __name__ == "__main__":
    unittest.main()
