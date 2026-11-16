@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run run_windows.bat first.&pause&exit /b 1)
".venv\Scripts\python.exe" -m pip install -r requirements-ai.txt
if errorlevel 1 (echo Whisper install failed.&pause&exit /b 1)
echo Whisper installed. Restart News Studio AI.
pause
