#!/usr/bin/env bash
set -euo pipefail

NEMO_SPEECH_ROOT="${NEMO_SPEECH_ROOT:-/home/yubin/workspace/Hyundai/nemo-speech}"
MODEL_DIR="${NEMOTRON35_MODEL_DIR:-$NEMO_SPEECH_ROOT/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-NVFP4}"
VLLM_BIN="${NEMOTRON35_VLLM_BIN:-$NEMO_SPEECH_ROOT/.venv/bin/vllm}"
CUDA_HOME="${NEMOTRON35_CUDA_HOME:-$NEMO_SPEECH_ROOT/.venv/lib/python3.12/site-packages/nvidia/cu13}"

if [[ ! -f "$MODEL_DIR/config.json" ]]; then
  echo "Model not found: $MODEL_DIR" >&2
  echo 'Run scripts/download_nemotron35.sh first.' >&2
  exit 1
fi
if [[ ! -x "$VLLM_BIN" ]]; then
  echo "vLLM executable not found: $VLLM_BIN" >&2
  exit 1
fi
if ! "$NEMO_SPEECH_ROOT/.venv/bin/python" -c \
  "import importlib.metadata as m; m.version('flashinfer-cubin'); m.version('flashinfer-jit-cache')"; then
  echo 'Prebuilt FlashInfer kernels are missing. Run: vllm download-kernels' >&2
  exit 1
fi
if [[ ! -x "$CUDA_HOME/bin/nvcc" ]]; then
  echo "CUDA compiler not found: $CUDA_HOME/bin/nvcc" >&2
  echo 'Install CUDA 13.0 nvcc, crt, and nvvm packages in the NeMo virtual environment.' >&2
  exit 1
fi
if ! "$CUDA_HOME/bin/nvcc" --version | grep -q 'release 13\.0'; then
  echo "Nemotron requires the JIT compiler to match PyTorch CUDA 13.0: $CUDA_HOME/bin/nvcc" >&2
  "$CUDA_HOME/bin/nvcc" --version >&2
  exit 1
fi

export VLLM_PLUGINS=nemo_speechlm
export CUDA_HOME
export PATH="$NEMO_SPEECH_ROOT/.venv/bin:$CUDA_HOME/bin:$PATH"
export VLLM_MAX_AUDIO_DECODE_DURATION_S=120
export VLLM_MAX_AUDIO_CLIP_FILESIZE_MB=64
export VLLM_USE_V2_MODEL_RUNNER=0
export VLLM_DISABLED_KERNELS=FlashInferFP8ScaledMMLinearKernel

exec "$VLLM_BIN" serve "$MODEL_DIR" \
  --host 127.0.0.1 --port 8000 \
  --served-model-name nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B-NVFP4 \
  --trust-remote-code --dtype bfloat16 --kv-cache-dtype fp8 \
  --gpu-memory-utilization 0.94 \
  --max-model-len 8192 --max-num-batched-tokens 4096 --max-num-seqs 1 \
  --enable-chunked-prefill --no-enable-prefix-caching \
  --use-replayssm --mamba-backend flashinfer --mamba-cache-mode none \
  --mm-processor-cache-gb 0 --no-async-scheduling \
  --limit-mm-per-prompt '{"audio":{"count":1,"length":1920000}}' \
  --reasoning-parser nemotron_v3 \
  --trust-request-mm-kwargs \
  --middleware nemo.collections.speechlm2.vllm.salm.ctc_serving.ctc_timestamp_middleware
