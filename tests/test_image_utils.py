import asyncio
import base64
import io
import unittest

from image_judge.image_utils import (
    _bytes_to_data_url,
    _compress_for_provider,
    _mime_from_magic,
    extract_image_urls,
    is_plausible_image_ref,
    normalize_image_ref,
    qq_avatar_url,
)
from PIL import Image


def make_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def make_gif_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 200, 10)).save(buffer, format="GIF")
    return buffer.getvalue()


def make_jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 10, 200)).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class FakeSession:
    """最小 aiohttp 假对象：get 返回可 async with 的请求对象（同真实 aiohttp）。"""

    def get(self, url, *, headers=None, timeout=None):
        return FakeRequest(url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeRequest:
    def __init__(self, url):
        self._url = url

    async def __aenter__(self):
        lowered = self._url.lower()
        if ".png" in lowered:
            data = make_png_bytes()
        elif ".gif" in lowered:
            data = make_gif_bytes()
        else:
            data = b"not an image"
        return FakeResponse(data)

    async def __aexit__(self, *args):
        return False


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.status = 200

    async def read(self):
        return self._data


class MagicMimeTests(unittest.TestCase):
    def test_detects_known_formats(self):
        self.assertEqual(_mime_from_magic(make_jpeg_bytes()), "image/jpeg")
        self.assertEqual(_mime_from_magic(make_png_bytes()), "image/png")
        self.assertEqual(_mime_from_magic(make_gif_bytes()), "image/gif")

    def test_rejects_unknown_data(self):
        self.assertEqual(_mime_from_magic(b"hello world"), "")


class NormalizeTests(unittest.TestCase):
    def test_local_file_path(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "photo.png"
            path.write_bytes(make_png_bytes())
            normalized = asyncio.run(
                normalize_image_ref(
                    str(path), FakeSession(), max_bytes=8 * 1024 * 1024, timeout_seconds=5
                )
            )
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.data_url.startswith("data:image/jpeg;base64,"))
        self.assertFalse(normalized.is_gif)

    def test_http_download_and_compress(self):
        normalized = asyncio.run(
            normalize_image_ref(
                "https://example.com/a/image.png",
                FakeSession(),
                max_bytes=8 * 1024 * 1024,
                timeout_seconds=5,
            )
        )
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.data_url.startswith("data:image/jpeg;base64,"))

    def test_gif_first_frame_converted_when_enabled(self):
        normalized = asyncio.run(
            normalize_image_ref(
                "https://example.com/a/image.gif",
                FakeSession(),
                max_bytes=8 * 1024 * 1024,
                timeout_seconds=5,
                first_frame_gif=True,
            )
        )
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.is_gif)
        self.assertTrue(normalized.data_url.startswith("data:image/jpeg;base64,"))

    def test_oversized_file_rejected(self):
        normalized = asyncio.run(
            normalize_image_ref(
                "https://example.com/a/image.png",
                FakeSession(),
                max_bytes=10,
                timeout_seconds=5,
            )
        )
        self.assertIsNone(normalized)

    def test_empty_and_junk_rejected(self):
        session = FakeSession()
        self.assertIsNone(
            asyncio.run(
                normalize_image_ref("", session, max_bytes=9999, timeout_seconds=5)
            )
        )
        self.assertIsNone(
            asyncio.run(
                normalize_image_ref(
                    "https://example.com/not-image",
                    session,
                    max_bytes=9999,
                    timeout_seconds=5,
                )
            )
        )


