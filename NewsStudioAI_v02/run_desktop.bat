@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (echo Install Python 3.11 x64 and enable Add Python to PATH.&pause&exit /b 1)
if not exist ".venv\Scripts\python.exe" (python -m venv .venv)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-desktop.txt
if errorlevel 1 (echo Desktop dependencies failed.&pause&exit /b 1)
".venv\Scripts\python.exe" launcher.py
