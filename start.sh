#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f "frontend/dist/index.html" ]; then
  echo "Frontend build not found. Building frontend..."
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm was not found. Install Node.js, then run: cd frontend && npm install"
    exit 1
  fi
  (cd frontend && npm run build)
fi

uv run python scripts/run_app.py --open
