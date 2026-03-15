#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
SUBSYSTEM_DIR="$ROOT_DIR/subsystem"
PASSES_DIR="$ROOT_DIR/experiment/1-pass-knowledge/summary/passes-non-regression"
SUMMARY_OUT_DIR="$ROOT_DIR/experiment/1-pass-knowledge/summary/non-regression"
SUMMARY_LOG_DIR="$ROOT_DIR/experiment/1-pass-knowledge/summary/log-non-regression"

mkdir -p "$SUMMARY_OUT_DIR" "$SUMMARY_LOG_DIR"

cd "$SUBSYSTEM_DIR"

for file in "$PASSES_DIR"/*.md; do
  if [ -f "$file" ]; then
    component=$(basename "$file" .md)
    python3 summary.py \
      --component "$component" \
      --model google/gemini-3.1-pro-preview \
      --passes-dir "$PASSES_DIR" \
      --output-dir "$SUMMARY_OUT_DIR" \
      --log-dir "$SUMMARY_LOG_DIR"
  fi
done
