@echo off
setlocal
cd /d "%~dp0\..\.."
set "AGENT_CONFIG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%AGENT_CONFIG_PYTHON%" set "AGENT_CONFIG_PYTHON=python"
"%AGENT_CONFIG_PYTHON%" -X utf8 deployments\agentarts\configure_model.py
pause
