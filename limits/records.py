"""Serializable result objects shared by every experiment and the reporter."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Record:
    """One HTTP round-trip with everything needed to explain and reproduce it."""

    experiment_id: str
    suite: str
    protocol: str
    title: str
    expect: str
    probe: str = ""
    axis: str = ""
    axis_value: float | None = None
    axis_unit: str = ""

    body_bytes: int = 0
    image_count: int = 0
    raw_asset_bytes: int = 0
    base64_chars: int = 0
    text_chars: int = 0

    status: int = 0
    accepted: bool = False
    elapsed_s: float = 0.0
    error_code: str = ""
    error_type: str = ""
    error_message: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    reply: str = ""
    note: str = ""

    @property
    def body_mb(self) -> float:
        return round(self.body_bytes / 1024 / 1024, 3)

    @property
    def base64_mb(self) -> float:
        return round(self.base64_chars / 1024 / 1024, 3)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["body_mb"] = self.body_mb
        data["base64_mb"] = self.base64_mb
        return data


@dataclass
class Boundary:
    """Result of a search along a single numeric axis."""

    experiment_id: str
    suite: str
    protocol: str
    title: str
    axis: str
    unit: str
    last_ok: float | None
    first_fail: float | None
    limit: float | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentResult:
    records: list[Record] = field(default_factory=list)
    boundary: Boundary | None = None


@dataclass
class RunSummary:
    settings: dict[str, Any]
    records: list[Record] = field(default_factory=list)
    boundaries: list[Boundary] = field(default_factory=list)

    def cost_cny(self) -> float:
        """估算成本：按 ``Pricing``（可用 BAILIAN_PRICE_* 覆盖）分档计价。

        旧记录没有缓存拆分字段时，按「全部未命中」计，是保守上限。
        """
        from .config import Pricing

        pricing = Pricing.from_mapping(self.settings.get("pricing"))
        uncached = 0
        cached = 0
        completion = 0
        for record in self.records:
            usage = record.usage
            total = int(usage.get("input_tokens") or 0)
            hit = int(usage.get("cache_read_tokens") or 0)
            miss = usage.get("uncached_input_tokens")
            uncached += int(miss) if miss is not None else max(total - hit, 0)
            uncached += int(usage.get("cache_write_tokens") or 0)
            cached += hit
            completion += int(usage.get("output_tokens") or 0)
        return round(
            uncached / 1e6 * pricing.input
            + cached / 1e6 * pricing.cache_hit
            + completion / 1e6 * pricing.output,
            4,
        )

    def input_tokens(self) -> tuple[int, int]:
        """Return ``(uncached, cached)`` input tokens across all records."""
        uncached = cached = 0
        for record in self.records:
            usage = record.usage
            total = int(usage.get("input_tokens") or 0)
            hit = int(usage.get("cache_read_tokens") or 0)
            miss = usage.get("uncached_input_tokens")
            uncached += int(miss) if miss is not None else max(total - hit, 0)
            cached += hit
        return uncached, cached

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "cost_cny_estimate": self.cost_cny(),
            "records": [r.to_dict() for r in self.records],
            "boundaries": [b.to_dict() for b in self.boundaries],
        }
