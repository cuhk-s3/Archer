#!/bin/bash

MODEL="google/gemini-3.1-pro-preview-customtools"
MODEL_DIR="gemini-3.1-pro-preview-customtools"

mkdir -p archer-"$MODEL_DIR"/history
mkdir -p archer-"$MODEL_DIR"/review

for file in dataset/*.json; do
  if [ -f "$file" ]; then
    issue=$(basename "$file" .json)
    python3 regression.py --issue "$issue" --model "$MODEL" --stats archer-"$MODEL_DIR"/"$issue".json --history archer-"$MODEL_DIR"/history/"$issue".json --review archer-"$MODEL_DIR"/review/"$issue".md --debug
  fi
done
