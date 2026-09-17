#!/bin/sh
set -e

alembic -c database/alembic.ini upgrade head
python -m backend.core.seed

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
