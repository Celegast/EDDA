@echo off
setlocal

echo === EDDA Query Builder ===
echo.

set PDM=pdm
where pdm >nul 2>&1
if errorlevel 1 (
    set PDM=python -m pdm
)

%PDM% run serve %*
if errorlevel 1 ( pause & exit /b 1 )
