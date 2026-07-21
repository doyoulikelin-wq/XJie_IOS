#!/usr/bin/env bash
set -euo pipefail

snippet="${1:?path to the exact-location snippet is required}"
config="/www/server/panel/vhost/nginx/jianjieaitech.com.conf"
updated="$(mktemp /tmp/jianjieaitech.com.conf.updated.XXXXXX)"
backup="${config}.bak.$(date +%Y%m%d%H%M%S)"

cleanup() {
    rm -f "$updated"
}
trap cleanup EXIT

if grep -q 'location = /api/chat/stream' "$config"; then
    echo "nginx_exact_route_already_present=1"
    exit 0
fi

cp "$config" "$backup"
sed '\|# 后端接口转发到 FastAPI|r '"$snippet" "$config" > "$updated"
grep -q 'location = /api/chat/stream' "$updated"
grep -q 'location = /privacy' "$updated"
install -o root -g root -m 644 "$updated" "$config"

if ! nginx -t; then
    cp "$backup" "$config"
    nginx -t
    exit 1
fi

nginx -s reload
echo "nginx_backup=$backup"
