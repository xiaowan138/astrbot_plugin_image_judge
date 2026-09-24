import asyncio
import unittest
from datetime import date

from image_judge.cooldown import DailyQuota, HourlyCap, UserCooldown


class UserCooldownTests(unittest.TestCase):
    def test_allows_first_call(self):
        cooldown = UserCooldown(60)
        self.assertTrue(asyncio.run(cooldown.is_ok("user-1")))

    def test_rejects_immediate_second_call(self):
        cooldown = UserCooldown(60)
        asyncio.run(cooldown.mark("user-1"))
        self.assertFalse(asyncio.run(cooldown.is_ok("user-1")))

    def test_zero_window_disables_cooldown(self):
        cooldown = UserCooldown(0)
        asyncio.run(cooldown.mark("user-1"))
        self.assertTrue(asyncio.run(cooldown.is_ok("user-1")))

    def test_expiry_uses_fake_clock(self):
        clock = {"now": 100.0}
        cooldown = UserCooldown(10, clock=lambda: clock["now"])
        asyncio.run(cooldown.mark("user-1"))
        self.assertFalse(asyncio.run(cooldown.is_ok("user-1")))
        clock["now"] = 111.0
        self.assertTrue(asyncio.run(cooldown.is_ok("user-1")))

    def test_keys_are_independent(self):
        cooldown = UserCooldown(60)
        asyncio.run(cooldown.mark("user-1"))
        self.assertTrue(asyncio.run(cooldown.is_ok("user-2")))


class HourlyCapTests(unittest.TestCase):
    def test_zero_limit_disables_cap(self):
        cap = HourlyCap(0)
        self.assertFalse(cap.enabled)
        for _ in range(50):
            asyncio.run(cap.mark("g"))
        self.assertTrue(asyncio.run(cap.is_ok("g")))

    def test_allows_until_limit_within_window(self):
        cap = HourlyCap(3, window_seconds=3600)
        for _ in range(3):
            self.assertTrue(asyncio.run(cap.is_ok("g")))
            asyncio.run(cap.mark("g"))
        self.assertFalse(asyncio.run(cap.is_ok("g")))

    def test_is_ok_does_not_consume(self):
        cap = HourlyCap(1, window_seconds=3600)
        for _ in range(5):
            self.assertTrue(asyncio.run(cap.is_ok("g")))
        asyncio.run(cap.mark("g"))
        self.assertFalse(asyncio.run(cap.is_ok("g")))

    def test_window_slides(self):
        clock = {"now": 0.0}
        cap = HourlyCap(1, window_seconds=3600, clock=lambda: clock["now"])
        asyncio.run(cap.mark("g"))
        self.assertFalse(asyncio.run(cap.is_ok("g")))
        clock["now"] = 3600.0
        self.assertTrue(asyncio.run(cap.is_ok("g")))

    def test_keys_are_independent(self):
        cap = HourlyCap(1, window_seconds=3600)
        asyncio.run(cap.mark("g1"))
        self.assertFalse(asyncio.run(cap.is_ok("g1")))
        self.assertTrue(asyncio.run(cap.is_ok("g2")))

    def test_negative_limit_is_clamped_to_disabled(self):
        cap = HourlyCap(-5)
        self.assertFalse(cap.enabled)


class DailyQuotaTests(unittest.TestCase):
    def test_allows_until_limit(self):
        quota = DailyQuota(2)
        today = date.today().isoformat()
        self.assertTrue(asyncio.run(quota.can_use("u", today)))
        asyncio.run(quota.consume("u", today))
        asyncio.run(quota.consume("u", today))
        self.assertFalse(asyncio.run(quota.can_use("u", today)))

    def test_resets_next_day(self):
        quota = DailyQuota(1)
        asyncio.run(quota.consume("u", "2026-01-01"))
        self.assertTrue(asyncio.run(quota.can_use("u", "2026-01-02")))

    def test_zero_limit_disabled(self):
        quota = DailyQuota(0)
        for _ in range(5):
            asyncio.run(quota.consume("u", "2026-01-01"))
        self.assertTrue(asyncio.run(quota.can_use("u", "2026-01-01")))

    def test_keys_are_independent(self):
        quota = DailyQuota(1)
        asyncio.run(quota.consume("u1", "2026-01-01"))
        self.assertTrue(asyncio.run(quota.can_use("u2", "2026-01-01")))


if __name__ == "__main__":
    unittest.main()
