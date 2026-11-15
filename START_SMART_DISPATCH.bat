@echo off
setlocal
cd /d "%~dp0"
echo Starting Smart Dispatch in local mode (no Docker required)...
start "Smart Dispatch Backend" cmd.exe /k ""%~dp0START_BACKEND.bat""
timeout /t 3 /nobreak >nul
start "Smart Dispatch Frontend" cmd.exe /k ""%~dp0START_FRONTEND.bat""
echo.
echo Two terminal windows have been opened.
echo Wait until both show that their servers are running, then open:
echo http://localhost:3000
 echo Backend API: http://localhost:8080/docs
echo.
pause
