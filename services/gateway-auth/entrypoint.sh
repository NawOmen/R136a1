#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Seeding demo accounts..."
if [ "${ENABLE_DEMO_SEED:-false}" = "true" ]; then
    python seed.py
fi

echo "Starting gateway-auth..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --no-proxy-headers --no-access-log
