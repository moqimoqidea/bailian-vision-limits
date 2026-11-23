"""Base64 多图张数上限（文档：250 张）。"""

from __future__ import annotations

from ..base import BoundarySearch, Built, Experiment
from ..config import DocumentedLimits, Settings
from ..fixtures import image_bytes
from ..protocols import ImageAsset, Protocol
from ..wire import image_payload

SUITE = "image-count"
PROMPT = "这些图是什么颜色？只回答颜色。"
MAX_TOKENS = 8


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    tiny = ImageAsset("image/png", image_bytes("PNG", 64, 64))

    def builder(count: float) -> Built:
        images = [tiny] * int(round(count))
        return image_payload(protocol, settings.model, PROMPT, images, MAX_TOKENS)

    return [
        BoundarySearch(
            id=f"image_count_{protocol.key}",
            suite=SUITE,
            title="Base64 图片张数上限",
            protocol=protocol,
            expect=(
                f"文档：Base64 最多 {limits.images_base64_max} 张"
                f"（URL/路径为 {limits.images_url_max_qwen38} 张），"
                "预计 250 张通过、251 张被拒"
            ),
            builder=builder,
            points=[1, limits.images_base64_max, limits.images_base64_max + 1],
            axis="image_count",
            axis_unit="张",
            tolerance=1,
            max_tokens=MAX_TOKENS,
            max_refine=0,
        )
    ]
