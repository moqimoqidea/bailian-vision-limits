#!/usr/bin/env bash
# image-format / responses / 4200×20 PNG
# 实测 HTTP 400  code=InvalidParameter
# message: <400> InternalError.Algo.InvalidParameter: The image length and width do not meet the model restrictions. [absolute aspect ratio must be smaller than 200, got 20 / 4200]
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${DASHSCOPE_API_KEY:?请先导出 DASHSCOPE_API_KEY}"
: "${DASHSCOPE_WORKSPACE_ID:?请先导出 DASHSCOPE_WORKSPACE_ID}"
PAYLOAD="${TMPDIR:-/tmp}/bailian_fmt_aspect_210_responses_single.json"
CFG="$(mktemp "${TMPDIR:-/tmp}/bailian_curl_cfg.XXXXXX")"
trap 'rm -f "$CFG" "$PAYLOAD"' EXIT
umask 077
cat > "$CFG" <<EOF
header = "Authorization: Bearer $DASHSCOPE_API_KEY"
header = "Content-Type: application/json"
EOF
PYTHON="${PYTHON:-python3}"
"$PYTHON" run_tests.py --dump-body 'fmt_aspect_210_responses' --out "$PAYLOAD"
echo "request body: $(wc -c < "$PAYLOAD") bytes"
curl -q -sS -X POST "https://${DASHSCOPE_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/responses" \
  --config "$CFG" \
  --data-binary @"$PAYLOAD" \
  -w '\nHTTP %{http_code} | upload %{size_upload} bytes | %{time_total}s\n'
