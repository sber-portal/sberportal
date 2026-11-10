@echo off
rem Windows: двойной клик или "run-windows.bat --ip 192.168.1.50"
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 portal_installer.py %*
) else (
  python portal_installer.py %*
)
pause
