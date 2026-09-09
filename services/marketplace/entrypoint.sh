#!/bin/sh
set -e

echo "Applying marketplace migrations..."
alembic upgrade head

echo "Seeding demo marketplace data..."
if [ "${ENABLE_DEMO_SEED:-false}" = "true" ]; then
    python seed.py
fi

echo "Starting marketplace..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --no-proxy-headers --no-access-log