class DataUriNormalizeTests(unittest.TestCase):
    """data URI 与其他引用同规矩：大小上限、魔数识别与压缩都不豁免。"""

    def _png_data_uri(self) -> str:
        return _bytes_to_data_url(make_png_bytes(), "image/png")

    def test_png_data_uri_is_normalized_and_compressed(self):
        normalized = asyncio.run(
            normalize_image_ref(
                self._png_data_uri(), FakeSession(), max_bytes=1024 * 1024, timeout_seconds=5
            )
        )
        self.assertIsNotNone(normalized)
        self.assertFalse(normalized.is_gif)
        self.assertTrue(normalized.data_url.startswith("data:image/jpeg;base64,"))

    def test_oversized_data_uri_rejected(self):
        normalized = asyncio.run(
            normalize_image_ref(
                self._png_data_uri(), FakeSession(), max_bytes=10, timeout_seconds=5
            )
        )
        self.assertIsNone(normalized)

    def test_broken_data_uri_rejected(self):
        normalized = asyncio.run(
            normalize_image_ref(
                "data:image/png;base64,@@not-base64@@",
                FakeSession(),
                max_bytes=1024 * 1024,
                timeout_seconds=5,
            )
        )
        self.assertIsNone(normalized)

    def test_non_image_data_uri_rejected(self):
        normalized = asyncio.run(
            normalize_image_ref(
                _bytes_to_data_url(b"plain text file", "image/png"),
                FakeSession(),
                max_bytes=1024 * 1024,
                timeout_seconds=5,
            )
        )
        self.assertIsNone(normalized)

    def test_gif_data_uri_flagged_and_first_frame_extracted(self):
        uri = _bytes_to_data_url(make_gif_bytes(), "image/gif")
        normalized = asyncio.run(
            normalize_image_ref(
                uri, FakeSession(), max_bytes=1024 * 1024, timeout_seconds=5, first_frame_gif=True
            )
        )
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.is_gif)
        self.assertTrue(normalized.data_url.startswith("data:image/jpeg;base64,"))


class PlausibleRefTests(unittest.TestCase):
    def test_urls_and_paths_are_plausible(self):
        for value in (
            "https://gchat.qpic.cn/abc",
            "http://a.com/b.jpg",
            "data:image/png;base64,xxx",
            "base64://xxx",
            "file:///tmp/a.png",
            "/home/astrbot/data/x.jpg",
            "C:\\astrbot\\cache\\x.jpg",
        ):
            self.assertTrue(is_plausible_image_ref(value), value)

    def test_bare_cache_filenames_are_not_plausible(self):
        for value in ("", "ABC123.image", "abc.jpg", "   "):
            self.assertFalse(is_plausible_image_ref(value), value)


class AvatarUrlTests(unittest.TestCase):
    def test_qq_avatar_url_format(self):
        self.assertEqual(
            qq_avatar_url("123456"),
            "https://q1.qlogo.cn/g?b=qq&nk=123456&s=640",
        )


class DataUrlTests(unittest.TestCase):
    def test_roundtrip_base64(self):
        data = b"\x89PNG\r\n\x1a\nrest"
        url = _bytes_to_data_url(data, "image/png")
        self.assertTrue(url.startswith("data:image/png;base64,"))
        payload = url.split(",", 1)[1]
        self.assertEqual(base64.b64decode(payload), data)


class CompressTests(unittest.TestCase):
    def test_compresses_large_transparent_image(self):
        buffer = io.BytesIO()
        Image.new("RGBA", (400, 400), (255, 0, 0, 0)).save(buffer, format="PNG")
        raw = buffer.getvalue()
        compressed = _compress_for_provider(raw)
        # 透明底应合成白底并重编码为 JPEG。
        self.assertGreater(len(compressed), 0)
        self.assertEqual(compressed[:3], b"\xff\xd8\xff")
        Image.open(io.BytesIO(compressed)).load()


class ExtractImageUrlsTests(unittest.TestCase):
    def test_extracts_from_nested_raw_message(self):
        raw = {
            "message": [
                {
                    "type": "reply",
                    "data": {
                        "id": "123",
                        "message": [
                            {
                                "type": "image",
                                "data": {
                                    "url": "https://gchat.qpic.cn/abc/123",
                                    "file": "abc.image",
                                },
                            }
                        ],
                    },
                }
            ]
        }
        urls = extract_image_urls(raw)
        self.assertEqual(urls, ["https://gchat.qpic.cn/abc/123"])

    def test_extracts_by_extension(self):
        raw = '分享一张图 https://cdn.example.com/photo.jpg?x=1 好看吧'
        urls = extract_image_urls(raw)
        self.assertEqual(urls, ["https://cdn.example.com/photo.jpg?x=1"])

    def test_dedupes(self):
        raw = {"a": "https://a.cn/x.png", "b": "https://a.cn/x.png"}
        self.assertEqual(len(extract_image_urls(raw)), 1)


if __name__ == "__main__":
    unittest.main()
