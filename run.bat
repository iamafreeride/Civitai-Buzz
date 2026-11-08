@echo off
rem ---------------------------------------------------------------------------
rem  Civitai daily 25 Buzz
rem  Double-click on Windows. First run creates .venv and installs selenium.
rem  Paste your cookie string when asked (or put CIVITAI_COOKIE=... in .env).
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="CIVITAI_COOKIE" set "CIVITAI_COOKIE=%%B"
        if /i "%%A"=="USER_AGENT" set "USER_AGENT=%%B"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed
)

if not defined BROWSER set "BROWSER=edge"
if not defined SE_CACHE_PATH set "SE_CACHE_PATH=%~dp0.selenium"

".venv\Scripts\python.exe" buzz.py %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Done.
) else (
    echo Finished with exit code %RC%.
    echo If Cloudflare blocked it, refresh cf_clearance and make USER_AGENT match your browser.
)
echo.
pause
exit /b %RC%

:nopython
echo.
echo Python was not found. Install Python 3.9+ from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup.
pause
exit /b 1

:failed
echo.
echo Setup failed - see the messages above.
pause
exit /b 1
