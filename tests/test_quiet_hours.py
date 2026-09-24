import unittest
from datetime import datetime

from image_judge.quiet_hours import is_quiet_now, parse_quiet_hours


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 29, hour, minute)


class ParseQuietHoursTests(unittest.TestCase):
    def test_parses_valid_range(self):
        self.assertEqual(parse_quiet_hours("23:00-08:00"), (23 * 60, 8 * 60))
        self.assertEqual(parse_quiet_hours("09:30-18:45"), (570, 1125))

    def test_tolerates_spaces(self):
        self.assertEqual(parse_quiet_hours("  23:00 - 08:00 "), (1380, 480))

    def test_blank_or_invalid_returns_none(self):
        for spec in ("", "   ", "abc", "23:00", "23:00-", "25:00-08:00", "23:70-08:00"):
            self.assertIsNone(parse_quiet_hours(spec), spec)


class IsQuietNowTests(unittest.TestCase):
    def test_blank_spec_is_disabled(self):
        for spec in ("", "   ", "乱填"):
            self.assertFalse(is_quiet_now(spec, now=at(23, 30)), spec)

    def test_overnight_window(self):
        spec = "23:00-08:00"
        self.assertTrue(is_quiet_now(spec, now=at(23, 0)))
        self.assertTrue(is_quiet_now(spec, now=at(23, 59)))
        self.assertTrue(is_quiet_now(spec, now=at(0, 0)))
        self.assertTrue(is_quiet_now(spec, now=at(7, 59)))
        self.assertFalse(is_quiet_now(spec, now=at(8, 0)))
        self.assertFalse(is_quiet_now(spec, now=at(12, 0)))
        self.assertFalse(is_quiet_now(spec, now=at(22, 59)))

    def test_daytime_window(self):
        spec = "09:00-12:00"
        self.assertFalse(is_quiet_now(spec, now=at(8, 59)))
        self.assertTrue(is_quiet_now(spec, now=at(9, 0)))
        self.assertTrue(is_quiet_now(spec, now=at(11, 59)))
        self.assertFalse(is_quiet_now(spec, now=at(12, 0)))
        self.assertFalse(is_quiet_now(spec, now=at(23, 0)))

    def test_identical_bounds_disable_quiet_hours(self):
        # 起止相同视为不启用，否则会整天静默。
        self.assertFalse(is_quiet_now("08:00-08:00", now=at(8, 0)))
        self.assertFalse(is_quiet_now("08:00-08:00", now=at(20, 0)))


if __name__ == "__main__":
    unittest.main()
