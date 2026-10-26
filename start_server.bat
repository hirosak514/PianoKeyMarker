@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 goto trypy
python serve.py
goto end
:trypy
where py >nul 2>nul
if errorlevel 1 goto nopython
py serve.py
goto end
:nopython
echo Python was not found. Please install Python from https://www.python.org/
echo During installation, check "Add python.exe to PATH".
:end
pause
