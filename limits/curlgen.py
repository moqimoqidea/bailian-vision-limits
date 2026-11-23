"""Generate standalone curl scripts for failing cases.

Large payloads (20 MB images, 64 MB bodies) cannot be inlined into a shell
script, so each script first asks the CLI to rebuild the *exact* request body
from the same code path, then posts it with curl.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .config import Settings
from .protocols import PROTOCOLS
from .records import Record
from .redact import redact

_SAFE = re.compile(r"[^a-z0-9_]+")
_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _cmd_script(body_arg: str) -> str:
    """Windows 复现脚本：直接调用内置的 --replay，不依赖 curl 与 bash。"""
    lines = [
        "@echo off",
        "setlocal",
        "rem Replay one failing case; no curl required.",
        'cd /d "%~dp0..\\.."',
        'if "%DASHSCOPE_API_KEY%"=="" (',
        "  echo Please export DASHSCOPE_API_KEY first.",
        "  exit /b 1",
        ")",
        'if "%DASHSCOPE_WORKSPACE_ID%"=="" (',
        "  echo Please export DASHSCOPE_WORKSPACE_ID first.",
        "  exit /b 1",
        ")",
        f'python run_tests.py --replay "{body_arg}"',
        "",
    ]
    return "\r\n".join(lines)


def _slug(record: Record) -> str:
    raw = f"{record.experiment_id}_{record.probe}".lower()
    return _SAFE.sub("_", raw).strip("_")


def _safe_text(value: object, limit: int = 240) -> str:
    """把任意文本压成单行：注释与命令行都不能被换行/引号改写结构。"""
    text = _CONTROL.sub(" ", redact(value)).replace("\r", " ").replace("\n", " ")
    return text.replace("#!", "# !")[:limit]


def _header_config(protocol_key: str) -> str:
    """认证头通过 curl 配置文件传入，不出现在进程参数里。"""
    auth = (
        'header = "x-api-key: $DASHSCOPE_API_KEY"'
        if protocol_key == "anthropic"
        else 'header = "Authorization: Bearer $DASHSCOPE_API_KEY"'
    )
    return "\n".join([auth, 'header = "Content-Type: application/json"'])


def _cd_command(out_dir: Path) -> str:
    """脚本放在 <root>/results/curl 时用相对路径，保证换机器也能跑。"""
    try:
        relative = out_dir.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return f'cd "{PROJECT_ROOT}"'
    ups = "/".join(".." for _ in relative.parts)
    return f'cd "$(dirname "$0")/{ups}"'


def write_scripts(records: list[Record], settings: Settings, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cd_command = _cd_command(out_dir)
    written: list[Path] = []
    for record in records:
        if record.accepted:
            continue
        protocol = PROTOCOLS[record.protocol]
        if not _EXPERIMENT_ID.fullmatch(record.experiment_id):
            print(f"跳过非法实验 id：{record.experiment_id!r}", file=sys.stderr)
            continue
        body_arg = record.experiment_id
        if record.axis_value is not None:
            body_arg = f"{record.experiment_id}@{record.axis_value:g}"
        payload_path = f"${{TMPDIR:-/tmp}}/bailian_{_slug(record)}.json"
        header_config = _header_config(record.protocol)
        url = "${DASHSCOPE_WORKSPACE_ID}.%s.maas.aliyuncs.com%s" % (
            settings.region,
            protocol.path,
        )
        script = f"""#!/usr/bin/env bash
# {_safe_text(record.suite)} / {_safe_text(record.protocol)} / {_safe_text(record.title)}
# 实测 HTTP {int(record.status)}  code={_safe_text(record.error_code or record.error_type or '-')}
# message: {_safe_text(record.error_message)}
set -euo pipefail
{cd_command}
: "${{DASHSCOPE_API_KEY:?请先导出 DASHSCOPE_API_KEY}}"
: "${{DASHSCOPE_WORKSPACE_ID:?请先导出 DASHSCOPE_WORKSPACE_ID}}"
PAYLOAD="{payload_path}"
CFG="$(mktemp "${{TMPDIR:-/tmp}}/bailian_curl_cfg.XXXXXX")"
trap 'rm -f "$CFG" "$PAYLOAD"' EXIT
umask 077
cat > "$CFG" <<EOF
{header_config}
EOF
PYTHON="${{PYTHON:-python3}}"
"$PYTHON" run_tests.py --dump-body '{body_arg}' --out "$PAYLOAD"
echo "request body: $(wc -c < "$PAYLOAD") bytes"
curl -q -sS -X POST "https://{url}" \\
  --config "$CFG" \\
  --data-binary @"$PAYLOAD" \\
  -w '\\nHTTP %{{http_code}} | upload %{{size_upload}} bytes | %{{time_total}}s\\n'
"""
        path = out_dir / f"{_slug(record)}.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        if os.name == "posix":
            path.chmod(0o755)
        cmd_path = out_dir / f"{_slug(record)}.cmd"
        cmd_path.write_text(_cmd_script(body_arg), encoding="utf-8", newline="")
        written.append(path)

    index = [
        "# 失败用例复现脚本",
        "",
        "每个用例都有两份：",
        "",
        "- `*.sh`：用 curl 重放（macOS / Linux）",
        "- `*.cmd`：Windows 双击或命令行执行，内部调用 `python run_tests.py --replay`",
        "",
        "先设置环境变量：",
        "",
        "```bash",
        "export DASHSCOPE_API_KEY='sk-...'",
        "export DASHSCOPE_WORKSPACE_ID='ws-...'",
    ]
    index += [f"bash {path.name}" for path in written]
    index += [
        "```",
        "",
        "Windows 下把 `bash xxx.sh` 换成 `xxx.cmd` 即可（或在 PowerShell 里执行）。",
        "两者重放的是同一个请求体。",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(index), encoding="utf-8")
    return written
