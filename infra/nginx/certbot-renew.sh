#!/usr/bin/env bash
# Phase 4.2.6 — Let's Encrypt 인증서 자동 갱신.
# crontab 0 4 * * * /opt/pipeline-hub/infra/nginx/certbot-renew.sh

set -euo pipefail

DOMAINS=("api.datapipeline.co.kr" "app.datapipeline.co.kr")

for d in "${DOMAINS[@]}"; do
    docker run --rm \
        -v /etc/letsencrypt:/etc/letsencrypt \
        -v /var/lib/letsencrypt:/var/lib/letsencrypt \
        -v /var/log/letsencrypt:/var/log/letsencrypt \
        certbot/certbot:latest \
        renew --quiet --no-random-sleep-on-renew \
              --deploy-hook "docker exec datapipeline-nginx nginx -s reload" \
              --cert-name "$d"
done
