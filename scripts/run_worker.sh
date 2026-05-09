#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_DIR="${ACTIONS_RUNNER_DIR:-${ROOT_DIR}/actions-runner}"

if [[ ! -d "${RUNNER_DIR}" ]]; then
  echo "Error: ACTIONS_RUNNER_DIR does not exist: ${RUNNER_DIR}" >&2
  echo "Set ACTIONS_RUNNER_DIR to your GitHub self-hosted runner directory." >&2
  exit 1
fi

if [[ ! -x "${RUNNER_DIR}/run.sh" ]]; then
  echo "Error: runner executable not found: ${RUNNER_DIR}/run.sh" >&2
  exit 1
fi

echo "Starting worker runner from: ${RUNNER_DIR}"
cd "${RUNNER_DIR}"
exec ./run.sh
