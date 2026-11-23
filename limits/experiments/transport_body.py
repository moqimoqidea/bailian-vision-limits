"""请求体整体上限（文档：64 MB；DashScope 主域名 16 MiB）。

用 6 张「像素极小、文件极大」的 PNG 把请求体撑到目标体积：图像 token 数
由像素决定，因此单次探测的 token 成本可以忽略，测到的纯粹是传输层与体积校验。
同时，60 MB 仍被接受即可反证 DashScope 主域名的 16 MiB 上限不适用于工作空间域名。
"""

from __future__ import annotations

from ..base import BoundarySearch, Built, Experiment
from ..config import DocumentedLimits, Settings
from ..fixtures import png_of_size
from ..protocols import ImageAsset, Protocol
from ..wire import image_payload

MiB = 1024 * 1024
SUITE = "transport"
PROMPT = "这些图是什么颜色？只回答颜色。"
MAX_TOKENS = 8
IMAGE_COUNT = 6


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    def builder(body_mb: float) -> Built:
        raw_total = int(body_mb * MiB * 0.75)
        per_image = max(raw_total // IMAGE_COUNT, 4096)
        assets = [
            ImageAsset("image/png", png_of_size(per_image))
            for _ in range(IMAGE_COUNT)
        ]
        return image_payload(protocol, settings.model, PROMPT, assets, MAX_TOKENS)

    return [
        BoundarySearch(
            id=f"body_size_{protocol.key}",
            suite=SUITE,
            title=f"请求体整体上限（{IMAGE_COUNT} 张低像素大文件 PNG）",
            protocol=protocol,
            expect=(
                f"文档：整体 ≤ {limits.body_mb:g} MB；"
                f"DashScope 主域名另有 {limits.body_mb_dashscope_domain:g} MiB 上限。"
                "第一轮 65 MB 在 OpenAI 兼容仍返回 200、在 Anthropic 兼容被断开连接，"
                "本轮继续加压以定位真实上限"
            ),
            builder=builder,
            points=[12.0, 60.0, 65.0, 80.0, 110.0],
            axis="body_mb",
            axis_unit="MB",
            tolerance=4.0,
            max_tokens=MAX_TOKENS,
            max_refine=1,
            transient_is_failure=True,
        )
    ]
