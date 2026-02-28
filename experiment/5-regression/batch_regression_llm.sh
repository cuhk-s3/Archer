#!/bin/bash

MODEL="deepseek-chat"
MODEL_DIR="deepseek-chat"

mkdir -p llm-"$MODEL_DIR"/history

for file in dataset/*.json; do
  if [ -f "$file" ]; then
    issue=$(basename "$file" .json)
    python3 llm.py --issue "$issue" --model "$MODEL" --stats llm-"$MODEL_DIR"/"$issue".json --history llm-"$MODEL_DIR"/history/"$issue".json --debug
  fi
done
