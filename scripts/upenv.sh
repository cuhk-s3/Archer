#!/usr/bin/env bash

# Source this file in every new shell: `source scripts/upenv.sh`.
if [[ "${BASH_SOURCE[0]:-$0}" == "$0" && -z "${ZSH_EVAL_CONTEXT:-}" ]]; then
  echo "Error: scripts/upenv.sh must be sourced, not executed." >&2
  exit 1
fi

if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  _ARCHER_UPENV_FILE="${BASH_SOURCE[0]}"
elif [[ -n "${ZSH_VERSION:-}" ]]; then
  _ARCHER_UPENV_FILE="${(%):-%N}"
else
  echo "Error: unsupported shell; use bash or zsh." >&2
  return 1
fi
_ARCHER_SCRIPT_DIR=$(cd -P "$(dirname "${_ARCHER_UPENV_FILE}")" && pwd)

export ARCHER_HOME_DIR="${ARCHER_HOME_DIR:-$(cd -P "${_ARCHER_SCRIPT_DIR}/.." && pwd)}"
export ARCHER_DEPS_DIR="${ARCHER_DEPS_DIR:-${ARCHER_HOME_DIR}/deps}"
export ARCHER_BUILD_DIR="${ARCHER_BUILD_DIR:-${ARCHER_HOME_DIR}/builds}"
export ARCHER_VENV_DIR="${ARCHER_VENV_DIR:-${ARCHER_HOME_DIR}/.venv}"
export ARCHER_ELAN_HOME="${ARCHER_ELAN_HOME:-${ARCHER_DEPS_DIR}/elan}"
export ARCHER_REVIEWER_TOOLS_DIR="${ARCHER_REVIEWER_TOOLS_DIR:-${ARCHER_BUILD_DIR}/reviewer-tools}"
export LAB_VEIR_DIR="${LAB_VEIR_DIR:-${ARCHER_DEPS_DIR}/veir}"
export LAB_DATASET_DIR="${LAB_DATASET_DIR:-${ARCHER_HOME_DIR}/dataset}"
if [[ -f "${ARCHER_HOME_DIR}/environments" ]]; then
  # shellcheck disable=SC1091
  source "${ARCHER_HOME_DIR}/environments" || return 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv is required to initialize ${ARCHER_VENV_DIR}." >&2
  return 1
fi
if [[ ! -x "${ARCHER_VENV_DIR}/bin/python" ]]; then
  echo "Creating Python environment at ${ARCHER_VENV_DIR}"
  UV_CACHE_DIR="${TMPDIR:-/tmp}/archer-veir-uv-cache" \
    uv venv "${ARCHER_VENV_DIR}" || return 1
fi

_ARCHER_REQ_HASH=$(sha256sum "${ARCHER_HOME_DIR}/requirements.txt" | cut -d' ' -f1)
_ARCHER_REQ_STAMP="${ARCHER_VENV_DIR}/.archer-requirements.sha256"
if [[ ! -f "${_ARCHER_REQ_STAMP}" ]] || \
   [[ "$(tr -d '[:space:]' < "${_ARCHER_REQ_STAMP}")" != "${_ARCHER_REQ_HASH}" ]]; then
  echo "Updating Python dependencies in ${ARCHER_VENV_DIR}"
  UV_CACHE_DIR="${TMPDIR:-/tmp}/archer-veir-uv-cache" \
    uv pip install --python "${ARCHER_VENV_DIR}/bin/python" \
      -r "${ARCHER_HOME_DIR}/requirements.txt" || return 1
  printf '%s\n' "${_ARCHER_REQ_HASH}" > "${_ARCHER_REQ_STAMP}"
fi

# shellcheck disable=SC1091
source "${ARCHER_VENV_DIR}/bin/activate" || return 1
export ELAN_HOME="${ARCHER_ELAN_HOME}"
if [[ -f "${LAB_VEIR_DIR}/lean-toolchain" ]]; then
  export ELAN_TOOLCHAIN="$(tr -d '[:space:]' < "${LAB_VEIR_DIR}/lean-toolchain")"
  _ARCHER_ELAN_BIN="${ARCHER_ELAN_BIN:-$(command -v elan || true)}"
  if [[ -n "${_ARCHER_ELAN_BIN}" ]]; then
    export LAB_VEIR_LAKE="$("${_ARCHER_ELAN_BIN}" which lake 2>/dev/null || true)"
  fi
fi

if [[ -f "${ARCHER_REVIEWER_TOOLS_DIR}/environment.sh" ]]; then
  # shellcheck disable=SC1091
  source "${ARCHER_REVIEWER_TOOLS_DIR}/environment.sh" || return 1
else
  echo "Note: reviewer tools are not built; run scripts/setup.sh when needed."
fi

export PYTHONPATH="${ARCHER_HOME_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
unset _ARCHER_UPENV_FILE _ARCHER_SCRIPT_DIR _ARCHER_REQ_HASH _ARCHER_REQ_STAMP _ARCHER_ELAN_BIN
echo "Archer environment ready: ${ARCHER_HOME_DIR}"
