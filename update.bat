@echo off
setlocal

echo === EDDA update ===

:: ---------------------------------------------------------------
:: Step 1: Git pull
:: ---------------------------------------------------------------
echo.
echo [1/5] Pulling latest changes...
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
:: Step 2: Sync dependencies
:: ---------------------------------------------------------------
:step2
echo.
echo [2/5] Installing dependencies...
set PDM=pdm
where pdm >nul 2>&1
if errorlevel 1 (
    python -m pdm --version >nul 2>&1
    if errorlevel 1 (
        echo Error: PDM not found.
        echo Install it with:  pip install pdm
        echo Then ensure the Python Scripts directory is in your PATH.
        echo Typical location: %APPDATA%\Python\PythonXXX\Scripts
        pause
        exit /b 1
    )
    set PDM=python -m pdm
)
%PDM% install
if errorlevel 1 ( echo Dependency install failed & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 3: Import journal data
:: ---------------------------------------------------------------
echo.
echo [3/5] Importing journal data...
%PDM% run import
if errorlevel 1 ( echo Import failed & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 4: Rebuild maps and charts
:: ---------------------------------------------------------------
echo.
echo [4/5] Rebuilding maps and charts...
%PDM% run map
if errorlevel 1 ( echo Map build failed & pause & exit /b 1 )
%PDM% run charts
if errorlevel 1 ( echo Chart build failed & pause & exit /b 1 )

:: ---------------------------------------------------------------
:: Step 5: Rebuild dashboard
:: ---------------------------------------------------------------
echo.
echo [5/5] Rebuilding dashboard...
%PDM% run dashboard
if errorlevel 1 ( echo Dashboard build failed & pause & exit /b 1 )

echo.
echo Done.  Open dashboard.html in a browser.
endlocal
pause
