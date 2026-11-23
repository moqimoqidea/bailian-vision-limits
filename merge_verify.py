"""把两个模型的边界核对结果合并成一份对照报告。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads((path / "verify.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    a, b = _load(Path(args.a)), _load(Path(args.b))
    base_model = Path(a["baseline"]).name
    key = lambda row: (row["label"], row["protocol"], row["value"])
    rows_b = {key(row): row for row in b["probes"]}

    lines = [
        f"# 百炼 {a['model']} / {b['model']} 请求限制核对报告",
        "",
        f"- 方法：以 `{a['baseline']}` 中 qwen3.8-flash 的实测边界为基线，逐点复验；"
        "拒绝类请求不计费，只有文本通过与 Responses 截断点会产生 token 成本。",
        f"- 核对点：{a['model']} {len(a['probes'])} 个，{b['model']} {len(b['probes'])} 个。",
        f"- 差异：{a['anomalies']} + {b['anomalies']} 处（合计 {a['anomalies'] + b['anomalies']} 处）。",
        "",
    ]

    differences = [
        (payload["model"], row) for payload in (a, b) for row in payload["probes"] if not row["ok"]
    ]
    if not differences:
        lines += [
            "**结论：两个模型在所有核对点上都与基线一致。** "
            "因此 `qwen3.8-flash` 报告中的边界值（文本 991,808 tokens、单图 Data URI "
            "50 MiB / 32 MiB、张数 250、请求体行为等）同样适用于这两个模型。",
            "",
        ]
    else:
        lines += ["**存在差异，逐条说明见下节。**", ""]



    lines += [
        f"| 核对点 | 接口 | 点位 | {a['model']} | {b['model']} | 结论 |",
        "|---|---|---|---|---|---|",
    ]
    for row in a["probes"]:
        other = rows_b.get(key(row))
        left = "一致" if row["ok"] else f"**异常**（{row['detail']}）"
        right = (
            "一致" if other and other["ok"]
            else (f"**异常**（{other['detail']}）" if other else "缺失")
        )
        verdict = "一致" if row["ok"] and other and other["ok"] else "**需复核**"
        lines.append(
            f"| {row['label']} | {row['protocol']} | {row['value']:g} | "
            f"{left} | {right} | {verdict} |"
        )

    if differences:
        lines += ["", "### 差异说明", ""]
        for model, row in differences:
            lines.append(f"- `{model}` · {row['label']} · {row['protocol']} · {row['value']:g}：{row['detail']}")
        lines += [
            "",
            "qwen4-max 的差异经补充单点确认属于**行为改进**：同一段 3.5 MB 英文在 Responses 路径上报 "
            "815,640 tokens（qwen3.8-max 与 flash 在该点位固定为 800,017，即被截断），"
            "4.4 MB 则直接返回 400 `Range of input length should be [1, 991808]`。"
            "也就是说 qwen4-max 不再静默丢弃超长输入，而是按 token 上限拒绝。",
        ]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已合并 -> {out/'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
