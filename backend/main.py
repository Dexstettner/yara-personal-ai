"""
main.py — Servidor WebSocket FastAPI que orquestra STT, LLM e TTS
"""

import asyncio
import json
import logging
import io
import os
import threading
import sys
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

# ─── OpenMP duplicado (PyTorch + CTranslate2 carregam libiomp5md.dll duas vezes)
# Deve ser setado ANTES de qualquer import que carregue OpenMP
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# ─── Filtros de warning ANTES de qualquer import não-stdlib ──────────────────
# NumPy conda-forge MINGW
warnings.filterwarnings("ignore", message="Numpy built with MINGW-W64")
warnings.filterwarnings("ignore", "invalid value encountered in exp2")
warnings.filterwarnings("ignore", "invalid value encountered in log10")
warnings.filterwarnings("ignore", "invalid value encountered in nextafter")
# pkg_resources deprecated — pygame emite UserWarning, outros DeprecationWarning
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
# hf_xet não instalado — fallback para HTTP é funcional, warning é desnecessário
warnings.filterwarnings("ignore", message="Xet Storage is enabled")
# past_key_values legado no indextts — não quebra até transformers 4.53
warnings.filterwarnings("ignore", message="Passing a tuple of `past_key_values`")
# GenerationMixin — aviso interno do indextts, não afeta funcionamento atual
warnings.filterwarnings("ignore", message=".*GenerationMixin.*")

from dotenv import load_dotenv

# Carrega .env da raiz do projeto (tokens, chaves de API)
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# ─── Configuração de logging ──────────────────────────────────────────────
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("main")

# ─── Carrega config ───────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent.parent / "config.json"

def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# ─── Inicializa motores ───────────────────────────────────────────────────
from stt import STTEngine
from tts import TTSEngine
from llm import LLMClient

stt = STTEngine(config["stt"], config["audio"])
tts = TTSEngine(config["tts"])
llm = LLMClient(config["ai"])

# ─── Estado global ────────────────────────────────────────────────────────
active_ws: WebSocket | None = None
is_listening  = False
is_speaking   = False
pipeline_lock: asyncio.Lock | None = None
stop_speaking_evt = threading.Event()

# ─── Lifespan (substitui o deprecated @app.on_event) ─────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline_lock
    pipeline_lock = asyncio.Lock()
    yield

# ─── App FastAPI ──────────────────────────────────────────────────────────
app = FastAPI(title="AI Assistant Backend", lifespan=lifespan)

# ─── Helpers de envio ─────────────────────────────────────────────────────
async def send(ws: WebSocket, msg: dict):
    try:
        await ws.send_json(msg)
    except Exception as e:
        logger.warning(f"[WS] Erro ao enviar mensagem: {e}")

# ─── Pipeline principal ───────────────────────────────────────────────────
async def run_pipeline(ws: WebSocket, loop: asyncio.AbstractEventLoop):
    global is_listening, is_speaking

    # Lock garante que apenas um pipeline roda por vez
    if pipeline_lock.locked():
        logger.warning("[Pipeline] Já em execução, ignorando chamada extra.")
        return

    async with pipeline_lock:
        # 1. Iniciar escuta
        is_listening = True
        await send(ws, {"type": "listening_start"})
        logger.info("[Pipeline] Gravando...")

        audio = await loop.run_in_executor(None, stt.record_until_silence)

        is_listening = False
        await send(ws, {"type": "listening_stop"})

        # 2. Transcrição
        logger.info("[Pipeline] Transcrevendo...")
        text = await loop.run_in_executor(None, stt.transcribe, audio)

        if not text.strip():
            await send(ws, {"type": "error", "message": "Não entendi. Tente novamente."})
            return

        await send(ws, {"type": "transcript", "text": text})

        # 3. LLM (com timeout para evitar travamento por VRAM insuficiente)
        llm_timeout = config.get("ai", {}).get("timeout", 120)
        logger.info("[Pipeline] Consultando LLM...")
        try:
            reply = await asyncio.wait_for(
                loop.run_in_executor(None, llm.chat, text),
                timeout=llm_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"[Pipeline] LLM não respondeu em {llm_timeout}s — VRAM insuficiente?")
            await send(ws, {"type": "error", "message": "IA demorou demais. Tente um modelo menor ou reduza o contexto."})
            return
        await send(ws, {"type": "reply_text", "text": reply})

        # 4. Lip-sync estimado a partir do texto
        lip_sync = tts.estimate_lip_sync(reply)

        # 5. Reproduzir voz (edge-tts é async — sem run_in_executor, sem deadlock)
        logger.info("[Pipeline] Falando...")
        is_speaking = True
        stop_speaking_evt.clear()
        await send(ws, {"type": "speaking_start", "lip_sync": lip_sync})

        await tts.speak_async(reply, stop_speaking_evt)

        is_speaking = False
        await send(ws, {"type": "speaking_stop"})
        logger.info("[Pipeline] Concluído.")


