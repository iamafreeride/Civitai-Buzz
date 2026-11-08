@echo off
rem ---------------------------------------------------------------------------
rem  Civitai daily 25 Buzz  (Windows, no Docker)
rem  Double-click to run. First run creates .venv and installs selenium.
rem
rem  Cookie / User-Agent are asked here and kept in this process only.
rem  Nothing is written to disk - do not put them in a file inside this repo.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if not defined CIVITAI_COOKIE set /p CIVITAI_COOKIE=Cookie (name=value; ...): 
if not defined USER_AGENT set /p USER_AGENT=User-Agent (optional, Enter to skip): 

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :failed
)

if not defined BROWSER set "BROWSER=edge"

".venv\Scripts\python.exe" buzz.py %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo Done.
) else (
    echo Finished with exit code %RC%.
    echo If Cloudflare blocked it, refresh the cookie and make USER_AGENT match your browser.
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
