@echo off
setlocal
cd /d "%~dp0"

if not exist "frontend\dist\index.html" (
  echo Frontend build not found. Building frontend...
  where npm >nul 2>nul
  if errorlevel 1 (
    echo npm was not found. Install Node.js, then run: cd frontend ^&^& npm install
    pause
    exit /b 1
  )
  pushd frontend
  call npm run build
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
)

uv run python scripts\run_app.py --open
if errorlevel 1 pause
