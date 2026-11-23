"""纯文本场景：请求体上限实际由上下文长度决定，而不是 64 MB 传输上限。"""

from __future__ import annotations

from ..base import BoundarySearch, Built, Experiment, SingleRequest
from ..config import DocumentedLimits, Settings, env_floats
from ..fixtures import chinese_text, english_text
from ..protocols import Protocol
from ..wire import text_payload

MiB = 1024 * 1024
SUITE = "text"
MAX_TOKENS = 24

# 探测点按「输入上限 / 参考模型上限」等比缩放：换模型时无需手算，
# 1M 上下文的模型仍用默认布点，256K 的模型会自动降到 1/4 附近。
REFERENCE_INPUT_TOKENS = 991_808
BASE_EN_POINTS = (0.25, 1.0, 3.0, 4.4, 4.5)
BASE_ZH_POINTS = (1.0, 1.8, 2.2)
BASE_ZH_EXT_POINTS = (4.0, 4.6)


def _scale(points: tuple[float, ...], limits: DocumentedLimits) -> list[float]:
    factor = limits.max_input_tokens / REFERENCE_INPUT_TOKENS
    return [round(point * factor, 3) for point in points]


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    key = protocol.key

    def sized_builder(factory):
        def _build(value: float) -> Built:
            text = factory(int(value * MiB))
            return text_payload(protocol, settings.model, text, MAX_TOKENS)

        return _build

    en_points = env_floats("BAILIAN_TEXT_POINTS_MB") or _scale(BASE_EN_POINTS, limits)

    return [
        SingleRequest(
            id=f"text_baseline_{key}",
            suite=SUITE,
            title="短文本基线（约 1 KB）",
            protocol=protocol,
            expect="200，用于校准 token/字节比并确认链路正常",
            builder=lambda: text_payload(
                protocol, settings.model, english_text(1024, needle=True), MAX_TOKENS
            ),
            max_tokens=MAX_TOKENS,
        ),
        BoundarySearch(
            id=f"text_en_{key}",
            suite=SUITE,
            title="英文文本体积边界",
            protocol=protocol,
            expect=(
                f"上下文上限 {limits.max_input_tokens:,} tokens，"
                "按约 4.5 字符/token 推算，应在上限对应体积附近被拒"
            ),
            builder=sized_builder(english_text),
            points=en_points,
            axis="text_mb",
            axis_unit="MB",
            tolerance=max(
                round(0.15 * limits.max_input_tokens / REFERENCE_INPUT_TOKENS, 4), 0.02
            ),
            max_tokens=MAX_TOKENS,
            max_refine=3,
        ),
        BoundarySearch(
            id=f"text_zh_{key}",
            suite=SUITE,
            title="中文文本体积边界",
            protocol=protocol,
            expect="中文按字节折算的 token 密度与英文接近，应在相近体积处被拒",
            builder=sized_builder(chinese_text),
            points=_scale(BASE_ZH_POINTS, limits),
            axis="text_mb",
            axis_unit="MB",
            tolerance=0.1,
            max_tokens=MAX_TOKENS,
            max_refine=2,
        ),
        BoundarySearch(
            id=f"text_zh_ext_{key}",
            suite=SUITE,
            title="中文文本体积边界（续测）",
            protocol=protocol,
            expect="补充上探，定位中文的实际上限",
            builder=sized_builder(chinese_text),
            points=_scale(BASE_ZH_EXT_POINTS, limits),
            axis="text_mb",
            axis_unit="MB",
            tolerance=0.15,
            max_tokens=MAX_TOKENS,
            max_refine=2,
        ),
    ]
