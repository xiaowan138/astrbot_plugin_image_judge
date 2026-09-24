import unittest

from image_judge.cache import ResultCache, cache_key


class CacheKeyTests(unittest.TestCase):
    def test_same_image_and_style_hits_same_key(self):
        self.assertEqual(
            cache_key("data:image/jpeg;base64,AAA", "毒舌"),
            cache_key("data:image/jpeg;base64,AAA", "毒舌"),
        )

    def test_different_style_is_a_different_key(self):
        self.assertNotEqual(
            cache_key("data:image/jpeg;base64,AAA", "毒舌"),
            cache_key("data:image/jpeg;base64,AAA", "彩虹屁"),
        )

    def test_different_image_is_a_different_key(self):
        self.assertNotEqual(
            cache_key("data:image/jpeg;base64,AAA", "毒舌"),
            cache_key("data:image/jpeg;base64,BBB", "毒舌"),
        )

    def test_key_is_stable_hex(self):
        key = cache_key("data:image/jpeg;base64,AAA", "毒舌")
        self.assertEqual(len(key), 64)
        self.assertTrue(all(char in "0123456789abcdef" for char in key))


class ResultCacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = {"now": 1000.0}
        self.cache = ResultCache(60, clock=lambda: self.clock["now"])

    def test_miss_then_hit(self):
        self.assertIsNone(self.cache.get("k"))
        self.cache.put("k", "结果")
        self.assertEqual(self.cache.get("k"), "结果")

    def test_expires_after_ttl(self):
        self.cache.put("k", "结果")
        self.clock["now"] += 59
        self.assertEqual(self.cache.get("k"), "结果")
        self.clock["now"] += 2
        self.assertIsNone(self.cache.get("k"))

    def test_zero_ttl_disables_cache(self):
        cache = ResultCache(0, clock=lambda: self.clock["now"])
        self.assertFalse(cache.enabled)
        cache.put("k", "结果")
        self.assertIsNone(cache.get("k"))

    def test_empty_value_is_not_cached(self):
        self.cache.put("k", "   ")
        self.assertIsNone(self.cache.get("k"))

    def test_entries_are_bounded_evicting_oldest(self):
        cache = ResultCache(60, max_entries=3, clock=lambda: self.clock["now"])
        for index in range(5):
            cache.put(f"k{index}", f"值{index}")
        self.assertIsNone(cache.get("k0"))
        self.assertIsNone(cache.get("k1"))
        self.assertEqual(cache.get("k4"), "值4")
        self.assertEqual(len(cache._items), 3)

    def test_get_refreshes_recency(self):
        cache = ResultCache(60, max_entries=2, clock=lambda: self.clock["now"])
        cache.put("a", "A")
        cache.put("b", "B")
        cache.get("a")  # 让 a 变成最近使用
        cache.put("c", "C")
        self.assertEqual(cache.get("a"), "A")
        self.assertIsNone(cache.get("b"))


if __name__ == "__main__":
    unittest.main()
