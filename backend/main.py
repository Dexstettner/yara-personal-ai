"""
main.py — Servidor WebSocket FastAPI que orquestra STT, LLM e TTS
"""

import asyncio
import json
import logging
import io
import os
import re
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
from wake_word import WakeWordDetector

stt = STTEngine(config["stt"], config["audio"])
tts = TTSEngine(config["tts"])
llm = LLMClient(config["ai"])
wake_detector = WakeWordDetector(
    stt,
    config.get("stt", {}).get("wake_word", {}),
    config["audio"],
)

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

    async def _on_wake():
        if active_ws and not is_listening and not is_speaking:
            asyncio.create_task(run_pipeline(active_ws, asyncio.get_event_loop()))

    async def _on_stop():
        stop_speaking_evt.set()
        tts.stop()

    wake_detector.set_callbacks(_on_wake, _on_stop)

    # Pré-carregamento de modelos em background (se habilitado no config)
    perf_cfg = config.get("performance", {})
    if perf_cfg.get("preload_models", False):
        asyncio.create_task(_preload_models())

    await wake_detector.start()
    yield
    await wake_detector.stop()


async def _preload_models():
    """Carrega modelos TTS/STT em background e notifica o cliente via WS."""
    # Aguarda cliente conectar (até 30s)
    for _ in range(60):
        if active_ws:
            break
        await asyncio.sleep(0.5)

    async def _notify(provider: str, done: bool):
        if active_ws:
            await send(active_ws, {
                "type": "model_loading",
                "provider": provider,
                "done": done,
            })

    await _notify(config.get("tts", {}).get("provider", "tts"), False)
    try:
        await tts.preload()
    except Exception as e:
        logger.warning(f"[Preload] Erro ao carregar modelo TTS: {e}")
    await _notify(config.get("tts", {}).get("provider", "tts"), True)

# ─── App FastAPI ──────────────────────────────────────────────────────────
app = FastAPI(title="AI Assistant Backend", lifespan=lifespan)

# ─── Helpers de envio ─────────────────────────────────────────────────────
async def send(ws: WebSocket, msg: dict):
    try:
        await ws.send_json(msg)
    except Exception as e:
        logger.warning(f"[WS] Erro ao enviar mensagem: {e}")

# ─── Emotion parser ──────────────────────────────────────────────────────────

_VALID_EMOTIONS = {
    "happy", "excited", "sad", "angry", "tsundere",
    "shy", "surprised", "calm", "teasing",
}
_SEGMENT_RE = re.compile(r'\[(\w+)\]\s*', re.IGNORECASE)


def _parse_segments(text: str) -> list[tuple[str, str]]:
    """Divide texto em segmentos (emoção, trecho) pelas tags de emoção.
    Ex: '[tsundere] Tch! [angry] Me irritou...' →
        [('tsundere', 'Tch!'), ('angry', 'Me irritou...')]
    Texto antes da primeira tag recebe emoção 'default'.
    """
    parts = _SEGMENT_RE.split(text)
    # split com grupo capturador: [antes, tag1, trecho1, tag2, trecho2, ...]
    segments: list[tuple[str, str]] = []

    if parts[0].strip():
        segments.append(("default", parts[0].strip()))

    i = 1
    while i + 1 < len(parts):
        tag = parts[i].lower()
        seg_text = parts[i + 1].strip()
        emotion = tag if tag in _VALID_EMOTIONS else "default"
        if seg_text:
            segments.append((emotion, seg_text))
        i += 2

    return segments or [("default", text.strip())]


def _display_text(segments: list[tuple[str, str]]) -> str:
    """Junta todos os trechos sem as tags para exibição no chat bubble."""
    return " ".join(t for _, t in segments)


