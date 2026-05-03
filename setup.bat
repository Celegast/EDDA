@echo off
setlocal

echo === EDDA setup ===
echo.

:: Find Python 3.12+
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
    exit /b 1
)

echo Creating virtual environment...
%PYTHON% -m venv .venv
if errorlevel 1 ( echo Failed to create .venv & exit /b 1 )

echo Installing EDDA...
.venv\Scripts\pip install -e . --quiet
if errorlevel 1 ( echo Installation failed & exit /b 1 )

echo.
echo Done. Run update.bat to import journals and build the dashboard.
endlocal
