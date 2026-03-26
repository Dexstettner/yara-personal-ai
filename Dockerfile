# ── Backend Python — yara-personal-ai ────────────────────────────────────────
# PyTorch cu126 traz suas próprias CUDA runtime libs, sem precisar de imagem nvidia.
# Para GPU, Docker Desktop no Windows precisa de WSL2 + suporte NVIDIA habilitado.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    # Força pygame/SDL a usar PulseAudio (configurado via PULSE_SERVER no compose)
    SDL_AUDIODRIVER=pulse \
    # Garante que CTranslate2 use GPU quando disponível
    CT2_VERBOSE=0

WORKDIR /app

# ── Dependências do sistema ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PortAudio — sounddevice (microfone)
    libportaudio2 \
    portaudio19-dev \
    # PulseAudio client — reprodução de áudio via host
    libpulse0 \
    # libsndfile — soundfile (f5-tts)
    libsndfile1 \
    # ffmpeg — processamento de áudio
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ── Deps Python: base (numpy, fastapi, sounddevice, etc.) ────────────────────
COPY backend/requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt

# ── Deps Python: STT (silero-vad + faster-whisper) ───────────────────────────
COPY backend/requirements/stt_silero.txt requirements/stt_silero.txt
COPY backend/requirements/stt_faster_whisper.txt requirements/stt_faster_whisper.txt
RUN pip install -r requirements/stt_silero.txt

# ── Deps Python: LLM (ollama client) ─────────────────────────────────────────
COPY backend/requirements/llm_ollama.txt requirements/llm_ollama.txt
RUN pip install -r requirements/llm_ollama.txt

# ── Deps Python: TTS (PyTorch cu126 + f5-tts) ────────────────────────────────
# PyTorch cu126 (~2.6 GB) — camada separada para cache eficiente
RUN pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126

COPY backend/requirements/tts_f5.txt requirements/tts_f5.txt
RUN pip install -r requirements/tts_f5.txt

# ── Código fonte do backend ───────────────────────────────────────────────────
COPY backend/ backend/

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/health')"

CMD ["python", "backend/main.py"]
