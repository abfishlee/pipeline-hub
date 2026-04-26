#!/usr/bin/env bash
# Phase 4.2.6 — nginx 보안 헤더 + HTTPS redirect 검증.
# 사용법:
#   ./test_headers.sh https://api.datapipeline.co.kr
#   ./test_headers.sh https://app.datapipeline.co.kr

set -euo pipefail

URL="${1:-https://api.datapipeline.co.kr}"
HTTP_URL="${URL/https:/http:}"

echo "===> Testing $URL"

# 1) HTTP → 301 redirect.
status=$(curl -sk -o /dev/null -w "%{http_code}" "$HTTP_URL")
if [[ "$status" != "301" ]]; then
    echo "FAIL: HTTP did not redirect (got $status)"
    exit 1
fi
echo "PASS: HTTP → 301 redirect"

# 2) HTTPS 응답 헤더.
headers=$(curl -sIk "$URL")

require_header() {
    local name="$1"
    local pattern="$2"
    if echo "$headers" | grep -iq "^$name:.*$pattern"; then
        echo "PASS: $name 포함"
    else
        echo "FAIL: $name 누락 또는 패턴 불일치 ($pattern)"
        exit 1
    fi
}

require_header "Strict-Transport-Security" "max-age=63072000"
require_header "X-Frame-Options"            "DENY"
require_header "X-Content-Type-Options"     "nosniff"
require_header "Referrer-Policy"            "strict-origin"

echo "===> All header checks passed"
