#!/bin/bash

cd "$(dirname "$0")/../../subsystem" || exit

for file in passes/*.md; do
  if [ -f "$file" ]; then
    component=$(basename "$file" .md)
    python3 summary.py --component "$component" --model google/gemini-3.1-pro-preview
  fi
done
