#!/usr/bin/env python3
"""百炼 qwen3.8-flash 请求限制实测 — 命令行入口。

常用：
    python3 run_tests.py --suite all                 # 全量实测
    python3 run_tests.py --suite text --protocol openai
    python3 run_tests.py --dry-run                   # 只构建载荷，不发请求
    python3 run_tests.py --dump-body text_en_openai@4.4 --out body.json
    python3 run_tests.py --report-only               # 由已有结果重出报告
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from limits.config import Settings  # noqa: E402
from limits.curlgen import write_scripts  # noqa: E402
from limits.experiments import SUITES, build_all  # noqa: E402
from limits.persist import load_summary  # noqa: E402
from limits.redact import redact  # noqa: E402
from limits.report import Report  # noqa: E402
from limits.runner import Runner  # noqa: E402
from limits.transport import Transport  # noqa: E402


def _utf8_console() -> None:
    """Windows 控制台默认不是 UTF-8，避免中文输出直接抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _selection(value: str) -> list[str] | None:
    if value.strip().lower() in ("", "all", "*"):
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _settings() -> Settings:
    try:
        return Settings.from_env()
    except SystemExit:
        return Settings(workspace_id="ws-dryrun", api_key="dryrun")


def _emit_artifacts(summary, settings: Settings, out_dir: Path) -> None:
    report_path = out_dir / "report.md"
    report_path.write_text(Report(summary, settings).render(), encoding="utf-8")
    scripts = write_scripts(summary.records, settings, out_dir / "curl")
    print(f"\n报告: {report_path}")
    print(f"复现脚本: {len(scripts)} 个 -> {out_dir / 'curl'}")
    print(f"成本估算: {summary.cost_cny():.2f} 元 / {len(summary.records)} 次请求")


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings()
    experiments = build_all(
        settings, _selection(args.suite), _selection(args.protocol)
    )
    only = [item.strip() for item in (args.only or "").split(",") if item.strip()]
    if only:
        known = {experiment.id for experiment in experiments}
        unknown = [item for item in only if item not in known]
        if unknown:
            print(f"未知实验 id: {', '.join(unknown)}", file=sys.stderr)
            return 2
        experiments = [experiment for experiment in experiments if experiment.id in only]
    out_dir = Path(args.out).resolve()

    if args.dry_run:
        planned = 0
        for experiment in experiments:
            values = experiment.values() or [None]
            sample = values[0]
            first = "-" if sample is None else f"{sample:g}"
            built = experiment.build(sample)
            planned += len(values)
            print(
                f"{experiment.id:<28} {experiment.protocol.key:<9} "
                f"首点 {first:<8} "
                f"body={len(built.body) / 1024 / 1024:.2f}MB "
                f"计划请求={len(values)}"
            )
        print(f"\n共 {len(experiments)} 个实验，最多 {planned} 次请求。未发起网络调用。")
        return 0

    replace_ids = set(only)
    if args.force:
        replace_ids |= {experiment.id for experiment in experiments}
    summary = Runner(
        settings,
        experiments,
        out_dir,
        resume=args.resume,
        replace_ids=replace_ids or None,
    ).run()
    _emit_artifacts(summary, settings, out_dir)
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    settings = _settings()
    spec = args.dump_body
    experiment_id, _, raw_value = spec.partition("@")
    experiments = build_all(settings)
    experiment = next((item for item in experiments if item.id == experiment_id), None)
    if experiment is None:
        known = ", ".join(item.id for item in experiments)
        print(f"未知实验 id: {experiment_id}\n可选: {known}", file=sys.stderr)
        return 2
    built = experiment.build(float(raw_value) if raw_value else None)
    out = Path(args.out)
    out.write_bytes(built.body)
    print(f"{out} ({len(built.body)} bytes)")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    settings = _settings()
    out_dir = Path(args.out).resolve()
    summary = load_summary(out_dir / "results.json")
    stored_model = summary.settings.get("model")
    if stored_model:
        settings = replace(settings, model=stored_model)
    _emit_artifacts(summary, settings, out_dir)
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """重建某个实验的请求体并直接发送，跨平台复现（不依赖 curl）。"""
    settings = Settings.from_env()
    experiment_id, _, raw_value = args.replay.partition("@")
    experiments = build_all(settings)
    experiment = next((item for item in experiments if item.id == experiment_id), None)
    if experiment is None:
        print(f"未知实验 id: {experiment_id}", file=sys.stderr)
        return 2
    built = experiment.build(float(raw_value) if raw_value else None)
    print(
        f"实验 {experiment.id} | {experiment.protocol.label} | "
        f"请求体 {len(built.body):,} 字节",
        flush=True,
    )
    transport = Transport(settings.host, settings.timeout_s)
    result = transport.post(
        experiment.protocol.path,
        experiment.protocol.headers(settings.api_key),
        built.body,
    )
    print(f"HTTP {result.status} | {result.elapsed_s:.2f}s", flush=True)
    if result.payload is not None:
        print(redact(json.dumps(result.payload, ensure_ascii=False, indent=2))[:4000])
    elif result.text:
        print(redact(result.text)[:4000])
    if result.error:
        print(redact(result.error))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    settings = _settings()
    for experiment in build_all(settings, _selection(args.suite), _selection(args.protocol)):
        values = experiment.values()
        suffix = f" points={values}" if values else ""
        print(f"{experiment.id:<28} {experiment.protocol.key:<9} {experiment.title}{suffix}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", default="all", help=f"all 或 {','.join(SUITES)}")
    parser.add_argument("--protocol", default="all", help="all / openai / responses / anthropic")
    parser.add_argument("--out", default=str(ROOT / "results"), help="结果目录")
    parser.add_argument("--resume", action="store_true", help="跳过已完成的实验")
    parser.add_argument("--only", default="", help="只跑指定实验 id（逗号分隔），并替换其历史记录")
    parser.add_argument("--force", action="store_true", help="重跑所选实验并替换其历史记录")
    parser.add_argument("--dry-run", action="store_true", help="只构建载荷，不发请求")
    parser.add_argument("--list", action="store_true", help="列出实验与探测点")
    parser.add_argument("--dump-body", metavar="EXP[@VALUE]", help="输出某实验的请求体")
    parser.add_argument(
        "--replay", metavar="EXP[@VALUE]", help="重建请求并直接发送（跨平台复现，不依赖 curl）"
    )
    parser.add_argument("--report-only", action="store_true", help="由 results.json 重出报告")
    args = parser.parse_args()

    _utf8_console()

    if args.report_only:
        return cmd_report(args)
    if args.replay:
        return cmd_replay(args)
    if args.dump_body:
        return cmd_dump(args)
    if args.list:
        return cmd_list(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
