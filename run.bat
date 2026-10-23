@echo off
REM Start the Course Equivalence app on localhost.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
)

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

echo.
echo   Course Equivalence  ^-  http://127.0.0.1:5000
echo.
%PY% -m pip install -q -r requirements.txt
%PY% app.py