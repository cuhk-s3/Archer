#!/bin/bash

cd "$(dirname "$0")/../../subsystem" || exit

for file in ../dataset/issues/*.json; do
  if [ -f "$file" ]; then
    issue=$(basename "$file" .json)
    python3 collect.py --issue "$issue" --model google/gemini-3.1-pro-preview
  fi
done
