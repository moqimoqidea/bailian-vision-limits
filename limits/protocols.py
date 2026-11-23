"""Protocol strategies.

Each subclass knows only how to turn *one* logical request (text, or text plus
images) into a wire payload for its own endpoint. Adding a third compatible
endpoint means adding a subclass, not touching the experiments.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import cached_property
from typing import Any


@dataclass(frozen=True)
class ImageAsset:
    mime: str
    raw: bytes

    @cached_property
    def b64(self) -> str:
        return base64.b64encode(self.raw).decode("ascii")

    @cached_property
    def data_uri(self) -> str:
        return f"data:{self.mime};base64,{self.b64}"


class Protocol(ABC):
    key: str
    label: str
    path: str
    max_tokens_field: str = "max_tokens"
    messages_field: str = "messages"
    min_max_tokens: int = 1

    def body(
        self,
        model: str,
        text: str,
        images: list[ImageAsset],
        max_tokens: int,
    ) -> dict[str, Any]:
        """统一入口：把输出长度钳到协议允许的下限之上，再交给具体实现。"""
        return self._body(model, text, images, max(max_tokens, self.min_max_tokens))

    @abstractmethod
    def headers(self, api_key: str) -> dict[str, str]: ...

    @abstractmethod
    def _body(
        self,
        model: str,
        text: str,
        images: list[ImageAsset],
        max_tokens: int,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def usage(self, payload: dict[str, Any] | None) -> dict[str, int]: ...

    @abstractmethod
    def reply(self, payload: dict[str, Any] | None) -> str: ...

    # Shared helper -------------------------------------------------------
    @staticmethod
    def _truncate(value: str, limit: int = 160) -> str:
        value = " ".join(value.split())
        return value if len(value) <= limit else value[:limit] + "…"


class OpenAICompat(Protocol):
    key = "openai"
    label = "OpenAI Chat (/compatible-mode/v1/chat/completions)"
    path = "/compatible-mode/v1/chat/completions"

    def headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _body(
        self, model: str, text: str, images: list[ImageAsset], max_tokens: int
    ) -> dict[str, Any]:
        if images:
            content: Any = [{"type": "text", "text": text}]
            content += [
                {"type": "image_url", "image_url": {"url": image.data_uri}}
                for image in images
            ]
        else:
            content = text
        return {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "stream": False,
            "enable_thinking": False,
        }

    def usage(self, payload: dict[str, Any] | None) -> dict[str, int]:
        """OpenAI 的 ``prompt_tokens`` 已含缓存命中，是总输入。"""
        usage = (payload or {}).get("usage") or {}
        total = int(usage.get("prompt_tokens") or 0)
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        return {
            "input_tokens": total,
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "uncached_input_tokens": max(total - cached, 0),
            "cache_read_tokens": cached,
            "cache_write_tokens": 0,
        }

    def reply(self, payload: dict[str, Any] | None) -> str:
        try:
            choices = (payload or {}).get("choices") or []
            message = choices[0].get("message") or {}
            return self._truncate(str(message.get("content") or ""))
        except (IndexError, AttributeError, TypeError):
            return ""


class AnthropicCompat(Protocol):
    key = "anthropic"
    label = "Anthropic 兼容 (/apps/anthropic/v1/messages)"
    path = "/apps/anthropic/v1/messages"

    def headers(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key, "Content-Type": "application/json"}

    def _body(
        self, model: str, text: str, images: list[ImageAsset], max_tokens: int
    ) -> dict[str, Any]:
        if images:
            content: Any = [{"type": "text", "text": text}]
            content += [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.mime,
                        "data": image.b64,
                    },
                }
                for image in images
            ]
        else:
            content = text
        return {
            "model": model,
            "max_tokens": max_tokens,
            "thinking": {"type": "disabled"},
            "messages": [{"role": "user", "content": content}],
        }

    def usage(self, payload: dict[str, Any] | None) -> dict[str, int]:
        """Anthropic 的 ``input_tokens`` 只含最后一个缓存断点之后的 token。

        官方口径：``total = input_tokens + cache_creation_input_tokens + cache_read_input_tokens``
        （https://platform.claude.com/docs/en/build-with-claude/prompt-caching）。
        这里统一归一化成「总输入」，与 OpenAI 的 ``prompt_tokens`` 可直接比较。
        """
        usage = (payload or {}).get("usage") or {}
        uncached = int(usage.get("input_tokens") or 0)
        cache_write = int(usage.get("cache_creation_input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        return {
            "input_tokens": uncached + cache_write + cache_read,
            "output_tokens": int(usage.get("output_tokens") or 0),
            "uncached_input_tokens": uncached,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
        }

    def reply(self, payload: dict[str, Any] | None) -> str:
        blocks = (payload or {}).get("content") or []
        if not isinstance(blocks, list):
            return ""
        texts = [
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return self._truncate(" ".join(texts))


class OpenAIResponses(Protocol):
    """Responses API：`input` 取代 `messages`，`max_output_tokens` 取代 `max_tokens`。"""

    key = "responses"
    label = "OpenAI Responses (/compatible-mode/v1/responses)"
    path = "/compatible-mode/v1/responses"
    max_tokens_field = "max_output_tokens"
    messages_field = "input"
    # 该路径强制要求 max_output_tokens >= 16，否则 400。
    min_max_tokens = 16

    def headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _body(
        self, model: str, text: str, images: list[ImageAsset], max_tokens: int
    ) -> dict[str, Any]:
        if images:
            content: Any = [{"type": "input_text", "text": text}]
            content += [
                {"type": "input_image", "image_url": image.data_uri} for image in images
            ]
            input_value: Any = [{"role": "user", "content": content}]
        else:
            input_value = text
        return {
            "model": model,
            "input": input_value,
            "max_output_tokens": max_tokens,
            "stream": False,
            "enable_thinking": False,
        }

    def usage(self, payload: dict[str, Any] | None) -> dict[str, int]:
        usage = (payload or {}).get("usage") or {}
        total = int(usage.get("input_tokens") or 0)
        cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
        return {
            "input_tokens": total,
            "output_tokens": int(usage.get("output_tokens") or 0),
            "uncached_input_tokens": max(total - cached, 0),
            "cache_read_tokens": cached,
            "cache_write_tokens": 0,
        }

    def reply(self, payload: dict[str, Any] | None) -> str:
        texts: list[str] = []
        for item in (payload or {}).get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for block in item.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "output_text":
                    texts.append(str(block.get("text") or ""))
        return self._truncate(" ".join(texts))


PROTOCOLS: dict[str, Protocol] = {
    protocol.key: protocol
    for protocol in (OpenAICompat(), OpenAIResponses(), AnthropicCompat())
}
