#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Seeding demo accounts..."
python seed.py

echo "Starting gateway-auth..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8001
