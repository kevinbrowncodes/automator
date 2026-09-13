#!/bin/bash

INPUT="$1"
EXT="${INPUT##*.}"
EXT_LOWER=$(echo "$EXT" | tr '[:upper:]' '[:lower:]')
BASENAME=$(basename "$INPUT" ."$EXT")
OUTDIR=$(dirname "$INPUT")
TMPWAV="/tmp/${BASENAME}_input.wav"

export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1

source /Users/kevinbrown/venvs/audiosr/bin/activate

ffmpeg -y -i "$INPUT" -vn -ar 16000 -ac 1 "$TMPWAV"

audioldm \
  --mode transfer \
  --file_path "$TMPWAV" \
  --text "high quality audio" \
  --transfer_strength 0.15 \
  --model_name audioldm-m-full \
  --save_path /tmp/audioldm_out \
  --seed 42

REGENWAV=$(find /tmp/audioldm_out -name "*.wav" | head -1)

ffmpeg -y -i "$REGENWAV" -codec:a libmp3lame -q:a 2 "${OUTDIR}/${BASENAME}_regen.mp3"

rm -f "$TMPWAV"
rm -rf /tmp/audioldm_out
