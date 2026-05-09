#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${ROOT_DIR}/deps/py3_venv/bin/python"

cd "${ROOT_DIR}"

export LLVM_AUTOREVIEW_DEPS_DIR=$PWD/deps

if [[ -f "${ROOT_DIR}/scripts/upenv.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/scripts/upenv.sh"
fi

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Error: missing virtualenv python at ${VENV_PYTHON}" >&2
  exit 1
fi

export ARCHER_MODEL="${ARCHER_MODEL:-packyai-gpt-5.5}"
export ARCHER_DRIVER="${ARCHER_DRIVER:-openai}"
export ARCHER_SCAN_INTERVAL_SEC="${ARCHER_SCAN_INTERVAL_SEC:-300}"
export ARCHER_AUTO_SCAN="${ARCHER_AUTO_SCAN:-true}"
export ARCHER_OPEN_PR_LIMIT="${ARCHER_OPEN_PR_LIMIT:-20}"
export ARCHER_SERVICE_RELOAD="${ARCHER_SERVICE_RELOAD:-false}"

if [[ "${ARCHER_SERVICE_RELOAD}" == "true" ]]; then
  exec "${VENV_PYTHON}" -m uvicorn service.app:app --host "${ARCHER_SERVICE_HOST:-0.0.0.0}" --port "${ARCHER_SERVICE_PORT:-8080}" --reload
fi

exec "${VENV_PYTHON}" -m uvicorn service.app:app --host "${ARCHER_SERVICE_HOST:-0.0.0.0}" --port "${ARCHER_SERVICE_PORT:-8080}"
