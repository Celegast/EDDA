@echo off
setlocal

echo === EDDA update ===

:: ---------------------------------------------------------------
:: Step 1: Git pull
:: ---------------------------------------------------------------
echo.
echo [1/6] Pulling latest changes...
where git >nul 2>&1
if errorlevel 1 (
    echo   git not found - skipping pull.
    echo   Download the latest release manually from the repository.
    goto step2
)
if not exist .git (
    echo   Not a git repository - skipping pull.
    goto step2
)
git pull
if errorlevel 1 ( echo git pull failed & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 2: Virtual environment
:: ---------------------------------------------------------------
:step2
echo.
echo [2/6] Virtual environment...
if exist .venv (
    echo   .venv already exists.
    goto step3
)

echo   Creating .venv...
set "PYTHON="
python -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON=python"

if not defined PYTHON (
    py -3.12 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=py -3.12"
)

if not defined PYTHON (
    echo Error: Python 3.12 or newer not found.
    echo Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)

%PYTHON% -m venv .venv
if errorlevel 1 ( echo Failed to create .venv & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 3: Install / sync dependencies
:: ---------------------------------------------------------------
:step3
echo.
echo [3/6] Installing current version...
.venv\Scripts\pip install -e . --quiet
if errorlevel 1 ( echo Installation failed & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 4: Import journal data
:: ---------------------------------------------------------------
echo.
echo [4/6] Importing journal data...
.venv\Scripts\edda-import
if errorlevel 1 ( echo Import failed & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 5: Rebuild maps and charts
:: ---------------------------------------------------------------
echo.
echo [5/6] Rebuilding maps and charts...
.venv\Scripts\edda-map
if errorlevel 1 ( echo Map build failed & pause & exit /b 1 )
.venv\Scripts\edda-charts
if errorlevel 1 ( echo Chart build failed & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 6: Rebuild dashboard
:: ---------------------------------------------------------------
echo.
echo [6/6] Rebuilding dashboard...
.venv\Scripts\edda-dashboard
if errorlevel 1 ( echo Dashboard build failed & pause & exit /b 1 )

echo.
echo Done.  Open dashboard.html in a browser.
endlocal
pause
