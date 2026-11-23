@echo off
setlocal
rem Replay one failing case; no curl required.
cd /d "%~dp0..\.."
if "%DASHSCOPE_API_KEY%"=="" (
  echo Please export DASHSCOPE_API_KEY first.
  exit /b 1
)
if "%DASHSCOPE_WORKSPACE_ID%"=="" (
  echo Please export DASHSCOPE_WORKSPACE_ID first.
  exit /b 1
)
python run_tests.py --replay "image_count_responses@251"
