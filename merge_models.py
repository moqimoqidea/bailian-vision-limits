"""把两个模型的实测结果合并成一份对照报告。

只在**边界数值一致**时合并；记录级差异（例如某个模型不校验 max_tokens）
不阻止合并，而是单列一节，避免丢掉有用的差异信息。

用法：
    python merge_models.py --a results-qwen38-max --b results-qwen4-max \
        --out results-merged
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from limits.config import Pricing, Settings  # noqa: E402
from limits.persist import load_summary  # noqa: E402
from limits.report import (  # noqa: E402
    PROTOCOL_LABEL,
    PROTOCOL_ORDER,
    Report,
    _num,
)
from limits.records import RunSummary  # noqa: E402

TOLERANCE = 0.011


def _settings_for(summary: RunSummary) -> Settings:
    return Settings(
        workspace_id="from-results",
        api_key="",
        model=str(summary.settings.get("model") or "unknown"),
    )


def _boundary_map(summary: RunSummary) -> dict:
    return {boundary.experiment_id: boundary for boundary in summary.boundaries}


def _zh_cell(report: Report, protocol: str) -> str:
    for prefix in ("text_zh_ext_", "text_zh_"):
        boundary = report._boundary(prefix, protocol)
        if boundary and boundary.first_fail is not None:
            return f"{_num(boundary.last_ok)} / {_num(boundary.first_fail)} {boundary.unit}"
    return "未触顶"


def _image_cell(report: Report, protocol: str) -> str:
    boundary = report._boundary("image_real_", protocol)
    if boundary and boundary.first_fail is not None:
        return f"{_num(boundary.last_ok)} / {_num(boundary.first_fail)} {boundary.unit}"
    max_ok = report._max_ok("image_real_", protocol)
    return f"≥ {_num(max_ok)} MB 通过" if max_ok else "—"


def _count_cell(report: Report, protocol: str) -> str:
    boundary = report._boundary("image_count_", protocol)
    if boundary and boundary.last_ok is not None and boundary.first_fail is not None:
        return f"{int(boundary.last_ok)} / {int(boundary.first_fail)} 张"
    return "—"


def _matrix(a: Report, b: Report) -> list[list[str]]:
    rows: list[list[str]] = []
    for protocol in PROTOCOL_ORDER:
        label = PROTOCOL_LABEL[protocol]
        pairs = [
            ("英文文本", a._text_cell(protocol), b._text_cell(protocol)),
            ("中文文本", _zh_cell(a, protocol), _zh_cell(b, protocol)),
            ("请求体", a._body_cell(protocol), b._body_cell(protocol)),
            ("单图原始体积", _image_cell(a, protocol), _image_cell(b, protocol)),
            ("Base64 张数", _count_cell(a, protocol), _count_cell(b, protocol)),
        ]
        for name, left, right in pairs:
            rows.append([f"{name} · {label}", left, right, "一致" if left == right else "**不同**"])
    return rows


def _boundary_differences(a: RunSummary, b: RunSummary) -> list[str]:
    left, right = _boundary_map(a), _boundary_map(b)
    diffs: list[str] = []
    for experiment_id in sorted(set(left) | set(right)):
        one, two = left.get(experiment_id), right.get(experiment_id)
        if one is None or two is None:
            diffs.append(f"`{experiment_id}` 只在其中一个模型出现")
            continue
        if (
            abs((one.last_ok or 0) - (two.last_ok or 0)) > TOLERANCE
            or abs((one.first_fail or 0) - (two.first_fail or 0)) > TOLERANCE
        ):
            diffs.append(
                f"`{experiment_id}`：{_num(one.last_ok)}/{_num(one.first_fail)} "
                f"vs {_num(two.last_ok)}/{_num(two.first_fail)} {one.unit}"
            )
    return diffs


def _record_differences(a: RunSummary, b: RunSummary) -> list[str]:
    def index(summary: RunSummary) -> dict:
        return {(r.experiment_id, r.axis_value): r for r in summary.records}

    left, right = index(a), index(b)
    diffs: list[str] = []
    for key in sorted(set(left) & set(right), key=lambda item: (item[0], item[1] or 0)):
        one, two = left[key], right[key]
        if one.status != two.status:
            diffs.append(
                f"`{key[0]}`{f' @ {_num(key[1])}' if key[1] is not None else ''}："
                f"{one.status} vs {two.status}"
            )
    return diffs


def _intro(report_a: Report, report_b: Report, host: str) -> list[str]:
    a, b = report_a._summary, report_b._summary
    model_a = a.settings.get("model")
    model_b = b.settings.get("model")
    la, lb = report_a._limits, report_b._limits
    pricing_a = Pricing.from_mapping(a.settings.get("pricing"))
    pricing_b = Pricing.from_mapping(b.settings.get("pricing"))
    cost = a.cost_cny() + b.cost_cny()
    requests = len(a.records) + len(b.records)
    spec_a = (f"最大输入 {la.max_input_tokens:,} tokens，上下文 "
              f"{la.context_tokens:,}，最大输出 {la.max_output_tokens:,}")
    same_spec = (la.max_input_tokens, la.context_tokens, la.max_output_tokens) == (
        lb.max_input_tokens, lb.context_tokens, lb.max_output_tokens)
    spec_b = "同规格" if same_spec else (
        f"最大输入 {lb.max_input_tokens:,} tokens，上下文 "
        f"{lb.context_tokens:,}，最大输出 {lb.max_output_tokens:,}")
    return [
        f"- 端点：`{host}`",
        f"- 模型 A：`{model_a}`（{spec_a}；报价 "
        f"{pricing_a.input:g} / {pricing_a.output:g} 元每百万）",
        f"- 模型 B：`{model_b}`（{spec_b}；报价 "
        f"{pricing_b.input:g} / {pricing_b.output:g} 元每百万）",
        f"- 时间：{a.settings.get('started_at', '')} 起，共 {requests} 次请求；"
        f"估算成本合计约 {cost:.2f} 元",
        "- 说明：以下明细以模型 A 为主；模型 B 已按同一套探测点逐项核对，"
        "差异见「两模型一致性核对」一节。",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="合并两个模型的实测结果")
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    dir_a, dir_b, out_dir = Path(args.a), Path(args.b), Path(args.out)
    summary_a = load_summary(dir_a / "results.json")
    summary_b = load_summary(dir_b / "results.json")
    report_a = Report(summary_a, _settings_for(summary_a))
    report_b = Report(summary_b, _settings_for(summary_b))

    boundary_diffs = _boundary_differences(summary_a, summary_b)
    if boundary_diffs:
        print("边界不一致，保留两份独立报告：")
        for item in boundary_diffs:
            print("  -", item)
        return 1

    record_diffs = _record_differences(summary_a, summary_b)
    matrix = _matrix(report_a, report_b)
    model_a = summary_a.settings.get("model")
    model_b = summary_b.settings.get("model")

    comparison = [
        f"两个模型在 **{len(matrix)} 个边界维度上完全一致**（阈值口径 "
        f"±{TOLERANCE:g} MB/张），因此合并为一份报告。",
        "",
        f"| 维度 | {model_a} | {model_b} | 结论 |",
        "|---|---|---|---|",
    ]
    comparison += ["| " + " | ".join(row) + " |" for row in matrix]
    if record_diffs:
        comparison += [
            "",
            "### 记录级差异",
            "",
            "边界一致，但以下单点行为不同：",
            "",
        ]
        comparison += [f"- {item}" for item in record_diffs]
    else:
        comparison += ["", "记录级状态（HTTP 状态码）也逐条一致。"]

    merged = report_a.render(
        title=f"# 阿里云百炼 {model_a} / {model_b} 请求限制实测对照报告",
        intro=_intro(report_a, report_b, str(summary_a.settings.get("host", ""))),
        extra_sections=[("两模型一致性核对", "\n".join(comparison))],
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(merged, encoding="utf-8")
    print(f"已合并 -> {out_dir / 'report.md'}")
    print(f"边界维度 {len(matrix)} 个一致；记录级差异 {len(record_diffs)} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
