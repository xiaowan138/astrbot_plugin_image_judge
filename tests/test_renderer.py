import unittest

from image_judge.judge import Judgement
from image_judge.renderer import (
    DEFAULT_THEME,
    THEME_ALIASES,
    build_card_context,
    build_text_result,
    resolve_theme,
    score_color,
    stars,
)


class RendererTests(unittest.TestCase):
    def test_stars_rounding(self):
        self.assertEqual(stars(100), "★★★★★")
        self.assertEqual(stars(90), "★★★★★")
        self.assertEqual(stars(89), "★★★★☆")
        self.assertEqual(stars(0), "☆☆☆☆☆")
        self.assertEqual(stars(50), "★★★☆☆")

    def test_score_color_bands(self):
        self.assertEqual(score_color(90), "#ffd54f")
        self.assertEqual(score_color(70), "#ff8a65")
        self.assertEqual(score_color(40), "#ff5252")

    def test_text_result_with_all_fields(self):
        judgement = Judgement(score=66, reason="还行", roast="但下次别了", raw="x")
        text = build_text_result(judgement, "毒舌")
        self.assertIn("66/100", text)
        self.assertIn("毒舌", text)
        self.assertIn("还行", text)
        self.assertIn("但下次别了", text)

    def test_text_result_with_missing_fields(self):
        judgement = Judgement(score=None, reason="", roast="只有吐槽", raw="x")
        text = build_text_result(judgement, "客观")
        self.assertNotIn("100", text)
        self.assertIn("只有吐槽", text)

    def test_card_context_has_template_variables(self):
        judgement = Judgement(score=95, reason="绝了", roast="大师之作", raw="x")
        context = build_card_context(judgement, "彩虹屁", image_src="data:...")
        self.assertEqual(context["score"], 95)
        self.assertEqual(context["stars"], "★★★★★")
        self.assertEqual(context["style_name"], "彩虹屁")
        self.assertEqual(context["image_src"], "data:...")
        self.assertEqual(context["score_color"], "#ffd54f")
        self.assertIn("reason", context)
        self.assertIn("roast", context)

    def test_card_context_handles_no_score(self):
        judgement = Judgement(score=None, reason="", roast="", raw="x")
        context = build_card_context(judgement, "毒舌")
        self.assertEqual(context["score"], 0)


class ThemeTests(unittest.TestCase):
    def test_theme_aliases_cover_five_themes(self):
        self.assertEqual(
            set(THEME_ALIASES.values()),
            {"neon", "minimal", "retro", "cyber", "macaron"},
        )
        self.assertEqual(resolve_theme("霓虹"), "neon")
        self.assertEqual(resolve_theme("复古"), "retro")

    def test_unknown_theme_falls_back_to_default(self):
        self.assertEqual(resolve_theme("不存在的主题"), DEFAULT_THEME)
        self.assertEqual(resolve_theme(""), DEFAULT_THEME)

    def test_card_context_carries_resolved_theme(self):
        judgement = Judgement(score=70, reason="", roast="", raw="x")
        context = build_card_context(judgement, "毒舌", theme="赛博朋克")
        self.assertEqual(context["theme"], "cyber")
        context = build_card_context(judgement, "毒舌", theme="乱写")
        self.assertEqual(context["theme"], "neon")


if __name__ == "__main__":
    unittest.main()