async def _speak_reply(ws: WebSocket, segments: list[tuple[str, str]]) -> None:
    """Reproduz os segmentos de resposta frase a frase, emitindo phrase_start/phrase_end por segmento."""
    global is_speaking

    cfg_tts      = config.get("tts", {})
    tts_enabled  = cfg_tts.get("enabled", True)
    inter_delay  = cfg_tts.get("inter_phrase_delay_ms", 600) / 1000.0
    bubble_secs  = cfg_tts.get("bubble_display_ms", 4000) / 1000.0

    is_speaking = True
    wake_detector.set_speaking(True)
    stop_speaking_evt.clear()
    await send(ws, {"type": "speaking_start"})

    try:
        for i, (emotion, text) in enumerate(segments):
            if stop_speaking_evt.is_set():
                break

            is_last = (i == len(segments) - 1)
            lip_sync = tts.estimate_lip_sync(text) if tts_enabled else []

            await send(ws, {
                "type": "phrase_start",
                "text": text,
                "emotion": emotion,
                "lip_sync": lip_sync,
            })

            if tts_enabled:
                await tts.speak_segments_async([(emotion, text)], stop_speaking_evt)
            else:
                # Duração proporcional ao tamanho do texto, mínimo bubble_secs
                duration = max(bubble_secs, len(text) * 0.060)
                await asyncio.sleep(duration)

            # Emite phrase_end só entre frases (não na última — speaking_stop cuida disso)
            if not is_last and not stop_speaking_evt.is_set():
                await send(ws, {"type": "phrase_end"})
                await asyncio.sleep(inter_delay)
    finally:
        is_speaking = False
        wake_detector.set_speaking(False)
        await send(ws, {"type": "speaking_stop"})


# ─── Pipeline principal ───────────────────────────────────────────────────
async def run_pipeline(ws: WebSocket, loop: asyncio.AbstractEventLoop):
    global is_listening

    # Lock garante que apenas um pipeline roda por vez
    if pipeline_lock.locked():
        logger.warning("[Pipeline] Já em execução, ignorando chamada extra.")
        return

    async with pipeline_lock:
        # 1. Iniciar escuta
        is_listening = True
        wake_detector.set_mic_busy(True)
        await send(ws, {"type": "listening_start"})
        logger.info("[Pipeline] Gravando...")
        try:
            audio = await loop.run_in_executor(None, stt.record_until_silence)
        finally:
            is_listening = False
            wake_detector.set_mic_busy(False)
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
        segments = _parse_segments(reply)
        display = _display_text(segments)
        await send(ws, {"type": "reply_text", "text": display})

        logger.info("[Pipeline] Falando... %s", [(e, t) for e, t in segments])
        await _speak_reply(ws, segments)
        logger.info("[Pipeline] Concluído.")


# ─── Debug: texto → LLM → TTS ─────────────────────────────────────────────
async def run_debug_think(ws: WebSocket, loop: asyncio.AbstractEventLoop, text: str):
    """Pula STT: envia `text` direto para o LLM e fala a resposta."""
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

        segments = _parse_segments(reply)
        display = _display_text(segments)
        await send(ws, {"type": "reply_text", "text": display})

        await _speak_reply(ws, segments)
        logger.info("[Debug/think] Concluído.")


# ─── Debug: texto → TTS direto ────────────────────────────────────────────
async def run_debug_speak(ws: WebSocket, text: str):
    """Pula STT e LLM: fala `text` diretamente via TTS."""
    if pipeline_lock.locked():
        logger.warning("[Debug/speak] Pipeline em execução, ignorando.")
        return

    async with pipeline_lock:
        segments = _parse_segments(text)
        display = _display_text(segments)
        logger.info("[Debug/speak] %s", [(e, t) for e, t in segments])

        await _speak_reply(ws, segments)
        logger.info("[Debug/speak] Concluído.")

# ─── WebSocket endpoint ───────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global active_ws
    await ws.accept()
    active_ws = ws
    loop = asyncio.get_running_loop()
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
    return {"status": "ok", "stt": stt.model is not None, "tts": tts._engine is not None}

# ─── Ponto de entrada ─────────────────────────────────────────────────────
if __name__ == "__main__":
    port = config.get("app", {}).get("backend_port", 8765)
    logger.info(f"[Main] Iniciando servidor na porta {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
