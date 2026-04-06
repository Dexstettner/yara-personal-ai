"""
kokoclone/server.py — Servidor HTTP para KokoClone voice cloning.

Requer Python 3.12 + ambiente conda separado:
    conda create -n kokoclone python=3.12
    conda activate kokoclone
    pip install git+https://github.com/frothywater/kanade-tokenizer.git
    pip install git+https://github.com/Ashish-Patnaik/kokoclone.git
    pip install fastapi uvicorn soundfile

Uso:
    conda activate kokoclone
    python kokoclone/server.py

    # ou com opções:
    python kokoclone/server.py --ref backend/assets/reference_voice.wav --port 8010
"""

import argparse
import io
import logging
import os
import sys
import tempfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Argumentos ─────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="KokoClone TTS server")
parser.add_argument("--ref",  default="backend/assets/reference_voice.wav",
                    help="Caminho para o áudio de referência (WAV/MP3)")
parser.add_argument("--lang", default="pt",
                    help="Idioma para síntese (padrão: pt)")
parser.add_argument("--port", type=int, default=8010,
                    help="Porta do servidor (padrão: 8010)")
parser.add_argument("--host", default="127.0.0.1",
                    help="Host (padrão: 127.0.0.1)")
args = parser.parse_args()

# Resolve caminho relativo à raiz do projeto (dois níveis acima de kokoclone/)
_ROOT = Path(__file__).parent.parent
ref_path = str(_ROOT / args.ref)
lang = args.lang

if not Path(ref_path).exists():
    logger.error(f"Áudio de referência não encontrado: {ref_path}")
    sys.exit(1)

logger.info(f"Referência : {ref_path}")
logger.info(f"Carregando KokoClone...")

try:
    from kokoclone import KokoClone
except ImportError:
    try:
        from core.cloner import KokoClone
    except ImportError:
        logger.error(
            "KokoClone não encontrado.\n"
            "  conda activate kokoclone\n"
            "  pip install git+https://github.com/Ashish-Patnaik/kokoclone.git"
        )
        sys.exit(1)

_cloner = KokoClone()
logger.info("KokoClone pronto.")

# ── FastAPI app ────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import soundfile as sf
import numpy as np

app = FastAPI(title="KokoClone TTS Server")


class TTSRequest(BaseModel):
    text: str
    speed: float = 1.0  # KokoClone não suporta speed, ignorado


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tts")
def tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text vazio")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        _cloner.generate(
            req.text,
            lang,
            ref_path,
            output_path=tmp.name,
        )
        audio, sr = sf.read(tmp.name)
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV")
        return Response(content=buf.getvalue(), media_type="audio/wav")
    except Exception as e:
        logger.error(f"Erro na síntese: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.remove(tmp.name)
        except Exception:
            pass


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Servidor em http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
