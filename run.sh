#!/usr/bin/env bash
# Build what is missing and start the Repo Analysis Tool on port 8000.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Backend virtualenv -------------------------------------------------------
if [ ! -x backend/.venv/bin/python ]; then
  echo "==> creating backend virtualenv"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi

# 2. Frontend build -----------------------------------------------------------
if [ ! -f frontend/dist/index.html ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "==> building frontend"
    (cd frontend && npm install --no-audit --no-fund && npm run build)
  else
    echo "!! npm not found - the backend will run without the web UI" >&2
  fi
fi

# 3. Serve --------------------------------------------------------------------
echo "==> starting server on http://127.0.0.1:8000"
cd backend
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 "$@"
