@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (echo Python 3.11 x64 not found.&pause&exit /b 1)
if not exist ".venv\Scripts\python.exe" (python -m venv .venv)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-ai.txt -r requirements-desktop.txt pyinstaller
if errorlevel 1 (echo Build dependencies failed.&pause&exit /b 1)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean NewsStudioAI.spec
if errorlevel 1 (echo EXE build failed.&pause&exit /b 1)
echo.
echo EXE created: dist\NewsStudioAI\NewsStudioAI.exe
if exist "vendor\ffmpeg\bin\ffmpeg.exe" (
  echo FFmpeg is bundled with the application.
) else (
  echo WARNING: FFmpeg is not bundled. Install FFmpeg and add it to PATH on the target PC.
)
echo To create Setup, install Inno Setup and compile installer\NewsStudioAI.iss.
pause
