"""Payload encoding plus the payload-derived metrics every record carries."""

from __future__ import annotations

import json

from .base import Built
from .protocols import ImageAsset, Protocol


def encode(payload: dict) -> bytes:
    """Compact UTF-8 JSON.  No ASCII escaping: Chinese must cost 3 bytes/char."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _metrics(text: str, images: list[ImageAsset]) -> dict[str, int]:
    return {
        "image_count": len(images),
        "raw_asset_bytes": sum(len(image.raw) for image in images),
        "base64_chars": sum(len(image.b64) for image in images),
        "text_chars": len(text),
    }


def text_payload(
    protocol: Protocol, model: str, text: str, max_tokens: int = 16
) -> Built:
    payload = protocol.body(model, text, [], max_tokens)
    return Built(body=encode(payload), meta=_metrics(text, []))


def image_payload(
    protocol: Protocol,
    model: str,
    text: str,
    images: list[ImageAsset],
    max_tokens: int = 16,
) -> Built:
    payload = protocol.body(model, text, images, max_tokens)
    return Built(body=encode(payload), meta=_metrics(text, images))
