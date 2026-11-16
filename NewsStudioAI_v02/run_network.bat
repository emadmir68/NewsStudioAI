@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run run_windows.bat first.&pause&exit /b 1)
echo.
echo IPv4 addresses on this computer:
ipconfig | findstr /i "IPv4"
echo.
echo Open http://COMPUTER-IP:8765 on another device in the same trusted LAN.
echo Do NOT expose this development server directly to the public internet.
echo.
".venv\Scripts\python.exe" -m uvicorn app:app --host 0.0.0.0 --port 8765
pause
