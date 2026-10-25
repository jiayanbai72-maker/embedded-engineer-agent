@echo off
setlocal
cd /d "%~dp0\..\.."
set "AGENT_PREVIEW_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%AGENT_PREVIEW_PYTHON%" set "AGENT_PREVIEW_PYTHON=python"
"%AGENT_PREVIEW_PYTHON%" -X utf8 deployments\agentarts\start_preview.py
if errorlevel 1 pause
