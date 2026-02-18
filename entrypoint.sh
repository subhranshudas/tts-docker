#!/bin/bash
set -e

INPUT_FILE="${INPUT_FILE}"

# If INPUT_FILE not set, auto-detect first .txt file
if [ -z "$INPUT_FILE" ]; then
  INPUT_FILE=$(ls /input/*.txt 2>/dev/null | head -n 1)
fi

if [ -z "$INPUT_FILE" ]; then
  echo "Error: No .txt files found in /input"
  exit 1
fi

# Google auth
GOOGLE_APPLICATION_CREDENTIALS="${GOOGLE_APPLICATION_CREDENTIALS:-/secrets/gcp.json}"

# Auto-generate output filename
base="$(basename "$INPUT_FILE")"
name="${base%.*}"

enc="${AUDIO_ENCODING:-LINEAR16}"
enc_upper="$(echo "$enc" | tr '[:lower:]' '[:upper:]')"

if [ "$enc_upper" = "MP3" ]; then
  OUTPUT_FILE="/output/${name}.mp3"
elif [ "$enc_upper" = "OGG_OPUS" ]; then
  OUTPUT_FILE="/output/${name}.ogg"
else
  OUTPUT_FILE="/output/${name}.wav"
fi

if [ ! -f "$INPUT_FILE" ]; then
  echo "Error: Input file not found at $INPUT_FILE"
  exit 1
fi

export GOOGLE_APPLICATION_CREDENTIALS
export INPUT_FILE
export OUTPUT_FILE

echo "Converting: $INPUT_FILE -> $OUTPUT_FILE"

python /app/tts_google.py
