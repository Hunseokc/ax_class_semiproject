#!/bin/sh
# 추가 CA(예: 백신·사내 프록시의 TLS 검사 루트)가 /certs에 있으면 시스템 CA 번들에 합쳐 모든 HTTP 클라이언트가 쓰게 한다.
# requests(SEC·DART·pykrx)는 REQUESTS_CA_BUNDLE, curl_cffi(yfinance)는 CURL_CA_BUNDLE, 표준 ssl은 SSL_CERT_FILE을 읽는다.
set -e

SYSTEM_BUNDLE=/etc/ssl/certs/ca-certificates.crt
BUNDLE=/tmp/ca-bundle.pem

extra=$(find /certs -maxdepth 1 -type f \( -name '*.pem' -o -name '*.crt' \) 2>/dev/null | sort)
if [ -n "$extra" ]; then
    cat "$SYSTEM_BUNDLE" > "$BUNDLE"
    for f in $extra; do
        printf '\n' >> "$BUNDLE"
        cat "$f" >> "$BUNDLE"
    done
    export SSL_CERT_FILE="$BUNDLE" REQUESTS_CA_BUNDLE="$BUNDLE" CURL_CA_BUNDLE="$BUNDLE"
    echo "[entrypoint] 추가 CA $(echo "$extra" | wc -l)개를 CA 번들에 합침: $(echo $extra)"
else
    echo "[entrypoint] 추가 CA 없음 — 시스템 CA 번들 사용"
fi

exec "$@"
