@echo off
echo Stopping all running Python and Node processes to clear ghost workers...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM node.exe /T >nul 2>&1
echo Processes stopped. Starting fresh!
echo.
call run.bat
