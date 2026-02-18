#!/bin/bash
set -e

INPUT_FILE="${INPUT_FILE:-/input/input.txt}"
OUTPUT_FILE="${OUTPUT_FILE:-/output/output.wav}"

# Google auth: set this to where your service account json is mounted
GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-/secrets/gcp.json}"

if [ ! -f "$INPUT_FILE" ]; then
  echo "Error: Input file not found at $INPUT_FILE"
  exit 1
fi

if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
  echo "Error: GCP credentials not found at $GOOGLE_APPLICATION_CREDENTIALS"
  echo "Mount your service account json and set GOOGLE_APPLICATION_CREDENTIALS."
  exit 1
fi

export GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_APPLICATION_CREDENTIALS"

echo "Converting: $INPUT_FILE -> $OUTPUT_FILE"
python /app/tts_google.py
