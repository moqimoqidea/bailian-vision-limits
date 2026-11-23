"""按基线模型的实测边界，快速核对另一个模型。

不是重新找边界，而是验证「同样的点位，行为是否一致」：
拒绝类请求不计费，所以只对少数学点位（文本通过、图片、请求体）产生成本。

用法：
    python verify_boundaries.py --model qwen4-max --out results-verify-qwen4-max
    python verify_boundaries.py --model qwen3.8-max --baseline results/results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from limits.config import DocumentedLimits, Pricing, Settings  # noqa: E402
from limits.fixtures import chinese_text, english_text, image_bytes, noise_png_of_mb, png_of_size  # noqa: E402
from limits.protocols import PROTOCOLS, ImageAsset  # noqa: E402
from limits.transport import TRANSIENT, Transport  # noqa: E402
from limits.wire import image_payload, text_payload  # noqa: E402

MiB = 1024 * 1024
BODY_IMAGES = 6
BODY_PROMPT = "这些图是什么颜色？只回答颜色。"
TEXT_PROMPT_MAX = 24
IMAGE_MAX = 8


@dataclass
class Probe:
    label: str
    protocol: str
    kind: str  # text_en / text_zh / image / count / body
    value: float
    expect: str  # accept / reject / transient / truncate
    baseline: str


def _baseline_boundaries(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["experiment_id"]: item for item in data.get("boundaries", [])}


def _baseline_max_axis(path: Path, experiment_id: str) -> float | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    values = [
        record["axis_value"]
        for record in data.get("records", [])
        if record.get("experiment_id") == experiment_id
        and record.get("accepted")
        and record.get("axis_value") is not None
    ]
    return max(values) if values else None


def _plan(boundaries: dict[str, dict], baseline_path: Path) -> list[Probe]:
    probes: list[Probe] = []
    for experiment_id, item in sorted(boundaries.items()):
        protocol = item["protocol"]
        last_ok, first_fail = item.get("last_ok"), item.get("first_fail")
        if experiment_id.startswith("text_en_"):
            probes.append(Probe("英文文本 · 首次拒绝", protocol, "text_en", first_fail, "reject", f"{first_fail} MB 被拒"))
            if protocol == "openai" and last_ok is not None:
                probes.append(Probe("英文文本 · 边界内", protocol, "text_en", last_ok, "accept", f"{last_ok} MB 通过"))
        elif experiment_id.startswith("text_zh_ext_"):
            probes.append(Probe("中文文本 · 首次拒绝", protocol, "text_zh", first_fail, "reject", f"{first_fail} MB 被拒"))
        elif experiment_id.startswith("image_real_"):
            # 基线区间 [36.375, 39.25) MB 已覆盖 50 MiB Data URI 的真实终值（原图 39,321,582 B）
            probes.append(Probe("单图 · 边界内", protocol, "image", last_ok, "accept", f"{last_ok} MB 通过"))
            probes.append(Probe("单图 · 首次拒绝", protocol, "image", first_fail, "reject", f"{first_fail} MB 被拒"))
        elif experiment_id.startswith("image_count_"):
            probes.append(Probe("张数 · 边界内", protocol, "count", last_ok, "accept", f"{int(last_ok)} 张通过"))
            probes.append(Probe("张数 · 首次拒绝", protocol, "count", first_fail, "reject", f"{int(first_fail)} 张被拒"))
        elif experiment_id.startswith("body_size_"):
            if last_ok is not None:
                probes.append(Probe("请求体 · 边界内", protocol, "body", last_ok, "accept", f"{last_ok} MB 通过"))
            if first_fail is not None:
                probes.append(Probe("请求体 · 首次拒绝", protocol, "body", first_fail, "transient", f"{first_fail} MB 断连"))

    # 基线里没有边界的两个请求体点位：110 MB 仍通过（真实上限 128 MiB，见 docs/limits-summary.md）
    for protocol in ("openai", "responses"):
        top = _baseline_max_axis(baseline_path, f"body_size_{protocol}")
        if top:
            probes.append(Probe("请求体 · 大体积", protocol, "body", top, "accept", f"{top} MB 通过"))

    # 基线的 Responses 文本在 4.4 MB 是「200 + 截断」，而不是拒绝
    probes.append(
        Probe("文本 · 静默截断", "responses", "text_en", 4.4, "truncate", "200 且上报 tokens 被截断")
    )
    return probes


def _payload(probe: Probe, protocol, model: str):
    if probe.kind == "text_en":
        return text_payload(protocol, model, english_text(int(probe.value * MiB), needle=True), TEXT_PROMPT_MAX)
    if probe.kind == "text_zh":
        return text_payload(protocol, model, chinese_text(int(probe.value * MiB)), TEXT_PROMPT_MAX)
    if probe.kind == "image":
        return image_payload(protocol, model, "图片是什么颜色？只回答颜色。",
                             [ImageAsset("image/png", noise_png_of_mb(probe.value))], IMAGE_MAX)
    if probe.kind == "count":
        asset = ImageAsset("image/png", image_bytes("PNG", 64, 64))
        return image_payload(protocol, model, "这些图是什么颜色？只回答颜色。",
                             [asset] * int(probe.value), IMAGE_MAX)
    raw_total = int(probe.value * MiB * 0.75)
    per_image = max(raw_total // BODY_IMAGES, 4096)
    assets = [ImageAsset("image/png", png_of_size(per_image)) for _ in range(BODY_IMAGES)]
    return image_payload(protocol, model, BODY_PROMPT, assets, IMAGE_MAX)


def _verdict(probe: Probe, result, expected_tokens: int | None) -> tuple[bool, str]:
    if probe.expect == "accept":
        ok = result.accepted
        return ok, "200 通过" if ok else f"HTTP {result.status}"
    if probe.expect == "reject":
        ok = not result.accepted and result.kind != TRANSIENT
        return ok, f"HTTP {result.status} 拒绝" if ok else f"HTTP {result.status} / {result.kind}"
    if probe.expect == "transient":
        ok = result.kind == TRANSIENT
        return ok, "连接重置" if ok else f"HTTP {result.status}"
    # truncate：基线是「200 + 上报 token 被截断」
    tokens = int((result.payload or {}).get("usage", {}).get("input_tokens") or 0)
    predicted = expected_tokens or 0
    if not result.accepted:
        return False, f"HTTP {result.status} 拒绝（基线为 200 + 截断）"
    if predicted and tokens < 0.95 * predicted:
        return True, f"200，上报 {tokens:,} tokens（截断，同基线）"
    return False, f"200，上报 {tokens:,} tokens（完整处理，基线为截断）"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--baseline", default="results/results.json")
    parser.add_argument("--out", default=None)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--only", default="", help="只重跑标签包含该子串的核对点")
    args = parser.parse_args()

    settings = Settings.from_env()
    settings = Settings(
        workspace_id=settings.workspace_id,
        api_key=settings.api_key,
        region=settings.region,
        model=args.model,
        timeout_s=settings.timeout_s,
        request_interval_s=0.0,
    )
    out_dir = Path(args.out or f"results-verify-{args.model}")
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = Path(args.baseline)
    probes = _plan(_baseline_boundaries(baseline_path), baseline_path)
    transport = Transport(settings.host, settings.timeout_s)

    print(f"模型 {args.model} | {len(probes)} 个核对点 | 基线 {baseline_path}", flush=True)
    if args.plan_only:
        for probe in probes:
            print(f"  {probe.label:<16} {probe.protocol:<9} {probe.value:>8g} {probe.expect}")
        return 0

    journal = out_dir / "verify.jsonl"
    done: dict[tuple, dict] = {}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                done[(item["label"], item["protocol"], item["value"])] = item
    rows, failures = [], 0
    for index, probe in enumerate(probes, start=1):
        key = (probe.label, probe.protocol, probe.value)
        if args.only and args.only not in probe.label:
            if key in done:
                rows.append(done[key])
                failures += 0 if done[key]["ok"] else 1
            continue
        if key in done and not args.only:
            row = done[key]
            failures += 0 if row["ok"] else 1
            print(f"  [{index}/{len(probes)}] {probe.label:<16} {probe.protocol:<9} "
                  f"{probe.value:>8g} 已完成，跳过", flush=True)
            rows.append(row)
            continue
        protocol = PROTOCOLS[probe.protocol]
        built = _payload(probe, protocol, settings.model)
        result = transport.post(protocol.path, protocol.headers(settings.api_key), built.body)
        predicted = int(built.meta.get("text_chars", 0) * 0.222) if probe.kind == "text_en" else None
        ok, detail = _verdict(probe, result, predicted)
        failures += 0 if ok else 1
        print(f"  [{index}/{len(probes)}] {probe.label:<16} {probe.protocol:<9} "
              f"{probe.value:>8g} 期望 {probe.expect:<9} -> {detail}  {'OK' if ok else 'ANOMALY'}", flush=True)
        row = {
            "label": probe.label, "protocol": probe.protocol, "kind": probe.kind,
            "value": probe.value, "expect": probe.expect, "ok": ok, "detail": detail,
            "status": result.status, "elapsed_s": result.elapsed_s,
        }
        rows.append(row)
        done[key] = row
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        time.sleep(0.2)

    payload = {
        "model": args.model,
        "baseline": str(baseline_path),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "anomalies": failures,
        "probes": rows,
        "pricing": Pricing.current().to_mapping(),
        "documented_limits": DocumentedLimits.from_env().to_mapping(),
    }
    (out_dir / "verify.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# {args.model} 边界核对（基线：{json.loads(baseline_path.read_text())['settings']['model']}）",
        "",
        f"- 核对点：{len(rows)} 个；异常：{failures} 个",
        "",
        "| 核对点 | 接口 | 点位 | 期望 | 实测 | 结论 |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['protocol']} | {row['value']:g} | {row['expect']} | "
            f"{row['detail']} | {'一致' if row['ok'] else '**异常**'} |"
        )
    (out_dir / "verify.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n结果 -> {out_dir/'verify.md'}；异常 {failures} 个", flush=True)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
