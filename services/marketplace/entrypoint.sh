#!/bin/sh
set -e

echo "Applying marketplace migrations..."
alembic upgrade head

echo "Seeding demo marketplace data..."
python seed.py

echo "Starting marketplace..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8002
