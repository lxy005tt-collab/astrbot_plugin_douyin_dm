@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m mimi_douyin serve --data-dir "%~dp0data"
pause
