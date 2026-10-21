#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PYTHON="$SCRIPT_DIR/../.venv-airllm/bin/python"

export GREMLIN_MODEL="${GREMLIN_MODEL:-Qwen/Qwen2.5-3B-Instruct}"
export AIRLLM_MODEL_DIR="${AIRLLM_MODEL_DIR:-$HOME/.cache/airgremlin/models}"
export GREMLIN_WORKSPACE="${GREMLIN_WORKSPACE:-$SCRIPT_DIR}"
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"

if [[ ! -x "$PYTHON" ]]; then
    echo "AirLLM Python environment not found: $PYTHON" >&2
    exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/gremlin.py" "$@"
