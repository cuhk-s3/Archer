#!/bin/bash

MODEL="deepseek-chat"
MODEL_DIR="deepseek-chat"

mkdir -p mswe-"$MODEL_DIR"/history

for file in dataset/*.json; do
  if [ -f "$file" ]; then
    issue=$(basename "$file" .json)
    python3 mswe.py --issue "$issue" --model "$MODEL" --stats mswe-"$MODEL_DIR"/"$issue".json --history mswe-"$MODEL_DIR"/history/"$issue".json --debug
  fi
done
