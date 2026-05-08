@echo off
setlocal

echo === EDDA setup ===
echo.

set PDM=pdm
where pdm >nul 2>&1
if errorlevel 1 (
    echo   PDM not found. Installing...
    pip install pdm
    if errorlevel 1 ( echo Failed to install PDM & pause & exit /b 1 )
    set PDM=python -m pdm
)

echo Installing dependencies...
%PDM% sync
if errorlevel 1 ( echo Installation failed & pause & exit /b 1 )

echo.
echo Done. Run update.bat to import journals and build the dashboard.
endlocal
pause
