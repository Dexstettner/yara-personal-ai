"""
services/stt_service.py — Microserviço STT (Speech-to-Text).

Porta padrão: 8766 (configurável via env SERVICE_PORT ou config.json → services.stt_port)

Endpoints:
  POST /transcribe  — recebe áudio float32 base64, retorna texto
  GET  /health      — status do serviço e do modelo
"""

import base64
import json
import logging
import os
import sys
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

# ── Workarounds de ambiente ──────────────────────────────────────────────────
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.filterwarnings("ignore", message="Numpy built with MINGW-W64")
warnings.filterwarnings("ignore", "invalid value encountered in.*")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

import numpy as np
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# ── Localiza raiz do projeto ─────────────────────────────────────────────────
_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent          # yara-personal-ai/
_BACKEND = _HERE.parent              # yara-personal-ai/backend/

# Garante que o backend/ está no PYTHONPATH para importar stt/
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ── Configuração de logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("stt_service")

# ── Carrega config ───────────────────────────────────────────────────────────
_CONFIG_PATH = _ROOT / "config.json"
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _config = json.load(_f)

# ── Engine STT (carregado no lifespan) ───────────────────────────────────────
_stt = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _stt
    from stt import STTEngine
    _stt = STTEngine(_config["stt"], _config["audio"])
    logger.info("[STT service] Engine inicializado")
    yield
    logger.info("[STT service] Encerrando")


app = FastAPI(title="Yara STT Service", lifespan=lifespan)


# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    audio_b64: str          # bytes float32 PCM em base64
    sample_rate: int = 16000


class TranscribeResponse(BaseModel):
    text: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(req: TranscribeRequest):
    import asyncio
    audio_bytes = base64.b64decode(req.audio_b64)
    audio = np.frombuffer(audio_bytes, dtype=np.float32).copy()
    loop  = asyncio.get_event_loop()
    text  = await loop.run_in_executor(None, _stt.transcribe, audio)
    return TranscribeResponse(text=text)


@app.get("/health")
async def health():
    ready = _stt is not None and _stt.model is not None
    return {
        "status": "ok",
        "service": "stt",
        "provider": _config["stt"].get("provider", "unknown"),
        "ready": ready,
    }


# ── Ponto de entrada ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(
        os.environ.get("SERVICE_PORT")
        or _config.get("services", {}).get("stt_port", 8766)
    )
    logger.info(f"[STT service] Iniciando na porta {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
