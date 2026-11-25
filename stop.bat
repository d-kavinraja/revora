@echo off
echo Stopping the managed Revora Whisper tunnel supervisor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev-whisper-tunnel.ps1" stop
if errorlevel 1 echo WARNING: the managed Whisper tunnel could not be stopped cleanly. Run scripts\dev-whisper-tunnel.ps1 status for details.
echo Close the Revora Backend and Revora Frontend terminal windows separately.