# ─── Debug: texto → LLM → TTS ─────────────────────────────────────────────
async def run_debug_think(ws: WebSocket, loop: asyncio.AbstractEventLoop, text: str):
    """Pula STT: envia `text` direto para o LLM e fala a resposta."""
    global is_speaking

    if pipeline_lock.locked():
        logger.warning("[Debug/think] Pipeline em execução, ignorando.")
        return

    async with pipeline_lock:
        logger.info(f"[Debug/think] Texto: {text!r}")
        await send(ws, {"type": "transcript", "text": text})

        llm_timeout = config.get("ai", {}).get("timeout", 120)
        try:
            reply = await asyncio.wait_for(
                loop.run_in_executor(None, llm.chat, text),
                timeout=llm_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"[Debug/think] LLM timeout ({llm_timeout}s)")
            await send(ws, {"type": "error", "message": "IA demorou demais."})
            return

        await send(ws, {"type": "reply_text", "text": reply})

        lip_sync = tts.estimate_lip_sync(reply)
        is_speaking = True
        stop_speaking_evt.clear()
        await send(ws, {"type": "speaking_start", "lip_sync": lip_sync})

        await tts.speak_async(reply, stop_speaking_evt)

        is_speaking = False
        await send(ws, {"type": "speaking_stop"})
        logger.info("[Debug/think] Concluído.")


# ─── Debug: texto → TTS direto ────────────────────────────────────────────
async def run_debug_speak(ws: WebSocket, text: str):
    """Pula STT e LLM: fala `text` diretamente via TTS."""
    global is_speaking

    if pipeline_lock.locked():
        logger.warning("[Debug/speak] Pipeline em execução, ignorando.")
        return

    async with pipeline_lock:
        logger.info(f"[Debug/speak] Texto: {text!r}")

        lip_sync = tts.estimate_lip_sync(text)
        is_speaking = True
        stop_speaking_evt.clear()
        await send(ws, {"type": "speaking_start", "lip_sync": lip_sync})

        await tts.speak_async(text, stop_speaking_evt)

        is_speaking = False
        await send(ws, {"type": "speaking_stop"})
        logger.info("[Debug/speak] Concluído.")

# ─── WebSocket endpoint ───────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global active_ws
    await ws.accept()
    active_ws = ws
    loop = asyncio.get_event_loop()
    logger.info("[WS] Cliente conectado")

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "start_listening":
                if not is_listening and not is_speaking:
                    asyncio.create_task(run_pipeline(ws, loop))

            elif mtype == "stop_listening":
                stt.stop_recording()

            elif mtype == "stop_speaking":
                stop_speaking_evt.set()
                tts.stop()

            elif mtype == "clear_history":
                llm.clear_history()
                await send(ws, {"type": "history_cleared"})

            elif mtype == "debug_think":
                # Debug: texto → LLM → TTS (pula STT)
                text = msg.get("text", "").strip()
                if text and not is_listening and not is_speaking:
                    asyncio.create_task(run_debug_think(ws, loop, text))
                elif not text:
                    await send(ws, {"type": "error", "message": "debug_think requer campo 'text'."})

            elif mtype == "debug_speak":
                # Debug: texto → TTS direto (pula STT e LLM)
                text = msg.get("text", "").strip()
                if text and not is_listening and not is_speaking:
                    asyncio.create_task(run_debug_speak(ws, text))
                elif not text:
                    await send(ws, {"type": "error", "message": "debug_speak requer campo 'text'."})

            else:
                logger.warning(f"[WS] Mensagem desconhecida: {mtype}")

    except WebSocketDisconnect:
        logger.info("[WS] Cliente desconectado")
        active_ws = None
    except Exception as e:
        logger.error(f"[WS] Erro: {e}")
        active_ws = None

# ─── Health check ─────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "stt": stt.model is not None, "tts": tts.tts is not None}

# ─── Ponto de entrada ─────────────────────────────────────────────────────
if __name__ == "__main__":
    port = config.get("app", {}).get("backend_port", 8765)
    logger.info(f"[Main] Iniciando servidor na porta {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
