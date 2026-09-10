#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

if [ "${ENABLE_DEMO_SEED:-false}" = "true" ]; then
    echo "Seeding demo accounts..."
    python seed.py
fi

echo "Starting gateway-auth..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --no-proxy-headers --no-access-log
