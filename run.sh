#!/bin/sh
set -eu

port="${PORT:-${APP_PORT:-8000}}"
workers="${WEB_CONCURRENCY:-1}"

alembic upgrade head

exec uvicorn events_aggregator.main:app \
    --host "${APP_HOST:-0.0.0.0}" \
    --port "$port" \
    --workers "$workers" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
