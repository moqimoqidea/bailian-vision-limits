"""图像格式、分辨率、尺寸与宽高比的边界（文档「支持的图像格式」「图像分辨率」）。"""

from __future__ import annotations

from ..base import Built, Experiment, SingleRequest
from ..config import DocumentedLimits, Settings
from ..fixtures import image_bytes
from ..protocols import ImageAsset, Protocol
from ..wire import image_payload

SUITE = "image-format"
MAX_TOKENS = 8
COLOR_PROMPT = "图片是什么颜色？只回答颜色。"

MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    def request(
        suffix: str, title: str, expect: str, mime: str, factory
    ) -> SingleRequest:
        def _build() -> Built:
            asset = ImageAsset(mime, factory())
            return image_payload(
                protocol, settings.model, COLOR_PROMPT, [asset], MAX_TOKENS
            )

        return SingleRequest(
            id=f"fmt_{suffix}_{protocol.key}",
            suite=SUITE,
            title=title,
            protocol=protocol,
            expect=expect,
            builder=_build,
            max_tokens=MAX_TOKENS,
        )

    def encoded(fmt: str, width: int, height: int):
        return lambda: image_bytes(fmt, width, height)

    cases = [
        request(
            "png", "PNG 64×64", "文档列为支持格式，期望 200",
            MIME["PNG"], encoded("PNG", 64, 64),
        ),
        request(
            "jpeg", "JPEG 64×64", "文档列为支持格式，期望 200",
            MIME["JPEG"], encoded("JPEG", 64, 64),
        ),
        request(
            "bmp", "BMP 64×64", "文档列为支持格式（<4K），期望 200",
            MIME["BMP"], encoded("BMP", 64, 64),
        ),
        request(
            "tiff", "TIFF 64×64", "文档列为支持格式（<4K），期望 200",
            MIME["TIFF"], encoded("TIFF", 64, 64),
        ),
        request(
            "webp", "WEBP 64×64", "文档列为支持格式（<4K），期望 200",
            MIME["WEBP"], encoded("WEBP", 64, 64),
        ),
        request(
            "4k_jpeg", "5000×3000 JPEG", "4K–8K 区间允许 JPEG，期望 200",
            MIME["JPEG"], encoded("JPEG", 5000, 3000),
        ),
        request(
            "4k_webp", "5000×3000 WEBP", "4K–8K 区间仅允许 JPEG/PNG，期望 4xx",
            MIME["WEBP"], encoded("WEBP", 5000, 3000),
        ),
        request(
            "min_10px", "10×10 PNG",
            f"文档：宽高均须 > {limits.min_side_px_exclusive} px；10 px 恰好是文档边界",
            MIME["PNG"], encoded("PNG", 10, 10),
        ),
        request(
            "min_9px", "9×9 PNG",
            "低于 10 px，用于确认阈值为「≥10」还是「>10」",
            MIME["PNG"], encoded("PNG", 9, 9),
        ),
        request(
            "min_1px", "1×1 PNG",
            "极小边长的反证用例：若仍返回 200，说明最小边限制未被实际执行",
            MIME["PNG"], encoded("PNG", 1, 1),
        ),
        request(
            "min_11px", "11×11 PNG", "刚好越过最小边限制，期望 200",
            MIME["PNG"], encoded("PNG", 11, 11),
        ),
        request(
            "aspect_200", "4000×20 PNG",
            f"宽高比恰好 {limits.max_aspect_ratio}:1，文档为「不得超过」，期望 200",
            MIME["PNG"], encoded("PNG", 4000, 20),
        ),
        request(
            "aspect_210", "4200×20 PNG", "宽高比 210:1 超过 200:1，期望 4xx",
            MIME["PNG"], encoded("PNG", 4200, 20),
        ),
        request(
            "res_8k", "7680×4320 PNG",
            "文档推荐上限 8K 以内，期望 200 且图像 token 被 max_pixels 截断",
            MIME["PNG"], encoded("PNG", 7680, 4320),
        ),
        request(
            "8k_webp", "7680×4320 WEBP",
            "文档称 4K–8K 仅支持 JPEG/PNG；若 200 则说明该格式限制未被执行",
            MIME["WEBP"], encoded("WEBP", 7680, 4320),
        ),
        request(
            "mime_mismatch", "JPEG 字节声明为 image/png",
            "观察服务端是否嗅探真实格式：200 表示按内容识别，4xx 表示信任 media_type",
            MIME["PNG"], encoded("JPEG", 64, 64),
        ),
        request(
            "corrupt", "非图像字节声明为 image/png",
            "基数为合法 base64 但内容不是图像，期望 4xx",
            MIME["PNG"], lambda: b"this-is-not-an-image" * 8,
        ),
        request(
            "empty", "0 字节图像",
            "空数据，期望 4xx",
            MIME["PNG"], lambda: b"",
        ),
    ]
    return cases
