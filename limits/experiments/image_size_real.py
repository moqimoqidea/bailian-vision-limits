"""单张图片体积：用真实高熵像素，而非元数据填充。

第一轮用「64×64 像素 + 巨大 tEXt 块」的 PNG 测过，20.1 MB 仍被接受。这只说明
填充块没有被剥离，不能证明 20 MB 限制不存在。本组用例改用不可压缩的随机像素，
文件体积约等于真实像素数据，从而直接回答「文档的 20 MB 到底有没有生效」。
"""

from __future__ import annotations

from ..base import BoundarySearch, Built, Experiment
from ..config import DocumentedLimits, Settings, env_floats
from ..fixtures import noise_png_of_mb
from ..protocols import ImageAsset, Protocol
from ..wire import image_payload

SUITE = "image-size-real"
PROMPT = "图片是什么颜色？只回答颜色。"
MAX_TOKENS = 8

# 每个协议布点不同：首点 9.9 MB 用来兼容 10 MB 档的模型，
# 之后按 Data URI 上限（50 MiB / 32 MiB）继续上探。
DEFAULT_POINTS = {
    "openai": [9.9, 20.5, 33.5, 45.0, 50.0],
    "responses": [9.9, 20.5, 33.5, 45.0, 50.0],
    "anthropic": [9.9, 20.5, 21.0, 23.9, 24.1],
}
TOLERANCE = {"openai": 0.5, "responses": 0.5, "anthropic": 0.05}

EXPECT = {
    "openai": "文档的单图上限若生效，应在 20 MB 附近被拒；先确认 9.9 MB 通过",
    "responses": "同 Chat 的布点，确认 Responses 路径的单图上限是否与 Chat 一致",
    "anthropic": "文档：Data URI ≤ 32 MB；预计 32 MiB 字符串上限先触发",
}


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    def builder(raw_mb: float) -> Built:
        asset = ImageAsset("image/png", noise_png_of_mb(raw_mb))
        return image_payload(protocol, settings.model, PROMPT, [asset], MAX_TOKENS)

    points = env_floats("BAILIAN_IMAGE_POINTS_MB") or DEFAULT_POINTS[protocol.key]
    return [
        BoundarySearch(
            id=f"image_real_{protocol.key}",
            suite=SUITE,
            title="单图真实体积上限（高熵像素）",
            protocol=protocol,
            expect=EXPECT[protocol.key],
            builder=builder,
            points=points,
            axis="image_raw_mb",
            axis_unit="MB",
            tolerance=TOLERANCE[protocol.key],
            max_tokens=MAX_TOKENS,
            max_refine=2,
        )
    ]
