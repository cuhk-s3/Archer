#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
source scripts/upenv.sh
export ARCHER_HOST="${ARCHER_HOST:-0.0.0.0}"
export ARCHER_PORT="${ARCHER_PORT:-8080}"
npm run build
exec node dist/cli.js serve
