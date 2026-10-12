@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python -m pip install --require-hashes -r requirements.txt
    if not errorlevel 1 python connect_dashboard.py
) else (
    py -3.12 -m pip install --require-hashes -r requirements.txt
    if not errorlevel 1 py -3.12 connect_dashboard.py
)
pause
