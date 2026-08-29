import json
import tempfile
import unittest
from pathlib import Path

from image_judge.leaderboard import JudgeRecord, LeaderboardStore


class JudgeRecordTests(unittest.TestCase):
    def test_roundtrip(self):
        record = JudgeRecord(score=88, subject_id="10001", ts=1000.5, reason="构图不错")
        restored = JudgeRecord.from_dict(record.to_dict())
        self.assertEqual(restored, record)

    def test_rejects_malformed_entries(self):
        for data in (None, "x", {}, {"score": 88}, {"score": "abc", "subject_id": "1", "ts": 1},
                     {"score": 88, "subject_id": "", "ts": 1},
                     {"score": 88, "subject_id": "1", "ts": "bad"}):
            self.assertIsNone(JudgeRecord.from_dict(data), data)

    def test_score_is_clamped(self):
        record = JudgeRecord.from_dict({"score": 250, "subject_id": "1", "ts": 1})
        self.assertEqual(record.score, 100)
        record = JudgeRecord.from_dict({"score": -5, "subject_id": "1", "ts": 1})
        self.assertEqual(record.score, 0)


class LeaderboardStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "leaderboard.json"
        self.store = LeaderboardStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_top_orders_by_score_desc(self):
        self.store.add("g1", JudgeRecord(70, "b", 1))
        self.store.add("g1", JudgeRecord(95, "a", 2))
        self.store.add("g1", JudgeRecord(80, "c", 3))
        top = self.store.top("g1")
        self.assertEqual([r.score for r in top], [95, 80, 70])

    def test_same_score_keeps_earliest_first(self):
        self.store.add("g1", JudgeRecord(90, "later", 2))
        self.store.add("g1", JudgeRecord(90, "earlier", 1))
        top = self.store.top("g1")
        self.assertEqual(top[0].subject_id, "earlier")

    def test_top_limit(self):
        for i in range(8):
            self.store.add("g1", JudgeRecord(i, f"u{i}", float(i)))
        top = self.store.top("g1", limit=5)
        self.assertEqual([r.score for r in top], [7, 6, 5, 4, 3])

    def test_since_window_filters_old_records(self):
        self.store.add("g1", JudgeRecord(99, "old", 100))
        self.store.add("g1", JudgeRecord(50, "new", 200))
        top = self.store.top("g1", since=150)
        self.assertEqual([r.subject_id for r in top], ["new"])
        worst = self.store.worst("g1", since=150)
        self.assertEqual(worst.subject_id, "new")

    def test_since_none_includes_all(self):
        self.store.add("g1", JudgeRecord(99, "old", 100))
        top = self.store.top("g1", since=None)
        self.assertEqual(len(top), 1)

    def test_worst_picks_lowest_and_latest_on_tie(self):
        self.store.add("g1", JudgeRecord(10, "first", 1))
        self.store.add("g1", JudgeRecord(10, "second", 2))
        self.store.add("g1", JudgeRecord(42, "mid", 3))
        worst = self.store.worst("g1")
        self.assertEqual(worst.subject_id, "second")

    def test_worst_on_empty_group(self):
        self.assertIsNone(self.store.worst("missing"))
        self.assertEqual(self.store.top("missing"), [])

    def test_groups_are_isolated(self):
        self.store.add("g1", JudgeRecord(90, "a", 1))
        self.store.add("g2", JudgeRecord(10, "b", 1))
        self.assertEqual(self.store.top("g1")[0].score, 90)
        self.assertEqual(self.store.top("g2")[0].score, 10)

    def test_persistence_roundtrip(self):
        store = LeaderboardStore(self.path)
        store.add("g1", JudgeRecord(88, "10001", 1234.5, reason="构图不错"))
        reloaded = LeaderboardStore(self.path)
        top = reloaded.top("g1")
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].score, 88)
        self.assertEqual(top[0].subject_id, "10001")
        self.assertEqual(top[0].reason, "构图不错")

    def test_corrupt_file_is_ignored(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("not json", encoding="utf-8")
        store = LeaderboardStore(self.path)
        self.assertEqual(store.top("g1"), [])

    def test_partial_malformed_entries_are_skipped(self):
        data = {
            "g1": [
                {"score": 90, "subject_id": "ok", "ts": 1},
                {"score": "bad"},
                "junk",
            ]
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")
        store = LeaderboardStore(self.path)
        top = store.top("g1")
        self.assertEqual([r.subject_id for r in top], ["ok"])

    def test_records_are_capped_per_group(self):
        store = LeaderboardStore(self.path, max_per_group=3)
        for i in range(5):
            store.add("g1", JudgeRecord(i, f"u{i}", float(i)))
        top = store.top("g1", since=None)
        self.assertEqual([r.score for r in top], [4, 3, 2])


if __name__ == "__main__":
    unittest.main()
