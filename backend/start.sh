#!/bin/sh
set -e

# Retry migrations a bounded number of times: the database may still be waking up
# (Neon scale-to-zero). Fail the start after the last attempt so the platform restarts it.
attempts=5
delay=3
n=1
until alembic upgrade head; do
    if [ "$n" -ge "$attempts" ]; then
        echo "alembic upgrade head failed after $attempts attempts" >&2
        exit 1
    fi
    echo "alembic upgrade head failed (attempt $n/$attempts), retrying in ${delay}s" >&2
    n=$((n + 1))
    sleep "$delay"
done

exec uvicorn eventssound.entrypoints.api.app:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"
