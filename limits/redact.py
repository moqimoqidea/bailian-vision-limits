"""统一脱敏。

服务端有时会在错误 message 或回复里回显请求头。记录落盘、日志打印、
重放输出与报告生成前都必须经过这里，避免密钥进入结果文件或终端历史。
"""

from __future__ import annotations

import os
import re

MASK = "***"

_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9][A-Za-z0-9._-]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"(?i)\bx-api-key\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bauthorization\s*[:=]\s*\S+"),
)


def redact(value: object) -> str:
    text = "" if value is None else str(value)
    if not text:
        return text
    secret = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if secret and secret in text:
        text = text.replace(secret, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)
    return text
