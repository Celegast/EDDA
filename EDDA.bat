@echo off
setlocal

if not exist ".venv" (
    echo ERROR: Virtual environment not found.
    echo Please run setup.bat first to install dependencies.
    echo.
    pause & exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" -c "from edda.gui import main; main()"
