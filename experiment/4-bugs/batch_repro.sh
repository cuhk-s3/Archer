#!/bin/bash

MODEL="deepseek-chat"
MODEL_DIR="deepseek-chat"

mkdir -p autoreview-"$MODEL_DIR"/history

for file in dataset/*.json; do
  if [ -f "$file" ]; then
    issue=$(basename "$file" .json)
    python3 repro.py --issue "$issue" --model "$MODEL" --stats autoreview-"$MODEL_DIR"/"$issue".json --history autoreview-"$MODEL_DIR"/history/"$issue".json --debug
  fi
done
