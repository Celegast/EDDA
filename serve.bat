@echo off
setlocal

echo === EDDA Query Builder ===
echo.

if not exist ".venv" (
    echo ERROR: Virtual environment not found.
    echo Please run setup.bat first to install dependencies.
    echo.
    pause & exit /b 1
)

set PDM=pdm
where pdm >nul 2>&1
if errorlevel 1 (
    set PDM=python -m pdm
)

%PDM% run serve %*
if errorlevel 1 ( pause & exit /b 1 )
