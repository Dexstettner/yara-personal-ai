"""
services/tts_service.py — Microserviço TTS (Text-to-Speech).

Porta padrão: 8767 (configurável via env SERVICE_PORT ou config.json → services.tts_port)

Endpoints:
  POST /speak      — sintetiza e reproduz segmentos; bloqueia até terminar
  POST /stop       — interrompe reprodução em andamento
  GET  /lip_sync   — estima movimento labial para um texto
  GET  /health     — status do serviço
"""

import json
import logging
import os
import sys
import threading
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

# ── Workarounds de ambiente ──────────────────────────────────────────────────
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.filterwarnings("ignore", message="Numpy built with MINGW-W64")
warnings.filterwarnings("ignore", "invalid value encountered in.*")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
warnings.filterwarnings("ignore", message="Xet Storage is enabled")
warnings.filterwarnings("ignore", message="Passing a tuple of `past_key_values`")
warnings.filterwarnings("ignore", message=".*GenerationMixin.*")

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# ── Localiza raiz do projeto ─────────────────────────────────────────────────
_HERE    = Path(__file__).parent
_ROOT    = _HERE.parent.parent
_BACKEND = _HERE.parent

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ── Configuração de logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("tts_service")

# ── Carrega config ───────────────────────────────────────────────────────────
_CONFIG_PATH = _ROOT / "config.json"
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _config = json.load(_f)

# ── Estado global do serviço ─────────────────────────────────────────────────
_tts        = None
_stop_event = threading.Event()
_speak_lock = None   # asyncio.Lock, criado no lifespan


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    global _tts, _speak_lock

    from tts import TTSEngine
    _tts        = TTSEngine(_config["tts"])
    _speak_lock = asyncio.Lock()
    logger.info("[TTS service] Engine inicializado")
    yield
    logger.info("[TTS service] Encerrando")


app = FastAPI(title="Yara TTS Service", lifespan=lifespan)


# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class Segment(BaseModel):
    emotion: str = "default"
    text: str


class SpeakRequest(BaseModel):
    segments: List[Segment]


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/speak")
async def speak(req: SpeakRequest):
    """Sintetiza e reproduz os segmentos. Bloqueia até o fim da reprodução
    ou até que POST /stop seja chamado."""
    async with _speak_lock:
        _stop_event.clear()
        pairs = [(s.emotion, s.text) for s in req.segments]
        try:
            await _tts.speak_segments_async(pairs, _stop_event)
        except Exception as e:
            logger.error(f"[TTS service] Erro ao falar: {e}")
            return {"ok": False, "error": str(e)}
    return {"ok": True}


@app.post("/stop")
async def stop():
    """Interrompe reprodução em andamento com fadeout suave."""
    _stop_event.set()
    _tts.stop()
    return {"ok": True}


@app.get("/lip_sync")
async def lip_sync(text: str, n_frames: int = 40):
    """Estima movimento labial (cálculo puro — sem GPU)."""
    import sys as _sys
    # utils está um nível acima (backend/)
    if str(_BACKEND) not in _sys.path:
        _sys.path.insert(0, str(_BACKEND))
    from utils import estimate_lip_sync
    return {"frames": estimate_lip_sync(text, n_frames)}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "tts",
        "provider": _config["tts"].get("provider", "unknown"),
        "ready": _tts is not None,
    }


# ── Ponto de entrada ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(
        os.environ.get("SERVICE_PORT")
        or _config.get("services", {}).get("tts_port", 8767)
    )
    logger.info(f"[TTS service] Iniciando na porta {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
