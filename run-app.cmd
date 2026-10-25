@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PORT=8791"
set "URL=http://127.0.0.1:%PORT%/"
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  pause
  exit /b 1
)

powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri '%URL%api/health' -TimeoutSec 1 -UseBasicParsing)|Out-Null;exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto openui
echo [1/2] Starting local service ...
start "HP Offline Server" /min python "%~dp0app\server.py" --port %PORT%
set /a tries=0
:wait
set /a tries+=1
powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri '%URL%api/health' -TimeoutSec 1 -UseBasicParsing)|Out-Null;exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto openui
if %tries% geq 40 (
  echo [ERROR] Service start timeout. See app\data\hp_offline.log
  pause
  exit /b 1
)
timeout /t 1 >nul
goto wait

:openui
echo [2/2] Opening app window ...
if not exist "%EDGE%" (
  echo [INFO] Edge not found, using default browser.
  start "" "%URL%"
  goto done
)
start "" "%EDGE%" --app="%URL%" --user-data-dir="%~dp0app\data\edge-profile" --no-first-run --no-default-browser-check
echo If no window appeared, use run.cmd or open %URL% manually.
:done
timeout /t 3 >nul
exit /b 0
