"""Responses 路径的静默截断。

Chat 与 Anthropic 在超长时返回 400；Responses 不报错，而是把 `input` 字符串
截断到某个固定字节数，上报的 `input_tokens` 也随之固定。若不对比「预期 token 数」，
这类丢数据的行为会被误认为「限制更宽松」。
"""

from __future__ import annotations

from ..base import Experiment, SingleRequest
from ..config import DocumentedLimits, Settings
from ..fixtures import english_text
from ..protocols import Protocol
from ..wire import text_payload

MiB = 1024 * 1024
SUITE = "text-truncation"
MAX_TOKENS = 24
# 截断阈值实测约 3.43 MB：3.3 应完整，其余三点应被截断到同一数值。
POINTS = [3.3, 3.5, 3.65, 3.8]


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    if protocol.key != "responses":
        return []  # 另两条路径会明确报错，不需要截断探测

    experiments: list[Experiment] = []
    for value in POINTS:
        experiments.append(
            SingleRequest(
                id=f"trunc_{str(value).replace('.', '_')}_{protocol.key}",
                suite=SUITE,
                title=f"输入 {value:g} MB 是否被静默截断",
                protocol=protocol,
                expect="记录上报的 input_tokens；若与预期不符即为截断",
                builder=lambda value=value: text_payload(
                    protocol,
                    settings.model,
                    english_text(int(value * MiB), needle=True),
                    MAX_TOKENS,
                ),
                max_tokens=MAX_TOKENS,
                axis="text_mb",
                axis_value=value,
                axis_unit="MB",
            )
        )
    return experiments
