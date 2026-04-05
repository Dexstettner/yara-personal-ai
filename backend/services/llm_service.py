"""
services/llm_service.py — Microserviço LLM (Large Language Model).

Porta padrão: 8768 (configurável via env SERVICE_PORT ou config.json → services.llm_port)

Endpoints:
  POST /chat           — envia mensagem, retorna resposta (com histórico interno)
  POST /clear_history  — limpa histórico da conversa
  GET  /health         — status do serviço
"""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

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
logger = logging.getLogger("llm_service")

# ── Carrega config ───────────────────────────────────────────────────────────
_CONFIG_PATH = _ROOT / "config.json"
with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _config = json.load(_f)

# ── Estado global ────────────────────────────────────────────────────────────
_provider = None
_history: list[dict]  = []
_cfg_ai   = _config["ai"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _provider
    from llm import LLMClient
    # LLMClient gerencia histórico internamente; aqui usamos o provider diretamente
    # para controle explícito do histórico no serviço.
    _client  = LLMClient(_cfg_ai)
    _provider = _client  # reusa a fachada existente
    logger.info("[LLM service] Provider inicializado")
    yield
    logger.info("[LLM service] Encerrando")


app = FastAPI(title="Yara LLM Service", lifespan=lifespan)


# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    text: str


class ChatResponse(BaseModel):
    reply: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    import asyncio
    loop  = asyncio.get_event_loop()
    reply = await loop.run_in_executor(None, _provider.chat, req.text)
    return ChatResponse(reply=reply)


@app.post("/clear_history")
async def clear_history():
    _provider.clear_history()
    return {"ok": True}


@app.get("/health")
async def health():
    ready = _provider is not None and getattr(_provider, "_provider", None) is not None
    return {
        "status": "ok",
        "service": "llm",
        "provider": _cfg_ai.get("provider", "unknown"),
        "ready": ready,
    }


# ── Ponto de entrada ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(
        os.environ.get("SERVICE_PORT")
        or _config.get("services", {}).get("llm_port", 8768)
    )
    logger.info(f"[LLM service] Iniciando na porta {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
