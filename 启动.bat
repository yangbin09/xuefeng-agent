@echo off
cd /d "%~dp0"
echo Checking openpyxl...
pip install openpyxl 2>nul || python -m pip install openpyxl 2>nul || py -3 -m pip install openpyxl 2>nul

netstat -ano | findstr ":8765 " | findstr LISTENING >nul
if not errorlevel 1 (
  echo.
  echo [WARN] Port 8765 is already in use - the server is probably already running.
  echo        Just open http://127.0.0.1:8765/  , or close the old window first.
  echo.
  pause
  exit /b 1
)

echo Starting...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 server.py
) else (
  python server.py
)
pause
