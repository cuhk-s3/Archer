#!/usr/bin/env bash

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

export ARCHER_ACTIONS_REPO="${ARCHER_ACTIONS_REPO:-cuhk-s3/Archer}"
export ARCHER_ACTIONS_WORKFLOW="${ARCHER_ACTIONS_WORKFLOW:-archer-review-dispatch.yml}"
export ARCHER_ACTIONS_REF="${ARCHER_ACTIONS_REF:-main}"
export ARCHER_ACTIONS_POLL_INTERVAL_SEC="${ARCHER_ACTIONS_POLL_INTERVAL_SEC:-20}"
export ARCHER_MODEL="${ARCHER_MODEL:-packyai-gpt-5.6-sol}"
export ARCHER_DRIVER="${ARCHER_DRIVER:-openai-responses}"

export FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
export FRONTEND_PORT="${FRONTEND_PORT:-8090}"

# Set domain (default to archer.top)
export ARCHER_DOMAIN="${ARCHER_DOMAIN:-archer.top}"

# Auto-configure domain-based variables
if [[ -n "${ARCHER_DOMAIN}" ]]; then
  # Use domain with Nginx reverse proxy
  export BACKEND_BASE_URL="https://${ARCHER_DOMAIN}"
  export ARCHER_CORS_ORIGINS="https://${ARCHER_DOMAIN}"
  echo "Domain config: ${ARCHER_DOMAIN}"
else
  # Local development mode
  export BACKEND_BASE_URL="http://127.0.0.1:${ARCHER_SERVICE_PORT}"
  export ARCHER_CORS_ORIGINS="*"
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required to serve dispatcher frontend static files." >&2
  exit 1
fi

cat > "${FRONTEND_DIR}/runtime-config.js" <<EOF
window.ARCHER_BACKEND_BASE_URL = "${BACKEND_BASE_URL}";
EOF

LOGO_SOURCE="${ROOT_DIR}/service/Archer.png"
LOGO_TARGET="${FRONTEND_DIR}/logo.png"
if [[ -f "${LOGO_SOURCE}" ]]; then
  ln -sfn "../Archer.png" "${LOGO_TARGET}" || cp "${LOGO_SOURCE}" "${LOGO_TARGET}"
fi

echo "Frontend runtime config written: ${FRONTEND_DIR}/runtime-config.js"
echo "Dispatcher model=${ARCHER_MODEL}, driver=${ARCHER_DRIVER}, ref=${ARCHER_ACTIONS_REF}, auto_scan=${ARCHER_AUTO_SCAN}"

echo "Starting dispatcher backend on ${ARCHER_SERVICE_HOST}:${ARCHER_SERVICE_PORT}"
if [[ -x "${ROOT_DIR}/deps/py3_venv/bin/python" ]]; then
  BACKEND_PYTHON="${ROOT_DIR}/deps/py3_venv/bin/python"
else
  BACKEND_PYTHON="${PYTHON_BIN:-python3}"
fi

"${BACKEND_PYTHON}" -m uvicorn service.backend.app:app \
  --host "${ARCHER_SERVICE_HOST}" \
  --port "${ARCHER_SERVICE_PORT}" &
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
