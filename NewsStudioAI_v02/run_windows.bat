@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (echo Install Python 3.11 x64 and enable Add Python to PATH.&pause&exit /b 1)
if not exist ".venv\Scripts\python.exe" (python -m venv .venv)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency installation failed.&pause&exit /b 1)
start "News Studio AI Server" cmd /k ""%~dp0.venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8765"
timeout /t 3 >nul
start "" http://127.0.0.1:8765
echo Keep the server window open while using News Studio AI.
