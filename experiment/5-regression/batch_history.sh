#!/bin/bash

for file in mis/*.json; do
  if [ -f "$file" ]; then
    issue=$(basename "$file" .json)
    python3 extract_history.py --issue "$issue"
  fi
done
