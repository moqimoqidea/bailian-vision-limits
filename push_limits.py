"""把「仍通过」的维度继续往前推，直到出现拒绝。

两个维度：
  image —— 单图原始字节数，按 Data URI 长度上限换算（50 MiB / 32 MiB）
  body  —— 6 张大文件的请求体总 MB 数

用法：
    python push_limits.py --model qwen3.8-flash --dim image --bytes 39300000,39321582,39321583
    python push_limits.py --model qwen3.8-flash --dim body  --mb 150,220,300
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from limits.config import Settings  # noqa: E402
from limits.fixtures import noise_png_of_size, png_of_size  # noqa: E402
from limits.protocols import PROTOCOLS, ImageAsset  # noqa: E402
from limits.transport import TRANSIENT, Transport  # noqa: E402
from limits.wire import image_payload  # noqa: E402

MiB = 1024 * 1024
BODY_IMAGES = 6
PROMPT = "这些图是什么颜色？只回答颜色。"
MAX_TOKENS = 8


def _image_payload(protocol, model: str, nbytes: int):
    asset = ImageAsset("image/png", noise_png_of_size(nbytes))
    assert len(asset.raw) == nbytes, (len(asset.raw), nbytes)
    return image_payload(protocol, model, PROMPT, [asset], MAX_TOKENS)


def _body_payload(protocol, model: str, body_mb: float):
    raw_total = int(body_mb * MiB * 0.75)
    per_image = max(raw_total // BODY_IMAGES, 4096)
    assets = [ImageAsset("image/png", png_of_size(per_image)) for _ in range(BODY_IMAGES)]
    return image_payload(protocol, model, PROMPT, assets, MAX_TOKENS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--dim", choices=("image", "body"), required=True)
    parser.add_argument("--bytes", default="", help="单图原始字节数，逗号分隔")
    parser.add_argument("--mb", default="", help="请求体目标 MB，逗号分隔")
    parser.add_argument("--protocol", default="openai")
    parser.add_argument("--out", default=None)
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
    protocol = PROTOCOLS[args.protocol]
    transport = Transport(settings.host, settings.timeout_s)
    out_dir = Path(args.out or f"results-push-{args.model}-{args.dim}")
    out_dir.mkdir(parents=True, exist_ok=True)
    journal = out_dir / "push.jsonl"

    points = (
        [int(value) for value in args.bytes.split(",") if value.strip()]
        if args.dim == "image"
        else [float(value) for value in args.mb.split(",") if value.strip()]
    )
    print(f"{args.model} | {args.dim} | {args.protocol} | {len(points)} 个点位", flush=True)

    rows = []
    for value in points:
        if args.dim == "image":
            built = _image_payload(protocol, settings.model, int(value))
            label = f"{int(value):,} B（{value / MiB:.3f} MiB 原图，Data URI {22 + 4 * ((int(value) + 2) // 3):,} B）"
        else:
            built = _body_payload(protocol, settings.model, value)
            label = f"{value:g} MB 请求体（{len(built.body):,} B）"
        started = time.time()
        result = transport.post(protocol.path, protocol.headers(settings.api_key), built.body)
        elapsed = round(time.time() - started, 1)
        verdict = (
            "通过"
            if result.accepted
            else ("断连" if result.kind == TRANSIENT else f"拒绝 HTTP {result.status}")
        )
        print(f"  {label} -> {verdict}  {elapsed}s  {result.error_fields()[2][:90]}", flush=True)
        row = {
            "dim": args.dim,
            "value": value,
            "protocol": args.protocol,
            "model": settings.model,
            "status": result.status,
            "accepted": result.accepted,
            "kind": result.kind,
            "elapsed_s": elapsed,
            "code": result.error_fields()[0],
            "message": result.error_fields()[2][:200],
            "body_bytes": len(built.body),
        }
        rows.append(row)
        with journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    lines = [
        f"# {settings.model} · {args.dim} 推进结果",
        "",
        "| 点位 | 请求体 | 结果 | 错误 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        value = f"{int(row['value']):,} B" if args.dim == "image" else f"{row['value']:g} MB"
        verdict = "通过" if row["accepted"] else (f"HTTP {row['status']}" if row["status"] else "断连")
        lines.append(f"| {value} | {row['body_bytes']:,} B | {verdict} | {row['message'][:80]} |")
    (out_dir / f"{args.dim}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n结果 -> {out_dir/f'{args.dim}.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
