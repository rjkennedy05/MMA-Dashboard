@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    python -m pip install -r requirements.txt
    if errorlevel 1 goto failed
    python install_sources.py
) else (
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 goto failed
    py -3 install_sources.py
)
if errorlevel 1 goto failed
echo Command and source packages installed. Run 05 once, then 06.
pause
exit /b 0
:failed
echo Installation stopped. Read the error above before closing this window.
pause
exit /b 1
