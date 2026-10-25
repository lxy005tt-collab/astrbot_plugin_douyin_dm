@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r standalone-requirements.txt
if errorlevel 1 goto failed
echo Dependencies installed. Run start.bat next.
pause
exit /b 0
:failed
echo Setup failed. Check Python installation and network, then read README.md.
pause
exit /b 1
