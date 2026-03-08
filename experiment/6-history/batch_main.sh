#!/bin/bash

cd "$(dirname "$0")/../.." || exit

MODEL="deepseek-chat"
MODEL_DIR="deepseek-chat"

mkdir -p experiment/6-history/autoreview-"$MODEL_DIR"/history

for file in dataset/*.json; do
  if [ -f "$file" ]; then
    issue=$(basename "$file" .json)
    python3 main.py --issue "$issue" --model deepseek-chat --stats experiment/6-history/autoreview-"$MODEL_DIR"/"$issue".json --history experiment/6-history/autoreview-"$MODEL_DIR"/history/"$issue".json --debug
  fi
done
