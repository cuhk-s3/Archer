#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/service/frontend"

cd "${ROOT_DIR}"

if [[ -z "${ARCHER_GITHUB_TOKEN:-}" && -z "${LAB_GITHUB_TOKEN:-}" ]]; then
  echo "Error: set ARCHER_GITHUB_TOKEN (or LAB_GITHUB_TOKEN) before starting dispatcher." >&2
  exit 1
fi

export ARCHER_EXECUTOR="${ARCHER_EXECUTOR:-github-actions}"
export ARCHER_SERVICE_HOST="${ARCHER_SERVICE_HOST:-0.0.0.0}"
export ARCHER_SERVICE_PORT="${ARCHER_SERVICE_PORT:-8080}"
export ARCHER_CORS_ORIGINS="${ARCHER_CORS_ORIGINS:-*}"

export ARCHER_ACTIONS_REPO="${ARCHER_ACTIONS_REPO:-cuhk-s3/Archer}"
export ARCHER_ACTIONS_WORKFLOW="${ARCHER_ACTIONS_WORKFLOW:-archer-review-dispatch.yml}"
export ARCHER_ACTIONS_REF="${ARCHER_ACTIONS_REF:-main}"
export ARCHER_ACTIONS_POLL_INTERVAL_SEC="${ARCHER_ACTIONS_POLL_INTERVAL_SEC:-20}"

export FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
export FRONTEND_PORT="${FRONTEND_PORT:-8090}"
export BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://127.0.0.1:${ARCHER_SERVICE_PORT}}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required to serve dispatcher frontend static files." >&2
  exit 1
fi

cat > "${FRONTEND_DIR}/runtime-config.js" <<EOF
window.ARCHER_BACKEND_BASE_URL = "${BACKEND_BASE_URL}";
EOF

echo "Frontend runtime config written: ${FRONTEND_DIR}/runtime-config.js"

echo "Starting dispatcher backend on ${ARCHER_SERVICE_HOST}:${ARCHER_SERVICE_PORT}"
bash "${ROOT_DIR}/scripts/run_service.sh" &
BACKEND_PID=$!

cleanup() {
  if kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" || true
    wait "${BACKEND_PID}" || true
  fi
}

trap cleanup EXIT INT TERM

echo "Starting dispatcher frontend on ${FRONTEND_HOST}:${FRONTEND_PORT}"
exec python3 -m http.server "${FRONTEND_PORT}" --bind "${FRONTEND_HOST}" --directory "${FRONTEND_DIR}"
