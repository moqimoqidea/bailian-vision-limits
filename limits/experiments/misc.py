"""非图像类边界：输出长度、模型名、消息结构。用于建立错误码参照系。"""

from __future__ import annotations

from typing import Any, Callable

from ..base import Built, Experiment, SingleRequest
from ..config import DocumentedLimits, Settings
from ..protocols import Protocol
from ..wire import encode

SUITE = "misc"
BASE_TEXT = "你好"


def build(
    protocol: Protocol, settings: Settings, limits: DocumentedLimits
) -> list[Experiment]:
    def variant(mutate: Callable[[dict[str, Any]], None]) -> Callable[[], Built]:
        def _build() -> Built:
            payload = protocol.body(settings.model, BASE_TEXT, [], 16)
            mutate(payload)
            return Built(body=encode(payload), meta={"text_chars": len(BASE_TEXT)})

        return _build

    return [
        SingleRequest(
            id=f"max_tokens_overflow_{protocol.key}",
            suite=SUITE,
            title=f"{protocol.max_tokens_field} = {limits.max_output_tokens + 1:,}",
            protocol=protocol,
            expect=f"超过最大输出 {limits.max_output_tokens:,}，期望 4xx",
            builder=variant(
                lambda payload: payload.__setitem__(
                    protocol.max_tokens_field, limits.max_output_tokens + 1
                )
            ),
        ),
        SingleRequest(
            id=f"unknown_model_{protocol.key}",
            suite=SUITE,
            title="不存在的模型名",
            protocol=protocol,
            expect="期望 4xx，用于区分「模型不存在」与「请求超限」两类错误码",
            builder=variant(
                lambda payload: payload.__setitem__(
                    "model", f"{settings.model}-does-not-exist"
                )
            ),
        ),
        SingleRequest(
            id=f"empty_messages_{protocol.key}",
            suite=SUITE,
            title=f"{protocol.messages_field} 为空数组",
            protocol=protocol,
            expect="期望 4xx，记录结构校验的错误码",
            builder=variant(
                lambda payload: payload.__setitem__(protocol.messages_field, [])
            ),
        ),
    ]
