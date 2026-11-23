"""Experiment framework: one request, or a search along a numeric axis.

Concrete experiments are *declarative*: they only supply (a) a builder that
turns an axis value into a wire payload and (b) the axis points to try.  The
execution, retry, boundary refinement and record-keeping live here once.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from .protocols import Protocol
from .records import Boundary, ExperimentResult, Record
from .redact import redact
from .transport import HttpResult, Transport


@dataclass
class Built:
    body: bytes
    meta: dict[str, Any] = field(default_factory=dict)


class Context:
    """Shared per-run services handed to every experiment."""

    def __init__(
        self,
        transport: Transport,
        api_key: str,
        model: str,
        interval_s: float = 1.0,
    ) -> None:
        self.transport = transport
        self.api_key = api_key
        self.model = model
        self.interval_s = interval_s
        self.request_count = 0

    def send(self, protocol: Protocol, built: Built, max_tokens: int) -> HttpResult:
        if self.request_count and self.interval_s:
            time.sleep(self.interval_s)
        self.request_count += 1
        return self.transport.post(
            protocol.path, protocol.headers(self.api_key), built.body
        )


def build_record(
    experiment_id: str,
    suite: str,
    protocol: Protocol,
    title: str,
    expect: str,
    probe: str,
    result: HttpResult,
    built: Built,
    usage: dict[str, int],
    reply: str,
    axis: str = "",
    axis_value: float | None = None,
    axis_unit: str = "",
    note: str = "",
) -> Record:
    code, err_type, message = result.error_fields()
    message = redact(message)
    reply = redact(reply)
    meta = built.meta
    return Record(
        experiment_id=experiment_id,
        suite=suite,
        protocol=protocol.key,
        title=title,
        expect=expect,
        probe=probe,
        axis=axis,
        axis_value=axis_value,
        axis_unit=axis_unit,
        body_bytes=len(built.body),
        image_count=int(meta.get("image_count") or 0),
        raw_asset_bytes=int(meta.get("raw_asset_bytes") or 0),
        base64_chars=int(meta.get("base64_chars") or 0),
        text_chars=int(meta.get("text_chars") or 0),
        status=result.status,
        accepted=result.accepted,
        elapsed_s=result.elapsed_s,
        error_code=code,
        error_type=err_type,
        error_message=" ".join(message.split())[:600],
        usage=usage,
        reply=reply,
        note=note,
    )


class Experiment(ABC):
    id: str
    suite: str
    title: str
    protocol: Protocol
    expect: str
    axis: str = ""
    axis_unit: str = ""

    @abstractmethod
    def build(self, value: float | None) -> Built: ...

    @abstractmethod
    def run(self, ctx: Context) -> ExperimentResult: ...

    def values(self) -> list[float]:
        return []


class SingleRequest(Experiment):
    """One payload, one request.  Used when there is nothing to search for."""

    def __init__(
        self,
        *,
        id: str,
        suite: str,
        title: str,
        protocol: Protocol,
        expect: str,
        builder: Callable[[], Built],
        max_tokens: int = 16,
        axis: str = "",
        axis_value: float | None = None,
        axis_unit: str = "",
    ) -> None:
        self.id = id
        self.suite = suite
        self.title = title
        self.protocol = protocol
        self.expect = expect
        self._builder = builder
        self.max_tokens = max(max_tokens, protocol.min_max_tokens)
        self.axis = axis
        self._axis_value = axis_value
        self.axis_unit = axis_unit

    def build(self, value: float | None = None) -> Built:
        return self._builder()

    def run(self, ctx: Context) -> ExperimentResult:
        built = self.build(None)
        result = ctx.send(self.protocol, built, self.max_tokens)
        record = build_record(
            self.id,
            self.suite,
            self.protocol,
            self.title,
            self.expect,
            probe="single",
            result=result,
            built=built,
            usage=self.protocol.usage(result.payload),
            reply=self.protocol.reply(result.payload),
            axis=self.axis,
            axis_value=self._axis_value,
            axis_unit=self.axis_unit,
        )
        return ExperimentResult(records=[record])


class BoundarySearch(Experiment):
    """Ladder to the first failure, then bisect until the bracket is tight.

    ``points`` must be ascending.  Points before the first failure are not
    re-sent, so a well-chosen ladder keeps the number of expensive (large-token)
    requests small.
    """

    def __init__(
        self,
        *,
        id: str,
        suite: str,
        title: str,
        protocol: Protocol,
        expect: str,
        builder: Callable[[float], Built],
        points: list[float],
        axis: str,
        axis_unit: str,
        tolerance: float,
        max_tokens: int = 16,
        max_refine: int = 4,
        ok_predicate: Callable[[HttpResult], bool] | None = None,
        transient_is_failure: bool = False,
    ) -> None:
        self.id = id
        self.suite = suite
        self.title = title
        self.protocol = protocol
        self.expect = expect
        self.axis = axis
        self.axis_unit = axis_unit
        self.tolerance = tolerance
        self.max_tokens = max(max_tokens, protocol.min_max_tokens)
        self.max_refine = max_refine
        self._builder = builder
        self._points = sorted(points)
        self._ok = ok_predicate or (lambda result: result.accepted)
        # 部分网关用「直接断开连接」表达体积超限，而不是返回 413。
        # 该开关让这类失败计入边界；每次失败前传输层已重试两次。
        self._transient_is_failure = transient_is_failure

    def values(self) -> list[float]:
        return list(self._points)

    def build(self, value: float | None) -> Built:
        if value is None:
            raise ValueError(f"{self.id} requires an axis value")
        return self._builder(value)

    def _evaluate(
        self, ctx: Context, value: float, probe: str, note: str = ""
    ) -> tuple[Record, bool, bool]:
        built = self.build(value)
        result = ctx.send(self.protocol, built, self.max_tokens)
        record = build_record(
            self.id,
            self.suite,
            self.protocol,
            self.title,
            self.expect,
            probe=probe,
            result=result,
            built=built,
            usage=self.protocol.usage(result.payload),
            reply=self.protocol.reply(result.payload),
            axis=self.axis,
            axis_value=value,
            axis_unit=self.axis_unit,
            note=note,
        )
        transient = result.kind == "transient"
        return record, self._ok(result), transient

    def run(self, ctx: Context) -> ExperimentResult:
        records: list[Record] = []
        last_ok: float | None = None
        first_fail: float | None = None
        transient_seen = False

        for value in self._points:
            record, ok, transient = self._evaluate(ctx, value, f"ladder@{value:g}")
            records.append(record)
            if transient and not self._transient_is_failure:
                transient_seen = True
                record.note = "传输层异常（非限制类），已停止搜索"
                break
            if transient:
                record.note = "连接被重置，按超限处理"
                ok = False
            if ok:
                last_ok = value
            else:
                first_fail = value
                if not transient:
                    record.note = "首次失败"
                break

        if last_ok is not None and first_fail is not None and not transient_seen:
            low, high = last_ok, first_fail
            for _ in range(self.max_refine):
                if high - low <= self.tolerance:
                    break
                mid = round((low + high) / 2, 4)
                if mid in (low, high):
                    break
                record, ok, transient = self._evaluate(ctx, mid, f"refine@{mid:g}")
                records.append(record)
                if transient and not self._transient_is_failure:
                    transient_seen = True
                    record.note = "传输层异常（非限制类），已停止细化"
                    break
                if transient:
                    record.note = "连接被重置，按超限处理"
                    ok = False
                if ok:
                    low = mid
                else:
                    high = mid
            last_ok, first_fail = low, high

        boundary = None
        if last_ok is not None and first_fail is not None:
            for record in records:
                if record.axis_value == last_ok and record.accepted:
                    record.note = "最大通过值"
            boundary = Boundary(
                experiment_id=self.id,
                suite=self.suite,
                protocol=self.protocol.key,
                title=self.title,
                axis=self.axis,
                unit=self.axis_unit,
                last_ok=last_ok,
                first_fail=first_fail,
                limit=round((last_ok + first_fail) / 2, 4),
                detail=f"阈值落在 [{last_ok:g}, {first_fail:g}) {self.axis_unit}",
            )
        return ExperimentResult(records=records, boundary=boundary)
