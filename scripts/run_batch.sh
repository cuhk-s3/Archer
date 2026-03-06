#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPLIT="${1:-}"

if [[ "${SPLIT}" != "open" && "${SPLIT}" != "closed" ]]; then
  echo "Usage: $(basename "$0") <open|closed>"
  exit 1
fi

DATASET_DIR="${ROOT_DIR}/dataset/${SPLIT}"
json_files=("${DATASET_DIR}"/*.json)

for json_file in "${json_files[@]}"; do
  pr_id="$(basename "${json_file}" .json)"

  echo "[RUN][${SPLIT}] PR #${pr_id}"
  python3 "${ROOT_DIR}/main.py" \
    --pr "${pr_id}" \
    --model google/gemini-3.1-pro-preview-customtools \
    --stats "${ROOT_DIR}/record/${SPLIT}/${pr_id}.json" \
    --history "${ROOT_DIR}/record/${SPLIT}/history/${pr_id}.json" \
    --review "${ROOT_DIR}/record/${SPLIT}/review/${pr_id}.md"
done
