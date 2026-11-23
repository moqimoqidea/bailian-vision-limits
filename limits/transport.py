"""HTTP transport with retry-on-transient and a single error-normalisation point.

Every failure mode of the gateway (413 from the edge, 400 from the model
service, connection reset on upload) lands in :class:`HttpResult` so the rest of
the code never has to inspect raw exceptions.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import HOST_SUFFIX
from .redact import redact

ACCEPTED = "accepted"
REJECTED = "rejected"
TRANSIENT = "transient"

# 服务端偶发以 400 表达「下载/处理超时」，这类不是容量限制，不能计入边界。
TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "temporarily unavailable",
    "try again",
    "please retry",
)


@dataclass
class HttpResult:
    status: int
    elapsed_s: float
    payload: dict[str, Any] | None = None
    text: str = ""
    error: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.status == 200

    @property
    def kind(self) -> str:
        if self.accepted:
            return ACCEPTED
        if self.status == 0 or self.status == 429 or self.status >= 500:
            return TRANSIENT
        message = self.error_fields()[2].lower()
        if any(marker in message for marker in TRANSIENT_MARKERS):
            return TRANSIENT
        return REJECTED

    def error_fields(self) -> tuple[str, str, str]:
        """Return ``(code, type, message)`` regardless of the error envelope."""
        if self.accepted:
            return "", "", ""
        if self.payload:
            err = self.payload.get("error")
            if isinstance(err, dict):
                return (
                    str(err.get("code") or self.payload.get("code") or ""),
                    str(err.get("type") or ""),
                    redact(str(err.get("message") or "")),
                )
            if self.payload.get("message") or self.payload.get("code"):
                return (
                    str(self.payload.get("code") or ""),
                    str(self.payload.get("type") or ""),
                    redact(str(self.payload.get("message") or "")),
                )
        return "", "", redact(self.error or self.text[:400])


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝跟随 3xx：避免把 Authorization 头转发到另一个主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class Transport:
    def __init__(self, host: str, timeout_s: float = 600.0, retries: int = 2) -> None:
        self._host = host.rstrip("/")
        parsed = urllib.parse.urlsplit(self._host)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SystemExit(f"端点必须是 HTTPS：{host!r}")
        if not parsed.hostname.endswith(HOST_SUFFIX):
            raise SystemExit(f"端点不在允许的域名内：{parsed.hostname!r}")
        self._hostname = parsed.hostname
        self._timeout_s = timeout_s
        self._retries = retries
        self._opener = urllib.request.build_opener(_NoRedirect)

    def post(self, path: str, headers: dict[str, str], body: bytes) -> HttpResult:
        last: HttpResult | None = None
        for attempt in range(self._retries + 1):
            last = self._post_once(path, headers, body)
            if last.kind != TRANSIENT:
                return last
            if attempt < self._retries:
                time.sleep(2.0 * (attempt + 1))
        assert last is not None
        return last

    def _post_once(self, path: str, headers: dict[str, str], body: bytes) -> HttpResult:
        url = self._host + path
        if urllib.parse.urlsplit(url).hostname != self._hostname:
            raise SystemExit(f"请求目标与配置主机不一致：{url!r}")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        started = time.time()
        try:
            with self._opener.open(request, timeout=self._timeout_s) as response:
                raw = response.read()
                return self._build(response.status, raw, started, dict(response.headers))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return self._build(exc.code, raw, started, dict(exc.headers or {}))
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            return HttpResult(
                status=0,
                elapsed_s=round(time.time() - started, 3),
                error=f"{type(exc).__name__}: {reason}",
            )

    @staticmethod
    def _build(
        status: int, raw: bytes, started: float, headers: dict[str, str]
    ) -> HttpResult:
        text = raw.decode("utf-8", errors="replace")
        payload: dict[str, Any] | None = None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = None
        return HttpResult(
            status=status,
            elapsed_s=round(time.time() - started, 3),
            payload=payload,
            text=text,
            headers={k.lower(): v for k, v in headers.items()},
        )
