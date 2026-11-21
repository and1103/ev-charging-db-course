@echo off
setlocal
chcp 65001 >nul
set "V2_APP_DIR="
set "V2_TEST_DIR="
for /d %%D in ("%~dp001_*") do if exist "%%~fD\project_paths.py" set "V2_APP_DIR=%%~fD"
for /d %%D in ("%~dp004_*") do if exist "%%~fD\run_checks.py" set "V2_TEST_DIR=%%~fD"
if not defined V2_APP_DIR goto failed
if not defined V2_TEST_DIR goto failed
if not exist "%V2_APP_DIR%\.venv\Scripts\python.exe" goto failed
cd /d "%~dp0"
"%V2_APP_DIR%\.venv\Scripts\python.exe" -X utf8 "%V2_TEST_DIR%\run_checks.py" %*
set "V2_EXIT=%ERRORLEVEL%"
if /i "%V2_NO_PAUSE%"=="1" exit /b %V2_EXIT%
pause
exit /b %V2_EXIT%
:failed
echo Validation environment or entry is missing. Run the installer first.
if /i "%V2_NO_PAUSE%"=="1" exit /b 1
pause
exit /b 1
