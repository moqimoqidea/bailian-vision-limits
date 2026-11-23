"""Experiment orchestration: run, stream progress, persist incrementally."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .base import Context, Experiment
from .config import Settings
from .persist import boundary_from_dict, iter_jsonl, record_from_dict
from .records import Boundary, Record, RunSummary
from .transport import Transport


class Runner:
    def __init__(
        self,
        settings: Settings,
        experiments: list[Experiment],
        out_dir: Path,
        resume: bool = False,
        replace_ids: set[str] | None = None,
    ) -> None:
        self._settings = settings
        self._experiments = experiments
        self._out_dir = out_dir
        self._jsonl = out_dir / "records.jsonl"
        self._resume = resume or bool(replace_ids)
        self._replace_ids = set(replace_ids or ())

    def run(self) -> RunSummary:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        summary = RunSummary(settings=self._settings_block())
        if self._resume:
            summary.records, summary.boundaries = self._load_existing()
        else:
            self._jsonl.write_text("", encoding="utf-8")

        done = {record.experiment_id for record in summary.records}
        context = Context(
            Transport(self._settings.host, self._settings.timeout_s),
            self._settings.api_key,
            self._settings.model,
            self._settings.request_interval_s,
        )

        total = len(self._experiments)
        for index, experiment in enumerate(self._experiments, start=1):
            if experiment.id in done:
                print(f"[{index}/{total}] {experiment.id} 已存在，跳过", flush=True)
                continue
            print(f"[{index}/{total}] {experiment.id} — {experiment.title}", flush=True)
            result = experiment.run(context)
            for record in result.records:
                summary.records.append(record)
                self._append({"_type": "record", **record.to_dict()})
                axis = "-" if record.axis_value is None else f"{record.axis_value:g}"
                error = "" if record.accepted else f"  {record.error_code} {record.error_message[:70]}"
                print(
                    f"    {record.probe:<14} {axis:>8}  body={record.body_mb:>8.2f}MB"
                    f"  HTTP {record.status}  {record.elapsed_s:>6.2f}s{error}",
                    flush=True,
                )
            if result.boundary:
                summary.boundaries.append(result.boundary)
                self._append({"_type": "boundary", **result.boundary.to_dict()})
                print(f"    → {result.boundary.detail}", flush=True)

        (self._out_dir / "results.json").write_text(
            json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    def _settings_block(self) -> dict:
        from .config import DocumentedLimits, Pricing

        return {
            "host": self._settings.host,
            "model": self._settings.model,
            "started_at": self._settings.started_at,
            "python": sys.version.split()[0],
            "documented_limits": DocumentedLimits.from_env().to_mapping(),
            "pricing": Pricing.current().to_mapping(),
        }

    def _append(self, payload: dict) -> None:
        with self._jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load_existing(self) -> tuple[list[Record], list[Boundary]]:
        records: list[Record] = []
        boundaries: list[Boundary] = []
        kept: list[dict] = []
        for data in iter_jsonl(self._jsonl):
            if data.get("experiment_id") in self._replace_ids:
                continue
            kept.append(data)
            kind = data.get("_type", "record")
            if kind == "boundary":
                boundaries.append(boundary_from_dict(data))
            else:
                records.append(record_from_dict(data))
        if self._replace_ids:
            self._jsonl.write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in kept),
                encoding="utf-8",
            )
        return records, boundaries
