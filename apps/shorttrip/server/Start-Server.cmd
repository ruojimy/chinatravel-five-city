@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if exist "combined version_personalized\.venv\Scripts\python.exe" goto usevenv
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 goto uselauncher
python3.12.exe -c "import sys" >nul 2>nul
if not errorlevel 1 goto use312
python start_server.py %*
goto finish
:usevenv
"combined version_personalized\.venv\Scripts\python.exe" start_server.py %*
goto finish
:uselauncher
py -3.12 start_server.py %*
goto finish
:use312
python3.12.exe start_server.py %*
:finish
set "ST_SERVER_EXIT=%ERRORLEVEL%"
if not "%ST_SERVER_EXIT%"=="0" pause
exit /b %ST_SERVER_EXIT%
