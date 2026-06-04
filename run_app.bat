@echo off
REM Launch ActinTrackCV GUI (Windows)
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
)

python run_app.py %*
set EXITCODE=%ERRORLEVEL%
endlocal & exit /b %EXITCODE%
