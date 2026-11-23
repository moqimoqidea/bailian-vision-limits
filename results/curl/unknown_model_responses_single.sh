#!/usr/bin/env bash
# misc / responses / 不存在的模型名
# 实测 HTTP 404  code=MODEL_NOT_FOUND
# message: Model not found: qwen3.8-flash-does-not-exist
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${DASHSCOPE_API_KEY:?请先导出 DASHSCOPE_API_KEY}"
: "${DASHSCOPE_WORKSPACE_ID:?请先导出 DASHSCOPE_WORKSPACE_ID}"
PAYLOAD="${TMPDIR:-/tmp}/bailian_unknown_model_responses_single.json"
CFG="$(mktemp "${TMPDIR:-/tmp}/bailian_curl_cfg.XXXXXX")"
trap 'rm -f "$CFG" "$PAYLOAD"' EXIT
umask 077
cat > "$CFG" <<EOF
header = "Authorization: Bearer $DASHSCOPE_API_KEY"
header = "Content-Type: application/json"
EOF
PYTHON="${PYTHON:-python3}"
"$PYTHON" run_tests.py --dump-body 'unknown_model_responses' --out "$PAYLOAD"
echo "request body: $(wc -c < "$PAYLOAD") bytes"
curl -q -sS -X POST "https://${DASHSCOPE_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/responses" \
  --config "$CFG" \
  --data-binary @"$PAYLOAD" \
  -w '\nHTTP %{http_code} | upload %{size_upload} bytes | %{time_total}s\n'
