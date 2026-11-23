"""Deterministic test-data factories.

Two properties matter for a limits study:

1. Every fixture is reproducible byte-for-byte, so an error can be replayed.
2. Payload *size* and payload *cost* are decoupled.  A PNG may carry a large
   ancillary ``tEXt`` chunk: the file becomes tens of megabytes while the
   decoded bitmap stays 64x64, i.e. essentially zero image tokens.  That is what
   makes it possible to probe the 64 MB transport ceiling without paying for
   millions of input tokens.
"""

from __future__ import annotations

import io
import math
import random

try:
    from PIL import Image, PngImagePlugin
except ImportError:  # pragma: no cover - 依赖缺失时的友好提示
    raise SystemExit(
        "缺少依赖 Pillow。请先执行：\n"
        "    pip install -r requirements.txt\n"
        "（或 pip install pillow）"
    )

PNG_PAD_KEY = "pad"
_DEFAULT_COLOR = (28, 92, 200)
NOISE_WIDTH = 3000

EN_SENTENCE = "The quick brown fox jumps over the lazy dog. "
CN_SENTENCE = "通义千问是阿里云研发的大语言模型，支持文本与图像理解。"

NEEDLE = "BLUE-OTTER-7742"

SUPPORTED_IMAGE_FORMATS = ("PNG", "JPEG", "BMP", "TIFF", "WEBP")


def _render(width: int, height: int, fmt: str, pad_chars: int = 0) -> bytes:
    image = Image.new("RGB", (width, height), _DEFAULT_COLOR)
    buffer = io.BytesIO()
    if fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text(PNG_PAD_KEY, "A" * pad_chars)
        image.save(buffer, "PNG", pnginfo=info)
    else:
        image.save(buffer, fmt)
    return buffer.getvalue()


def image_bytes(fmt: str, width: int, height: int) -> bytes:
    """Encode a solid-colour bitmap in any format Pillow supports."""
    fmt = fmt.upper()
    if fmt not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(f"unsupported format: {fmt}")
    return _render(width, height, fmt)


def png_of_size(target_bytes: int, width: int = 64, height: int = 64) -> bytes:
    """Return a *valid* PNG whose file size is exactly ``target_bytes``.

    A ``tEXt`` chunk is sized to absorb the difference, so pixel dimensions —
    and therefore image-token cost — stay constant.
    """
    base = _render(width, height, "PNG", pad_chars=0)
    pad = target_bytes - len(base)
    if pad < 0:
        raise ValueError(
            f"target {target_bytes}B is smaller than the empty PNG ({len(base)}B)"
        )
    data = _render(width, height, "PNG", pad_chars=pad)
    if len(data) != target_bytes:  # pragma: no cover - guards Pillow behaviour
        raise AssertionError(f"size mismatch: wanted {target_bytes}, got {len(data)}")
    return data


def png_of_mb(size_mb: float, width: int = 64, height: int = 64) -> bytes:
    return png_of_size(int(round(size_mb * 1024 * 1024)), width, height)


def _render_noise(width: int, height: int, pad_chars: int, seed: int) -> bytes:
    payload = random.Random(seed).randbytes(width * height * 3)
    image = Image.frombytes("RGB", (width, height), payload)
    buffer = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text(PNG_PAD_KEY, "A" * pad_chars)
    image.save(buffer, "PNG", pnginfo=info, compress_level=0)
    return buffer.getvalue()


def noise_png_of_size(target_bytes: int, seed: int = 17) -> bytes:
    """A *genuinely* large PNG: incompressible pixel data, not metadata padding.

    Used to prove that a size limit is (or is not) enforced on real image
    content rather than on an ancillary chunk the server might strip.
    ``compress_level=0`` keeps the file size predictable: roughly
    ``height * (3 * width + 1)`` bytes.
    """
    row = 3 * NOISE_WIDTH + 1
    height = max(1, (target_bytes - 4096) // row)
    data = _render_noise(NOISE_WIDTH, height, 0, seed)
    if len(data) > target_bytes:  # pragma: no cover - defensive
        height -= 1
        data = _render_noise(NOISE_WIDTH, height, 0, seed)
    pad = target_bytes - len(data)
    if pad < 0:  # pragma: no cover
        raise AssertionError("noise image exceeds target size")
    data = _render_noise(NOISE_WIDTH, height, pad, seed)
    if len(data) != target_bytes:  # pragma: no cover
        raise AssertionError(f"size mismatch: wanted {target_bytes}, got {len(data)}")
    return data


def noise_png_of_mb(size_mb: float, seed: int = 17) -> bytes:
    return noise_png_of_size(int(round(size_mb * 1024 * 1024)), seed)


def _fit_text(target_bytes: int, sentence: str) -> str:
    """Repeat ``sentence`` then clip to ``target_bytes`` on a character boundary."""
    encoded = sentence.encode("utf-8")
    repeats = math.ceil(target_bytes / len(encoded))
    raw = (encoded * repeats)[:target_bytes]
    return raw.decode("utf-8", errors="ignore")


def english_text(target_bytes: int, needle: bool = False) -> str:
    text = _fit_text(target_bytes, EN_SENTENCE)
    if needle:
        text += f"\n\n暗号是 {NEEDLE}。请只回复这串暗号。"
    return text


def chinese_text(target_bytes: int) -> str:
    return _fit_text(target_bytes, CN_SENTENCE)
