@echo off
setlocal
set "WORKBENCH_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%WORKBENCH_PYTHON%" (
  "%WORKBENCH_PYTHON%" -X utf8 "%~dp0tools\start_workbench.py"
) else (
  py -3 -X utf8 "%~dp0tools\start_workbench.py"
)
if errorlevel 1 pause
endlocal
