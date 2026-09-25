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

if [ ! -x "./venv/bin/python" ]; then
    echo "ERROR: Python venv not found at backend/venv."
    echo "Create it first:"
    echo "  cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
    exit 1
fi

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
echo "Queue worker is started by the FastAPI backend (embedded)."

osascript <<EOF
tell application "Terminal"
    do script "cd '$PROJECT_DIR/backend' && export PYTHONPATH=. && ./venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
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
