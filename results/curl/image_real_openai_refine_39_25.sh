#!/usr/bin/env bash
# image-size-real / openai / 单图真实体积上限（高熵像素）
# 实测 HTTP 413  code=invalid_request_error
# message: Exceeded limit on max bytes per data-uri item : 52428800
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${DASHSCOPE_API_KEY:?请先导出 DASHSCOPE_API_KEY}"
: "${DASHSCOPE_WORKSPACE_ID:?请先导出 DASHSCOPE_WORKSPACE_ID}"
PAYLOAD="${TMPDIR:-/tmp}/bailian_image_real_openai_refine_39_25.json"
CFG="$(mktemp "${TMPDIR:-/tmp}/bailian_curl_cfg.XXXXXX")"
trap 'rm -f "$CFG" "$PAYLOAD"' EXIT
umask 077
cat > "$CFG" <<EOF
header = "Authorization: Bearer $DASHSCOPE_API_KEY"
header = "Content-Type: application/json"
EOF
PYTHON="${PYTHON:-python3}"
"$PYTHON" run_tests.py --dump-body 'image_real_openai@39.25' --out "$PAYLOAD"
echo "request body: $(wc -c < "$PAYLOAD") bytes"
curl -q -sS -X POST "https://${DASHSCOPE_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions" \
  --config "$CFG" \
  --data-binary @"$PAYLOAD" \
  -w '\nHTTP %{http_code} | upload %{size_upload} bytes | %{time_total}s\n'
