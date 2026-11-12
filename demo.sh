#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${DRIVE_ORDER_PYTHON:-/home/ssonniee/anaconda3/envs/nemo/bin/python}"
exec "$PYTHON_BIN" -m drive_order.demo_server "$@"
