"""单张图片体积上限。

Base64 传入时存在两条互相独立的限制：
  * 原始文件 ≤ 20 MB（Qwen3.8 系列）
  * 编码后的 Data URI ≤ 20 MB（OpenAI 兼容）/ 32 MB（Anthropic 兼容）
后者会把前者的有效上限压到约 15 MB，这正是本实验要测出来的差异。
"""

from __future__ import annotations

from ..base import BoundarySearch, Built, Experiment
from ..config import DocumentedLimits, Settings
from ..fixtures import png_of_mb
from ..protocols import ImageAsset, Protocol
from ..wire import image_payload

MiB = 1024 * 1024
SUITE = "image-size"
PROMPT = "图片是什么颜色？只回答颜色。"
MAX_TOKENS = 8


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    def sized_builder(raw_mb: float) -> Built:
        asset = ImageAsset("image/png", png_of_mb(raw_mb))
        return image_payload(protocol, settings.model, PROMPT, [asset], MAX_TOKENS)

    return [
        BoundarySearch(
            id=f"image_size_{protocol.key}",
            suite=SUITE,
            title="单图原始体积上限（Base64）",
            protocol=protocol,
            expect=(
                f"文档：原图 ≤ {limits.image_mb_relaxed:g} MB，"
                f"Data URI ≤ {limits.data_uri_mb(protocol.key):g} MB；"
                "两者取小，预计 OpenAI 兼容约 15 MB、Anthropic 兼容约 20 MB"
            ),
            builder=lambda value: sized_builder(value),
            points=[9.9, 14.9, 15.1, 19.9, 20.1],
            axis="image_raw_mb",
            axis_unit="MB",
            tolerance=0.05,
            max_tokens=MAX_TOKENS,
            max_refine=3,
        )
    ]
