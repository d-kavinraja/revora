@echo off
echo Starting Revora Application Services...

echo Starting FastAPI Backend on port 8000...
start "Revora Backend" cmd /k "cd backend && set PYTHONPATH=.&& venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

echo Starting Next.js Frontend on port 3000...
start "Revora Frontend" cmd /k "cd frontend && npm run dev"

echo Both services started in separate terminal windows.
echo Backend: http://127.0.0.1:8000
echo Frontend: http://localhost:3000
