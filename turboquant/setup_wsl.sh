#!/bin/bash
# setup_wsl.sh — Configura ambiente WSL2 para turboquant-server
# Uso: bash turboquant/setup_wsl.sh
set -e

CONDA_ENV="turboquant"
TORCH_INDEX="https://download.pytorch.org/whl/cu126"

echo "=== TurboQuant WSL2 Setup ==="

# ── 1. Conda ──────────────────────────────────────────────────────────────────
if ! command -v conda &>/dev/null; then
    echo "[1/4] Instalando Miniconda..."
    wget -q https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
    bash /tmp/miniconda.sh -b -p "$HOME/miniconda3"
    eval "$($HOME/miniconda3/bin/conda shell.bash hook)"
    conda init bash
    echo "      Reinicie o terminal e rode este script novamente para continuar."
    exit 0
fi

eval "$(conda shell.bash hook)"

# ── 2. Ambiente conda ─────────────────────────────────────────────────────────
if conda env list | grep -q "^$CONDA_ENV "; then
    echo "[1/4] Ambiente '$CONDA_ENV' já existe, atualizando..."
else
    echo "[1/4] Criando ambiente '$CONDA_ENV' (Python 3.11)..."
    conda create -n "$CONDA_ENV" python=3.11 -y
fi

conda activate "$CONDA_ENV"

# ── 3. PyTorch 2.8.0 + CUDA 12.6 (instalar antes do autoawq) ─────────────────
echo "[2/4] Instalando PyTorch 2.8.0+cu126..."
pip install torch==2.8.0+cu126 --index-url "$TORCH_INDEX" -q

# ── 4. AutoAWQ + TurboQuant ───────────────────────────────────────────────────
# autoawq compila corretamente no Linux (sys.abiflags existe, NVCC disponível).
# --no-build-isolation garante que usa o torch já instalado.
echo "[3/4] Instalando autoawq (compila extensões CUDA — pode demorar ~5min)..."
pip install autoawq --no-build-isolation -q

echo "[4/4] Instalando turboquant, transformers, accelerate..."
pip install turboquant transformers accelerate -q

# ── Cache compartilhado com Windows ──────────────────────────────────────────
# Evita re-download do modelo (~4GB AWQ) se já foi baixado no Windows.
WIN_HF_CACHE="/mnt/c/Users/$(cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r')/.cache/huggingface"
if [ -d "$WIN_HF_CACHE" ]; then
    echo ""
    echo "Cache HuggingFace detectado em $WIN_HF_CACHE"
    echo "Para reutilizá-lo e evitar re-download, adicione ao ~/.bashrc:"
    echo "  export HF_HOME=\"$WIN_HF_CACHE\""
fi

echo ""
echo "=== Setup concluído! ==="
echo "Para iniciar o servidor:"
echo "  bash turboquant/start_wsl.sh"
echo ""
echo "Ou manualmente:"
echo "  conda activate $CONDA_ENV"
echo "  turboquant-server --model Qwen/Qwen2.5-7B-Instruct-AWQ --bits 4 --port 8000"
