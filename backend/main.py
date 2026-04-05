"""
main.py — Orquestrador WebSocket + spawn dos microserviços STT / TTS / LLM.

Não importa nenhuma dependência de ML diretamente.
Responsabilidades:
  - Lança stt_service, tts_service e llm_service como subprocessos
  - Aguarda todos ficarem prontos
  - Serve o WebSocket para o frontend Tauri
  - Gerencia gravação de áudio (sounddevice + RMS VAD)
  - Coordena wake word detector
"""

import asyncio
import atexit
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

# ── OpenMP duplicado (workaround para ambientes com torch + ctranslate2)
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import warnings
warnings.filterwarnings("ignore", message="Numpy built with MINGW-W64")
warnings.filterwarnings("ignore", "invalid value encountered in.*")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(dotenv_path=_ROOT / ".env")

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# ── Configuração de logging ──────────────────────────────────────────────────
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# ── Carrega config ───────────────────────────────────────────────────────────
CONFIG_PATH = _ROOT / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


config = load_config()

# ── Importa helpers locais (sem deps ML) ────────────────────────────────────
_BACKEND = Path(__file__).parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from recording import Recorder
from utils import estimate_lip_sync, parse_segments, display_text
from clients.stt_client import STTClient
from clients.tts_client import TTSClient
from clients.llm_client import LLMClient as LLMHttpClient
from wake_word import WakeWordDetector

# ── Serviços a lançar ────────────────────────────────────────────────────────
_SVC_CFG = config.get("services", {})
_SERVICES = [
    ("STT", _BACKEND / "services" / "stt_service.py",  _SVC_CFG.get("stt_port",  8766)),
    ("TTS", _BACKEND / "services" / "tts_service.py",  _SVC_CFG.get("tts_port",  8767)),
    ("LLM", _BACKEND / "services" / "llm_service.py",  _SVC_CFG.get("llm_port",  8768)),
]

_service_procs: list[subprocess.Popen] = []


def _spawn_services() -> None:
    """Lança os três microserviços como subprocessos filhos."""
    for name, script, port in _SERVICES:
        env = {**os.environ, "SERVICE_PORT": str(port)}
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            env=env,
            cwd=str(_ROOT),
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        _service_procs.append(proc)
        logger.info(f"[Main] {name} service iniciado (PID {proc.pid}, porta {port})")


def _kill_services() -> None:
    for proc in _service_procs:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass


atexit.register(_kill_services)

# ── Instâncias globais ───────────────────────────────────────────────────────
svc_urls = {
    "stt": f"http://127.0.0.1:{_SVC_CFG.get('stt_port', 8766)}",
    "tts": f"http://127.0.0.1:{_SVC_CFG.get('tts_port', 8767)}",
    "llm": f"http://127.0.0.1:{_SVC_CFG.get('llm_port', 8768)}",
}

recorder     = Recorder(config["audio"], config["stt"])
stt_client   = STTClient(svc_urls["stt"])
tts_client   = TTSClient(svc_urls["tts"])
llm_client   = LLMHttpClient(svc_urls["llm"])
wake_detector = WakeWordDetector(
    stt_client,
    config.get("stt", {}).get("wake_word", {}),
    config["audio"],
)

# ── Estado global ────────────────────────────────────────────────────────────
active_ws: WebSocket | None = None
is_listening  = False
is_speaking   = False
pipeline_lock: asyncio.Lock | None = None
stop_speaking_evt = threading.Event()


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline_lock

    # 1. Spawn microserviços
    _spawn_services()

    # 2. Aguarda todos ficarem prontos
    logger.info("[Main] Aguardando microserviços...")
    results = await asyncio.gather(
        stt_client.wait_ready(attempts=60, delay=2.0),
        tts_client.wait_ready(attempts=30, delay=2.0),
        llm_client.wait_ready(attempts=30, delay=2.0),
    )
    if not all(results):
        logger.error("[Main] Um ou mais serviços não ficaram prontos — continuando mesmo assim.")
    else:
        logger.info("[Main] Todos os microserviços prontos.")

    pipeline_lock = asyncio.Lock()

    # 3. Configura wake word
    async def _on_wake():
        if active_ws and not is_listening and not is_speaking:
            asyncio.create_task(run_pipeline(active_ws))

    async def _on_stop():
        stop_speaking_evt.set()
        await tts_client.stop()

    wake_detector.set_callbacks(_on_wake, _on_stop)
    await wake_detector.start()

    yield

    await wake_detector.stop()
    _kill_services()


# ── App FastAPI ──────────────────────────────────────────────────────────────
app = FastAPI(title="Yara Backend", lifespan=lifespan)


# ── Helpers de envio ─────────────────────────────────────────────────────────
async def send(ws: WebSocket, msg: dict):
    try:
        await ws.send_json(msg)
    except Exception as e:
        logger.warning(f"[WS] Erro ao enviar: {e}")


