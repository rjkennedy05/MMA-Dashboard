@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python run_bot.py
) else (
    py -3.12 run_bot.py
)
pause
