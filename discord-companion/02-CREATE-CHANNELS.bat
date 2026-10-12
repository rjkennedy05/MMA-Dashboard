@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python setup_discord.py --apply
) else (
    py -3 setup_discord.py --apply
)
pause
