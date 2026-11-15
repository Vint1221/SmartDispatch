@echo off
setlocal
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Run INSTALL_TOOLS.ps1 first.
  pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo npm was not found. Reinstall Node.js LTS and reopen the terminal.
  pause
  exit /b 1
)

echo Checking and installing frontend dependencies...
call npm install --no-audit --no-fund
if errorlevel 1 goto fail

echo.
echo Frontend starting at http://localhost:3000
echo Keep this window open while using the application.
echo.
call npm run dev
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo Frontend setup/start failed. Read the error above.
pause
exit /b 1
