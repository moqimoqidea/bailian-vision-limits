"""Loading persisted results back into dataclasses (shared by runner and CLI)."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from .records import Boundary, Record, RunSummary


def record_from_dict(data: dict) -> Record:
    allowed = {item.name for item in fields(Record)}
    return Record(**{key: value for key, value in data.items() if key in allowed})


def boundary_from_dict(data: dict) -> Boundary:
    allowed = {item.name for item in fields(Boundary)}
    return Boundary(**{key: value for key, value in data.items() if key in allowed})


def load_summary(path: Path) -> RunSummary:
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = RunSummary(settings=data.get("settings", {}))
    summary.records = [record_from_dict(item) for item in data.get("records", [])]
    summary.boundaries = [boundary_from_dict(item) for item in data.get("boundaries", [])]
    return summary


def iter_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)
