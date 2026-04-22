@echo off
setlocal
cd /d "%~dp0\.."
set "PYTHONPATH=%cd%\src"

if not exist "%cd%\.venv\Scripts\python.exe" (
  echo ERROR: No virtual environment at .venv\Scripts\python.exe
  echo Create one from the project root:  python -m venv .venv
  echo Then:  .venv\Scripts\pip install -e .[dev]
  exit /b 1
)

"%cd%\.venv\Scripts\python.exe" -m uvicorn psbt_tool.api.main:app --host 127.0.0.1 --port 8000 --reload %*

set EXITCODE=%ERRORLEVEL%
endlocal & exit /b %EXITCODE%
