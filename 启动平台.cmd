@echo off
setlocal
chcp 65001 >nul
set "V2_APP_DIR="
for /d %%D in ("%~dp001_*") do if exist "%%~fD\project_paths.py" set "V2_APP_DIR=%%~fD"
if not defined V2_APP_DIR goto missing_app
if not exist "%V2_APP_DIR%\.venv\Scripts\python.exe" goto missing_python
cd /d "%~dp0"
"%V2_APP_DIR%\.venv\Scripts\python.exe" -X utf8 "%V2_APP_DIR%\web_launcher.py" %*
set "V2_EXIT=%ERRORLEVEL%"
if not "%V2_EXIT%"=="0" pause
exit /b %V2_EXIT%
:missing_app
echo Application folder is missing. Please use the complete second edition.
pause
exit /b 1
:missing_python
echo Python environment is missing. Please run the environment installer first.
pause
exit /b 1
