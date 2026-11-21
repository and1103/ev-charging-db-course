@echo off
setlocal
chcp 65001 >nul
set "V2_APP_DIR="
for /d %%D in ("%~dp001_*") do if exist "%%~fD\project_paths.py" set "V2_APP_DIR=%%~fD"
if not defined V2_APP_DIR goto failed
if exist "%V2_APP_DIR%\.venv\Scripts\python.exe" goto dependencies
py -3 -m venv "%V2_APP_DIR%\.venv"
if errorlevel 1 goto failed
:dependencies
"%V2_APP_DIR%\.venv\Scripts\python.exe" -m pip install -r "%V2_APP_DIR%\requirements-lock.txt"
if errorlevel 1 goto failed
echo Environment ready.
pause
exit /b 0
:failed
echo Environment installation failed. Python 3.12 and a complete project are required.
pause
exit /b 1
