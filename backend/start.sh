#!/bin/bash

# Exit on any error
set -e

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting Queue Worker in background..."
python -m app.queue.worker &

echo "Starting FastAPI server..."
# Using the PORT environment variable provided by Render
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
