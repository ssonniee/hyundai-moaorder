#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${DRIVE_ORDER_PYTHON:-/home/ssonniee/anaconda3/envs/nemo/bin/python}"
export PYTHONPATH="$(pwd)/.deps:$(pwd)/../Nemotron-ASR/Speech${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m drive_order "$@"
