#!/usr/bin/env bash
# image-format / openai / 0 字节图像
# 实测 HTTP 400  code=invalid_parameter_error
# message: The provided URL does not appear to be valid. Ensure it is correctly formatted.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${DASHSCOPE_API_KEY:?请先导出 DASHSCOPE_API_KEY}"
: "${DASHSCOPE_WORKSPACE_ID:?请先导出 DASHSCOPE_WORKSPACE_ID}"
PAYLOAD="${TMPDIR:-/tmp}/bailian_fmt_empty_openai_single.json"
CFG="$(mktemp "${TMPDIR:-/tmp}/bailian_curl_cfg.XXXXXX")"
trap 'rm -f "$CFG" "$PAYLOAD"' EXIT
umask 077
cat > "$CFG" <<EOF
header = "Authorization: Bearer $DASHSCOPE_API_KEY"
header = "Content-Type: application/json"
EOF
PYTHON="${PYTHON:-python3}"
"$PYTHON" run_tests.py --dump-body 'fmt_empty_openai' --out "$PAYLOAD"
echo "request body: $(wc -c < "$PAYLOAD") bytes"
curl -q -sS -X POST "https://${DASHSCOPE_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions" \
  --config "$CFG" \
  --data-binary @"$PAYLOAD" \
  -w '\nHTTP %{http_code} | upload %{size_upload} bytes | %{time_total}s\n'
