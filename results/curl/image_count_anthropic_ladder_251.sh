#!/usr/bin/env bash
# image-count / anthropic / Base64 图片张数上限
# 实测 HTTP 400  code=BadRequest.TooLarge
# message: Exceeded limit on max number of data-uri items : 250
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${DASHSCOPE_API_KEY:?请先导出 DASHSCOPE_API_KEY}"
: "${DASHSCOPE_WORKSPACE_ID:?请先导出 DASHSCOPE_WORKSPACE_ID}"
PAYLOAD="${TMPDIR:-/tmp}/bailian_image_count_anthropic_ladder_251.json"
CFG="$(mktemp "${TMPDIR:-/tmp}/bailian_curl_cfg.XXXXXX")"
trap 'rm -f "$CFG" "$PAYLOAD"' EXIT
umask 077
cat > "$CFG" <<EOF
header = "x-api-key: $DASHSCOPE_API_KEY"
header = "Content-Type: application/json"
EOF
PYTHON="${PYTHON:-python3}"
"$PYTHON" run_tests.py --dump-body 'image_count_anthropic@251' --out "$PAYLOAD"
echo "request body: $(wc -c < "$PAYLOAD") bytes"
curl -q -sS -X POST "https://${DASHSCOPE_WORKSPACE_ID}.cn-beijing.maas.aliyuncs.com/apps/anthropic/v1/messages" \
  --config "$CFG" \
  --data-binary @"$PAYLOAD" \
  -w '\nHTTP %{http_code} | upload %{size_upload} bytes | %{time_total}s\n'
