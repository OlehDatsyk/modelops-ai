@echo off
setlocal EnableExtensions EnableDelayedExpansion
title ModelOps AI - local launcher
cd /d "%~dp0"

echo.
echo  =============================================
echo    ModelOps AI - local development launcher
echo  =============================================
echo.

rem ---------------------------------------------------------------- Python
set "PY="
where py >nul 2>&1 && (py -3.12 --version >nul 2>&1 && set "PY=py -3.12")
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python 3.12+ was not found. Install it from https://www.python.org/downloads/
  goto :fail
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" || (
  echo [ERROR] Python 3.12 or newer is required ^(found !PYVER!^).
  goto :fail
)
echo [OK] Python !PYVER!

rem ---------------------------------------------------------------- Node.js
where node >nul 2>&1 || (
  echo [ERROR] Node.js 20+ was not found. Install it from https://nodejs.org/
  goto :fail
)
for /f %%v in ('node --version') do set "NODEVER=%%v"
echo [OK] Node.js !NODEVER!

rem ---------------------------------------------------------------- .env
if not exist ".env" (
  echo [INFO] No .env file found - creating one from .env.example with freshly generated secrets.
  %PY% -c "import secrets,re,pathlib; t=pathlib.Path('.env.example').read_text(encoding='utf-8'); t=re.sub(r'(?m)^JWT_SECRET_KEY=.*$', 'JWT_SECRET_KEY='+secrets.token_urlsafe(48), t); t=re.sub(r'(?m)^MASTER_ENCRYPTION_KEY=.*$', 'MASTER_ENCRYPTION_KEY='+secrets.token_urlsafe(48), t); pathlib.Path('.env').write_text(t, encoding='utf-8')" || goto :fail
  echo [OK] .env created. Keep it private and back up MASTER_ENCRYPTION_KEY.
) else (
  echo [OK] Using existing .env ^(not modified^)
)

rem ---------------------------------------------------------------- Backend venv
if not exist "backend\.venv\Scripts\python.exe" (
  echo [INFO] Creating backend virtual environment...
  %PY% -m venv backend\.venv || goto :fail
)
set "VPY=%~dp0backend\.venv\Scripts\python.exe"
echo [INFO] Installing/updating backend dependencies...
"%VPY%" -m pip install -q --disable-pip-version-check -r backend\requirements.txt || goto :fail
echo [OK] Backend dependencies ready

rem ---------------------------------------------------------------- Frontend deps
if not exist "frontend\node_modules" (
  echo [INFO] Installing frontend dependencies ^(first run only^)...
  pushd frontend
  call npm install --no-audit --no-fund || (popd & goto :fail)
  popd
)
echo [OK] Frontend dependencies ready

rem ---------------------------------------------------------------- Database
pushd backend
"%VPY%" -m app.cli check >nul 2>&1
if not errorlevel 1 goto :dbready
where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Cannot connect to PostgreSQL using DATABASE_URL in .env, and Docker is not installed.
  echo         Start a PostgreSQL 16 server and update DATABASE_URL, then run this script again.
  popd
  goto :fail
)
echo [INFO] Database not reachable - starting PostgreSQL with Docker Compose...
docker compose -f ..\docker-compose.yml up -d db
if errorlevel 1 (
  echo [ERROR] docker compose failed. Is Docker Desktop running?
  popd
  goto :fail
)
set /a tries=0
:waitdb
set /a tries+=1
timeout /t 2 /nobreak >nul
"%VPY%" -m app.cli check >nul 2>&1
if not errorlevel 1 goto :dbready
if !tries! lss 30 goto :waitdb
echo [ERROR] PostgreSQL did not become ready. Check "docker compose logs db".
popd
goto :fail
:dbready
echo [OK] Database reachable
echo [INFO] Applying migrations...
"%VPY%" -m alembic upgrade head || (popd & goto :fail)
"%VPY%" -m app.cli seed-pricing || (popd & goto :fail)
popd

rem ---------------------------------------------------------------- Start
echo.
echo [INFO] Starting backend  on http://localhost:8000  (API docs: http://localhost:8000/api/docs)
start "ModelOps AI - backend" cmd /k ""%VPY%" -m uvicorn --app-dir backend app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend\app"
echo [INFO] Starting frontend on http://localhost:5173
start "ModelOps AI - frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"
timeout /t 5 /nobreak >nul
start "" http://localhost:5173
echo.
echo ModelOps AI is starting in two new windows. Close those windows to stop it.
echo.
pause
exit /b 0

:fail
echo.
echo Startup failed. See the messages above.
pause
exit /b 1
