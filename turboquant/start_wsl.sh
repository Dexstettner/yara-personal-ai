#!/bin/bash
# start_wsl.sh — Inicia turboquant-server no WSL2
# Uso: bash turboquant/start_wsl.sh
#
# O servidor fica acessível em http://localhost:8000 a partir do Windows.
# (WSL2 faz bridge automático de portas para o host Windows)

MODEL="${TURBOQUANT_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}"
BITS="${TURBOQUANT_BITS:-4}"
PORT="${TURBOQUANT_PORT:-8000}"

eval "$(conda shell.bash hook)" 2>/dev/null || \
    eval "$($HOME/miniconda3/bin/conda shell.bash hook)"

conda activate turboquant

echo "Iniciando turboquant-server..."
echo "  Modelo : $MODEL"
echo "  Bits   : $BITS-bit KV cache"
echo "  Porta  : $PORT"
echo ""

exec turboquant-server --model "$MODEL" --bits "$BITS" --port "$PORT"
