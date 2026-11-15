@echo off
setlocal
cd /d "%~dp0backend"

REM Prefer the Python launcher when available; otherwise use the python command.
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 --version >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)
if not defined PYTHON_CMD (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3.12 and reopen VS Code.
    pause
    exit /b 1
  )
  set "PYTHON_CMD=python"
)

%PYTHON_CMD% --version
if errorlevel 1 goto fail

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version >nul 2>nul
  if errorlevel 1 (
    echo Existing Python environment is invalid. Recreating it...
    rmdir /s /q ".venv"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python virtual environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto fail
)

set "PY=.venv\Scripts\python.exe"
if exist ".venv\.smart_dispatch_deps_ok" (
  "%PY%" -c "import fastapi, uvicorn, sqlalchemy, ortools" >nul 2>nul
  if errorlevel 1 del ".venv\.smart_dispatch_deps_ok"
)
if not exist ".venv\.smart_dispatch_deps_ok" (
  echo Installing backend dependencies. First run may take several minutes...
  "%PY%" -m pip install --upgrade pip
  if errorlevel 1 goto fail
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 goto fail
  type nul > ".venv\.smart_dispatch_deps_ok"
)

set "DATABASE_URL=sqlite:///./smart_dispatch.db"
set "TEAM_NAME=Smart Dispatch DEMO"
set "APP_VERSION=1.0.0"
echo.
echo Backend starting at http://localhost:8080
 echo Swagger: http://localhost:8080/docs
 echo Local database: backend\smart_dispatch.db (SQLite)
echo Keep this window open while using the application.
echo.
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --timeout-keep-alive 340
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo Backend setup/start failed. Read the error above.
pause
exit /b 1
