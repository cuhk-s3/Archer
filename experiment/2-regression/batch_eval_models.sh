#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
EXPERIMENT="${EXPERIMENT:-archer}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

MODELS=(
  "deepseek-chat"
  "google/gemini-3.1-pro-preview-customtools"
  "qwen3.5-plus"
)

for model in "${MODELS[@]}"; do
  echo "Running ${EXPERIMENT} with model: ${model}"
  "$PYTHON_BIN" "$SCRIPT_DIR/eval.py" \
    --experiment "$EXPERIMENT" \
    --model "$model" \
    "$@"
done
