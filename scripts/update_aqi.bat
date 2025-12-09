@echo off
setlocal

cd /d "%~dp0"

set "LOG_FILE=aq_widget_log.txt"

:loop
echo [LOOP %date% %time%] >> "%LOG_FILE%"

python "%~dp0aq_widget.py" >> "%LOG_FILE%" 2>&1


set "RM_EXE=%ProgramFiles%\Rainmeter\Rainmeter.exe"
if not exist "%RM_EXE%" set "RM_EXE=%ProgramFiles(x86)%\Rainmeter\Rainmeter.exe"

if exist "%RM_EXE%" (
    "%RM_EXE%" !RefreshApp >> "%LOG_FILE%" 2>&1
) else (
    echo [WARN] Rainmeter.exe not found, skipping refresh >> "%LOG_FILE%"
)

timeout /t 300 /nobreak >nul

goto loop
