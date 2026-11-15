#!/usr/bin/env bash
# ModelOps AI — local development launcher for macOS (also works on Linux).
# Double-click in Finder, or run: ./"Start App (Mac).command"
set -euo pipefail
cd "$(dirname "$0")"

info() { printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[ERROR]\033[0m %s\n' "$*"; read -r -p "Press Enter to close..." _ || true; exit 1; }

echo
echo "  ============================================="
echo "    ModelOps AI - local development launcher"
echo "  ============================================="
echo

# ---------------------------------------------------------------- Python
PY=""
for candidate in python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.12+ was not found. Install it from https://www.python.org/downloads/ (or: brew install python@3.12)"
ok "Python $("$PY" --version 2>&1 | cut -d' ' -f2)"

# ---------------------------------------------------------------- Node.js
command -v node >/dev/null 2>&1 || fail "Node.js 20+ was not found. Install it from https://nodejs.org/ (or: brew install node)"
ok "Node.js $(node --version)"

# ---------------------------------------------------------------- .env
if [ ! -f .env ]; then
  info "No .env file found - creating one from .env.example with freshly generated secrets."
  "$PY" - <<'PYCODE'
import pathlib, re, secrets
t = pathlib.Path('.env.example').read_text(encoding='utf-8')
t = re.sub(r'(?m)^JWT_SECRET_KEY=.*$', 'JWT_SECRET_KEY=' + secrets.token_urlsafe(48), t)
t = re.sub(r'(?m)^MASTER_ENCRYPTION_KEY=.*$', 'MASTER_ENCRYPTION_KEY=' + secrets.token_urlsafe(48), t)
pathlib.Path('.env').write_text(t, encoding='utf-8')
PYCODE
  chmod 600 .env
  ok ".env created. Keep it private and back up MASTER_ENCRYPTION_KEY."
else
  ok "Using existing .env (not modified)"
fi

# ---------------------------------------------------------------- Backend venv
if [ ! -x backend/.venv/bin/python ]; then
  info "Creating backend virtual environment..."
  "$PY" -m venv backend/.venv || fail "Could not create the virtual environment"
fi
VPY="$PWD/backend/.venv/bin/python"
info "Installing/updating backend dependencies..."
"$VPY" -m pip install -q --disable-pip-version-check -r backend/requirements.txt || fail "pip install failed"
ok "Backend dependencies ready"

# ---------------------------------------------------------------- Frontend deps
if [ ! -d frontend/node_modules ]; then
  info "Installing frontend dependencies (first run only)..."
  (cd frontend && npm install --no-audit --no-fund) || fail "npm install failed"
fi
ok "Frontend dependencies ready"

# ---------------------------------------------------------------- Database
cd backend
if ! "$VPY" -m app.cli check >/dev/null 2>&1; then
  command -v docker >/dev/null 2>&1 || fail "Cannot connect to PostgreSQL (DATABASE_URL in .env) and Docker is not installed. Start PostgreSQL 16 and try again."
  info "Database not reachable - starting PostgreSQL with Docker Compose..."
  docker compose -f ../docker-compose.yml up -d db || fail "docker compose failed (is Docker Desktop running?)"
  for _ in $(seq 1 30); do
    sleep 2
    "$VPY" -m app.cli check >/dev/null 2>&1 && break
  done
  "$VPY" -m app.cli check >/dev/null 2>&1 || fail "PostgreSQL did not become ready. Check: docker compose logs db"
fi
ok "Database reachable"
info "Applying migrations..."
"$VPY" -m alembic upgrade head || fail "Migrations failed"
"$VPY" -m app.cli seed-pricing
cd ..

# ---------------------------------------------------------------- Start
cleanup() { info "Stopping..."; kill "${BACK_PID:-}" "${FRONT_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

info "Starting backend  on http://localhost:8000  (API docs: http://localhost:8000/api/docs)"
"$VPY" -m uvicorn --app-dir backend app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend/app &
BACK_PID=$!
info "Starting frontend on http://localhost:5173"
(cd frontend && npm run dev) &
FRONT_PID=$!

sleep 5
if command -v open >/dev/null 2>&1; then open http://localhost:5173; elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:5173; fi
echo
ok "ModelOps AI is running. Press Ctrl+C (or close this window) to stop."
wait
