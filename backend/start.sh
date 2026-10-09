#!/bin/sh
set -e
alembic upgrade head
exec uvicorn eventssound.entrypoints.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"
