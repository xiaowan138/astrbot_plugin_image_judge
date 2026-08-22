"""图片引用下载、归一化与 data URL 转换。

QQ 图片 CDN URL 通常带防盗链和过期时间，不能直接透传给模型商。
这里统一处理四类引用（http(s) URL / 本地路径 / base64:// / data: URI），
下载或解码后做魔数识别、大小限制、GIF 首帧提取与 JPEG 压缩，
最终输出 ``data:image/jpeg;base64,...`` 供 ``llm_generate(image_urls=...)`` 使用。
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import aiohttp

from PIL import Image, ImageOps

_HTTP_URL_RE = re.compile(r"^https?://", re.I)
_BASE64_PREFIX_RE = re.compile(r"^base64://", re.I)
_DATA_URI_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.I)
_IMAGE_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.I)
_IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp)(?:$|[?#])", re.I)
_TRAILING_PUNCTUATION = "。，、；：！？,.!?:;)]}〉》」』】\"'"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_PLAUSIBLE_REF_PREFIXES = ("http://", "https://", "data:", "base64://", "file://")


def is_plausible_image_ref(value: str) -> bool:
    """引用是否是可直接解析的形态（URL/data URI/base64/本地路径）。

    部分平台的 ``Image.file`` 只是缓存文件名（如 ``ABC123.image``），既不是
    URL 也不是路径，不应挡住可用的 ``url``。
    """
    value = (value or "").strip()
    return value.startswith(_PLAUSIBLE_REF_PREFIXES) or "/" in value or "\\" in value


def qq_avatar_url(qq: str, size: int = 640) -> str:
    """QQ 头像直链（“锐评 @某人”用）；仅对纯数字 QQ 号有意义。"""
    return f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s={size}"


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    data_url: str
    mime: str
    is_gif: bool


def _mime_from_magic(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return ""


def _bytes_to_data_url(data: bytes, mime: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _compress_for_provider(data: bytes) -> bytes:
    """EXIF 转正、透明底合白、缩放到 1920 内并重编码为 JPEG。"""
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        if image.mode in ("P", "RGBA", "LA", "PA"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail((1920, 1920))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()
    except Exception:
        return data


def _gif_first_frame_as_png(data: bytes) -> bytes:
    """GIF 取首帧转 PNG，避免部分视觉网关不支持 GIF。"""
    try:
        image = Image.open(io.BytesIO(data))
        image.seek(0)
        frame = ImageOps.exif_transpose(image)
        if frame.mode in ("P", "RGBA", "LA", "PA"):
            frame = frame.convert("RGBA")
        else:
            frame = frame.convert("RGB")
        buffer = io.BytesIO()
        frame.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception:
        return data


async def _download(url: str, session: aiohttp.ClientSession, timeout_seconds: float) -> bytes | None:
    try:
        headers = {"User-Agent": DEFAULT_USER_AGENT, "Referer": _referer_for(url)}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as response:
            if response.status != 200:
                return None
            return await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def _referer_for(url: str) -> str:
    try:
        from urllib.parse import urlsplit

        host = urlsplit(url).netloc
        return f"https://{host}/" if host else ""
    except Exception:
        return ""


async def normalize_image_ref(
    ref: str,
    session: aiohttp.ClientSession,
    *,
    max_bytes: int,
    timeout_seconds: float,
    first_frame_gif: bool = True,
) -> NormalizedImage | None:
    """把图片引用归一化为可发送给模型的 data URL；任何失败返回 None。"""
    value = (ref or "").strip()
    if not value:
        return None

    if _DATA_URI_RE.match(value):
        # data URI 与其他引用同规矩：大小上限、魔数识别、GIF 处理与压缩都不豁免。
        try:
            raw = base64.b64decode(value.split(",", 1)[1], validate=True)
        except (IndexError, ValueError, TypeError):
            return None
    elif _BASE64_PREFIX_RE.match(value):
        try:
            raw = base64.b64decode(value[len("base64://"):], validate=True)
        except (ValueError, TypeError):
            return None
    elif _HTTP_URL_RE.match(value):
        raw = await _download(value, session, timeout_seconds)
        if raw is None:
            return None
    else:
        # 本地文件路径
        path = Path(value)
        if not path.is_file():
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None

    if not raw:
        return None
    if len(raw) > max_bytes:
        return None

    mime = _mime_from_magic(raw)
    if not mime:
        return None

    is_gif = mime == "image/gif"
    if is_gif and first_frame_gif:
        raw = _gif_first_frame_as_png(raw)
        mime = "image/png"

    compressed = _compress_for_provider(raw)
    if len(compressed) > max_bytes:
        return None
    return NormalizedImage(_bytes_to_data_url(compressed, "image/jpeg"), mime, is_gif)


def _iter_strings(value: Any, *, depth: int = 0, seen: set[int] | None = None) -> Iterator[str]:
    """递归遍历任意嵌套结构，用于从原始消息 JSON 中挖图片 URL。"""
    if value is None or depth > 7:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, (bytes, bytearray)):
        yield bytes(value).decode("utf-8", errors="ignore")
        return
    if isinstance(value, (int, float, bool)):
        return
    if seen is None:
        seen = set()
    object_id = id(value)
    if object_id in seen:
        return
    seen.add(object_id)
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _iter_strings(item, depth=depth + 1, seen=seen)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_strings(item, depth=depth + 1, seen=seen)


def _looks_like_image_url(url: str) -> bool:
    lowered = url.lower()
    if _IMAGE_EXT_RE.search(url):
        return True
    return "qpic.cn" in lowered or "gchat.qpic.cn" in lowered


def extract_image_urls(payload: Any) -> list[str]:
    """从原始消息 JSON 中递归提取图片 URL（处理回复消息内嵌图片）。"""
    found: list[str] = []
    for text in _iter_strings(payload):
        for match in _IMAGE_URL_RE.finditer(text):
            url = match.group(0).rstrip(_TRAILING_PUNCTUATION)
            if _looks_like_image_url(url) and url not in found:
                found.append(url)
    return found
