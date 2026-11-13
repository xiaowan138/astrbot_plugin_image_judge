import tempfile
import unittest
from pathlib import Path

from image_judge.group_config import (
    GroupConfigStore,
    GroupOverride,
    effective_settings,
)


class EffectiveSettingsTests(unittest.TestCase):
    def test_follows_global_when_no_override(self):
        result = effective_settings(
            global_enabled=True,
            global_probability=20,
            override=GroupOverride(),
        )
        self.assertTrue(result.enabled)
        self.assertEqual(result.probability, 20)
        self.assertEqual(result.probability_source, "全局默认")

    def test_group_can_opt_out(self):
        result = effective_settings(
            global_enabled=True,
            global_probability=20,
            override=GroupOverride(enabled=False),
        )
        self.assertFalse(result.enabled)

    def test_group_probability_overrides_global(self):
        result = effective_settings(
            global_enabled=True,
            global_probability=20,
            override=GroupOverride(probability=66),
        )
        self.assertEqual(result.probability, 66)
        self.assertEqual(result.probability_source, "本群")

    def test_global_master_switch_disables_everything(self):
        # 全局总闸关闭时，本群开启也不生效。
        result = effective_settings(
            global_enabled=False,
            global_probability=20,
            override=GroupOverride(enabled=True),
        )
        self.assertFalse(result.enabled)

    def test_quiet_hours_and_hourly_limit_follow_global_by_default(self):
        result = effective_settings(
            global_enabled=True,
            global_probability=20,
            override=GroupOverride(),
            global_quiet_hours="23:00-08:00",
            global_hourly_limit=10,
        )
        self.assertEqual(result.quiet_hours, "23:00-08:00")
        self.assertEqual(result.quiet_hours_source, "全局默认")
        self.assertEqual(result.hourly_limit, 10)
        self.assertEqual(result.hourly_limit_source, "全局默认")

    def test_group_overrides_quiet_hours_and_hourly_limit(self):
        result = effective_settings(
            global_enabled=True,
            global_probability=20,
            override=GroupOverride(quiet_hours="12:00-13:00", hourly_limit=3),
            global_quiet_hours="23:00-08:00",
            global_hourly_limit=10,
        )
        self.assertEqual(result.quiet_hours, "12:00-13:00")
        self.assertEqual(result.quiet_hours_source, "本群")
        self.assertEqual(result.hourly_limit, 3)
        self.assertEqual(result.hourly_limit_source, "本群")

    def test_empty_quiet_hours_disables_global_window_for_this_group(self):
        # 空字符串 = 本群显式关闭免打扰，与 None（跟随全局）区分开。
        result = effective_settings(
            global_enabled=True,
            global_probability=20,
            override=GroupOverride(quiet_hours=""),
            global_quiet_hours="23:00-08:00",
        )
        self.assertEqual(result.quiet_hours, "")
        self.assertEqual(result.quiet_hours_source, "本群")


class GroupConfigStoreTests(unittest.TestCase):
    def test_set_and_get_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "group_config.json"
            store = GroupConfigStore(path)
            self.assertEqual(store.get("123"), GroupOverride())
            store.set("123", enabled=False)
            store.set("123", probability=66)
            self.assertEqual(store.get("123"), GroupOverride(False, 66))

            # 新实例应从磁盘读到同样的内容。
            reopened = GroupConfigStore(path)
            self.assertEqual(reopened.get("123"), GroupOverride(False, 66))
            self.assertEqual(reopened.get("other"), GroupOverride())

    def test_reset_field_to_follow_global(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GroupConfigStore(Path(directory) / "group_config.json")
            store.set("123", probability=66)
            store.set("123", probability=None)
            self.assertEqual(store.get("123"), GroupOverride(None, None))

    def test_corrupt_file_falls_back_to_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "group_config.json"
            path.write_text("{ not json", encoding="utf-8")
            store = GroupConfigStore(path)
            self.assertEqual(store.get("123"), GroupOverride())

    def test_quiet_hours_and_hourly_limit_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "group_config.json"
            store = GroupConfigStore(path)
            store.set("123", quiet_hours="12:00-13:00", hourly_limit=5)
            self.assertEqual(
                store.get("123"),
                GroupOverride(quiet_hours="12:00-13:00", hourly_limit=5),
            )
            reopened = GroupConfigStore(path)
            self.assertEqual(
                reopened.get("123"),
                GroupOverride(quiet_hours="12:00-13:00", hourly_limit=5),
            )

    def test_quiet_hours_can_be_disabled_per_group(self):
        # 空字符串要原样保存，不能被当作“未设置”丢掉。
        with tempfile.TemporaryDirectory() as directory:
            store = GroupConfigStore(Path(directory) / "group_config.json")
            store.set("123", quiet_hours="")
            self.assertEqual(store.get("123").quiet_hours, "")
            store.set("123", quiet_hours=None)
            self.assertIsNone(store.get("123").quiet_hours)

    def test_hourly_limit_zero_means_unlimited_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GroupConfigStore(Path(directory) / "group_config.json")
            store.set("123", hourly_limit=0)
            self.assertEqual(store.get("123").hourly_limit, 0)


if __name__ == "__main__":
    unittest.main()
