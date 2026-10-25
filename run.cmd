@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PORTFILE=%~dp0app\data\port.txt"
set "PORT=8791"
if exist "%PORTFILE%" for /f "usebackq delims=" %%p in ("%PORTFILE%") do set "PORT=%%p"
set "URL=http://127.0.0.1:!PORT!/"
set "PYW=pythonw"
for %%I in (python.exe) do set "PYDIR=%%~dp$PATH:I"
if exist "%PYDIR%pythonw.exe" set "PYW=%PYDIR%pythonw.exe"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.10+ and check "Add to PATH".
  pause
  exit /b 1
)

powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri '!URL!api/health' -TimeoutSec 1 -UseBasicParsing)|Out-Null;exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto starttray

echo [1/3] Starting service ...
start "HP Offline Server" /min "!PYW!" "%~dp0app\server.py" --port !PORT! >nul 2>nul

set /a tries=0
:wait
set /a tries+=1
if exist "%PORTFILE%" for /f "usebackq delims=" %%p in ("%PORTFILE%") do set "PORT=%%p"
set "URL=http://127.0.0.1:!PORT!/"
powershell -NoProfile -Command "try{(Invoke-WebRequest -Uri '!URL!api/health' -TimeoutSec 1 -UseBasicParsing)|Out-Null;exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto starttray
if !tries! geq 40 goto failed
ping -n 2 127.0.0.1 >nul
goto wait

:failed
echo.
echo [ERROR] Service did not start within 40s. Recent log:
if exist "%~dp0app\data\hp_offline.log" powershell -NoProfile -Command "Get-Content '%~dp0app\data\hp_offline.log' -Tail 15"
echo.
echo Try manually: python "%~dp0app\server.py" --port 8791
pause
exit /b 1

:starttray
echo [2/3] Starting tray icon ...
start "HP Offline Tray" /min powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0tray.ps1" -Port !PORT! >nul 2>nul
echo [3/3] Done.
echo.
echo HP Offline is running in the system tray (near the clock).
echo   - Double-click the tray icon to open the UI
echo   - Right-click: open / rescan printers / log / restart / quit
echo   - URL: !URL!
exit /b 0
