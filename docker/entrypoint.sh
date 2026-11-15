#!/bin/sh
# Applies database migrations, seeds missing reference prices, then starts the server.
set -e

echo "Applying database migrations..."
alembic upgrade head

python -m app.cli seed-pricing

# One worker by default: the rate limiter is in-process (see SECURITY.md).
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --no-proxy-headers \
  --workers "${WEB_CONCURRENCY:-1}" \
  --no-server-header
