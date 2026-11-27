@echo off
pushd "%~dp0"
echo Starting Revora Application Services...
echo Starting the managed private Whisper tunnel supervisor on 127.0.0.1:18010...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev-whisper-tunnel.ps1" start
if errorlevel 1 echo WARNING: the managed Whisper tunnel did not start. Voice input will fail closed until it is started. Run scripts\dev-whisper-tunnel.ps1 status for details.

echo Applying migrations and starting FastAPI Backend (embedded review worker, up to 5 reviews) on port 8000...
start "Revora Backend" cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev-backend.ps1"

echo Starting Next.js Frontend on port 3000...
start "Revora Frontend" cmd /k "cd frontend && npm run dev"

echo Services started in separate terminal windows.
echo Backend (API + embedded review worker, max 5 reviews, same-repo reviews allowed): http://127.0.0.1:8000
echo Frontend: http://localhost:3000
