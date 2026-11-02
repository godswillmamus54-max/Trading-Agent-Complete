
@echo off
setlocal

cd /d "%~dp0"

echo ================================================
echo V28.5.2 MT5 TRADING AGENT
echo ================================================

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment not found.
    echo Please install the project requirements first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "start_trading_agent.py"

echo.
echo Trading agent session closed.
pause
