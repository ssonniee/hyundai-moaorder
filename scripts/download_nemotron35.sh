#!/usr/bin/env bash
set -euo pipefail

NEMO_SPEECH_ROOT="${NEMO_SPEECH_ROOT:-/home/yubin/workspace/Hyundai/nemo-speech}"
HF_BIN="${NEMOTRON35_HF_BIN:-$NEMO_SPEECH_ROOT/.venv/bin/hf}"
MODEL_DIR="${NEMOTRON35_MODEL_DIR:-$NEMO_SPEECH_ROOT/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-NVFP4}"

if [[ ! -x "$HF_BIN" ]]; then
  echo "Hugging Face CLI not found: $HF_BIN" >&2
  exit 1
fi

exec "$HF_BIN" download nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-NVFP4 \
  --local-dir "$MODEL_DIR"
