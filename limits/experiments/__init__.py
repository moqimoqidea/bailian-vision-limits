"""Experiment registry: one module per suite, all built from the same context."""

from __future__ import annotations

from ..base import Experiment
from ..config import DocumentedLimits, Settings
from ..protocols import PROTOCOLS, Protocol
from . import (
    image_count,
    image_format,
    image_size,
    image_size_real,
    misc,
    text,
    text_truncation,
    transport_body,
)

SUITES: dict[str, object] = {
    text.SUITE: text,
    text_truncation.SUITE: text_truncation,
    transport_body.SUITE: transport_body,
    image_size.SUITE: image_size,
    image_size_real.SUITE: image_size_real,
    image_count.SUITE: image_count,
    image_format.SUITE: image_format,
    misc.SUITE: misc,
}


def build_all(
    settings: Settings,
    suites: list[str] | None = None,
    protocol_keys: list[str] | None = None,
) -> list[Experiment]:
    limits = DocumentedLimits.from_env()
    selected_suites = suites or list(SUITES)
    unknown = [name for name in selected_suites if name not in SUITES]
    if unknown:
        raise SystemExit(
            f"未知 suite: {', '.join(unknown)}\n可选: {', '.join(SUITES)}"
        )

    protocols: list[Protocol] = []
    unknown_protocols = [key for key in (protocol_keys or []) if key not in PROTOCOLS]
    if unknown_protocols:
        raise SystemExit(
            f"未知协议: {', '.join(unknown_protocols)}\n可选: {', '.join(PROTOCOLS)}"
        )
    for key in protocol_keys or list(PROTOCOLS):
        protocols.append(PROTOCOLS[key])
    experiments: list[Experiment] = []
    for suite in selected_suites:
        module = SUITES[suite]
        for protocol in protocols:
            experiments.extend(module.build(protocol, settings, limits))
    return experiments