# ── Pipeline de fala ─────────────────────────────────────────────────────────
async def _speak_reply(ws: WebSocket, segments: list[tuple[str, str]]) -> None:
    global is_speaking

    cfg_tts     = config.get("tts", {})
    tts_enabled = cfg_tts.get("enabled", True)
    inter_delay = cfg_tts.get("inter_phrase_delay_ms", 600) / 1000.0

    is_speaking = True
    wake_detector.set_speaking(True)
    stop_speaking_evt.clear()
    await send(ws, {"type": "speaking_start"})

    try:
        for i, (emotion, text) in enumerate(segments):
            if stop_speaking_evt.is_set():
                break

            is_last  = (i == len(segments) - 1)
            lip_sync = estimate_lip_sync(text) if tts_enabled else []

            await send(ws, {
                "type":     "phrase_start",
                "text":     text,
                "emotion":  emotion,
                "lip_sync": lip_sync,
            })

            if tts_enabled:
                await tts_client.speak([(emotion, text)], stop_speaking_evt)
            else:
                await asyncio.sleep(max(4.0, len(text) * 0.060))

            if not is_last and not stop_speaking_evt.is_set():
                await send(ws, {"type": "phrase_end"})
                await asyncio.sleep(inter_delay)
    finally:
        is_speaking = False
        wake_detector.set_speaking(False)
        await send(ws, {"type": "speaking_stop"})


# ── Pipeline principal ────────────────────────────────────────────────────────
async def run_pipeline(ws: WebSocket):
    global is_listening

    if pipeline_lock.locked():
        logger.warning("[Pipeline] Já em execução, ignorando.")
        return

    async with pipeline_lock:
        # 1. Gravar
        is_listening = True
        wake_detector.set_mic_busy(True)
        await send(ws, {"type": "listening_start"})
        logger.info("[Pipeline] Gravando...")
        loop = asyncio.get_event_loop()
        try:
            audio = await loop.run_in_executor(None, recorder.record_until_silence)
        finally:
            is_listening = False
            wake_detector.set_mic_busy(False)
            await send(ws, {"type": "listening_stop"})

        # 2. Transcrever
        logger.info("[Pipeline] Transcrevendo...")
        text = await stt_client.transcribe(audio)

        if not text.strip():
            await send(ws, {"type": "error", "message": "Não entendi. Tente novamente."})
            return

        await send(ws, {"type": "transcript", "text": text})

        # 3. LLM
        llm_timeout = config.get("ai", {}).get("timeout", 120)
        logger.info("[Pipeline] Consultando LLM...")
        try:
            reply = await asyncio.wait_for(llm_client.chat(text), timeout=llm_timeout)
        except asyncio.TimeoutError:
            logger.error(f"[Pipeline] LLM não respondeu em {llm_timeout}s")
            await send(ws, {"type": "error", "message": "IA demorou demais. Tente um modelo menor."})
            return

        segments = parse_segments(reply)
        await send(ws, {"type": "reply_text", "text": display_text(segments)})

        # 4. TTS
        logger.info("[Pipeline] Falando...")
        await _speak_reply(ws, segments)
        logger.info("[Pipeline] Concluído.")


# ── Debug: texto → LLM → TTS ─────────────────────────────────────────────────
async def run_debug_think(ws: WebSocket, text: str):
    if pipeline_lock.locked():
        return
    async with pipeline_lock:
        await send(ws, {"type": "transcript", "text": text})
        llm_timeout = config.get("ai", {}).get("timeout", 120)
        try:
            reply = await asyncio.wait_for(llm_client.chat(text), timeout=llm_timeout)
        except asyncio.TimeoutError:
            await send(ws, {"type": "error", "message": "IA demorou demais."})
            return
        segments = parse_segments(reply)
        await send(ws, {"type": "reply_text", "text": display_text(segments)})
        await _speak_reply(ws, segments)


# ── Debug: texto → TTS direto ─────────────────────────────────────────────────
async def run_debug_speak(ws: WebSocket, text: str):
    if pipeline_lock.locked():
        return
    async with pipeline_lock:
        segments = parse_segments(text)
        await _speak_reply(ws, segments)


# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global active_ws
    await ws.accept()
    active_ws = ws
    logger.info("[WS] Cliente conectado")

    try:
        while True:
            raw  = await ws.receive_text()
            msg  = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "start_listening":
                if not is_listening and not is_speaking:
                    asyncio.create_task(run_pipeline(ws))

            elif mtype == "stop_listening":
                recorder.stop_recording()

            elif mtype == "stop_speaking":
                stop_speaking_evt.set()
                await tts_client.stop()

            elif mtype == "clear_history":
                await llm_client.clear_history()
                await send(ws, {"type": "history_cleared"})

            elif mtype == "debug_think":
                text = msg.get("text", "").strip()
                if text and not is_listening and not is_speaking:
                    asyncio.create_task(run_debug_think(ws, text))
                elif not text:
                    await send(ws, {"type": "error", "message": "debug_think requer campo 'text'."})

            elif mtype == "debug_speak":
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


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    stt_ready = await stt_client.is_ready()
    tts_ready = await tts_client.is_ready()
    llm_ready = await llm_client.is_ready()
    return {
        "status": "ok",
        "stt": stt_ready,
        "tts": tts_ready,
        "llm": llm_ready,
    }


# ── Ponto de entrada ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = config.get("app", {}).get("backend_port", 8765)
    logger.info(f"[Main] Iniciando servidor na porta {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
