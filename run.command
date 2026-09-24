#!/bin/bash

echo "========================================"
echo " Starting Revora Application Services"
echo "========================================"

# Get the directory where this script is located
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Project directory: $PROJECT_DIR"

# ----------------------------------------
# Run Database Migrations
# ----------------------------------------
echo ""
echo "Running Alembic database migrations..."

cd "$PROJECT_DIR/backend" || {
    echo "ERROR: Backend directory not found."
    exit 1
}

export PYTHONPATH=.

./venv/bin/alembic upgrade head

if [ $? -ne 0 ]; then
    echo "ERROR: Database migration failed."
    exit 1
fi

echo "Database migration completed successfully."

# ----------------------------------------
# Start FastAPI Backend
# ----------------------------------------
echo ""
echo "Starting FastAPI Backend on port 8000..."

osascript <<EOF
tell application "Terminal"
    do script "cd '$PROJECT_DIR/backend' && export PYTHONPATH=. && ./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
end tell
EOF

# ----------------------------------------
# Start Queue Worker
# ----------------------------------------
echo "Starting Revora Queue Worker..."

osascript <<EOF
tell application "Terminal"
    do script "cd '$PROJECT_DIR/backend' && export PYTHONPATH=. && ./venv/bin/python -m app.queue.worker"
end tell
EOF

# ----------------------------------------
# Start Next.js Frontend
# ----------------------------------------
echo "Starting Next.js Frontend on port 3000..."

osascript <<EOF
tell application "Terminal"
    do script "cd '$PROJECT_DIR/frontend' && npm run dev"
end tell
EOF

echo ""
echo "========================================"
echo " All Revora services started!"
echo "========================================"
echo ""
echo "Backend:  http://127.0.0.1:8000"
echo "Frontend: http://localhost:3000"
echo ""