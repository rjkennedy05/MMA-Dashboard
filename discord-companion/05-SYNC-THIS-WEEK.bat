@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python sync_discord.py
) else (
    py -3.12 sync_discord.py
)
pause
