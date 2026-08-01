#!/bin/bash

# Exit on any error
set -e

# Memory & C-library allocations optimizations for 512MB RAM free tier
export MALLOC_ARENA_MAX=2
export MALLOC_TRIM_THRESHOLD_=65536
export PYTHONUNBUFFERED=1
export PYTHONOPTIMIZE=1
export PYTHONHASHSEED=0
export WEB_CONCURRENCY=1

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting FastAPI server..."
# Limit workers to 1 and restrict concurrency to save RAM on free tier
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --limit-concurrency 30 --timeout-keep-alive 5
