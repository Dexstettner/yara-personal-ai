"""
tts/_common.py — Utilitarios compartilhados entre todos os providers TTS.
"""

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Reproducao de audio via pygame ───────────────────────────────────────────

async def play_file(path: str, stop_event) -> None:
    """Reproduz arquivo de audio (mp3/wav) via pygame e aguarda terminar."""
    import pygame
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if stop_event.is_set():
                pygame.mixer.music.stop()
                break
            await asyncio.sleep(0.05)
    finally:
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass


async def play_bytes(data: bytes, suffix: str, stop_event) -> None:
    """Salva bytes em arquivo temporario e reproduz."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    try:
        await play_file(tmp.name, stop_event)
    finally:
        if os.path.exists(tmp.name):
            try:
                os.remove(tmp.name)
            except Exception:
                pass


# ── Pre-processamento de texto ────────────────────────────────────────────────

_CLEANUP_MAP = [
    (r'\*\*([^*\n]+)\*\*', r'\1'),   # **bold** -> texto
    (r'_([^_\n]+)_',       r'\1'),   # _italic_ -> texto
    (r'\*[^*\n]{1,80}\*',  ''),      # *acao* -> remove
    (r' {2,}',             ' '),     # espacos duplicados
]


def tts_preprocess(text: str) -> str:
    """Remove markdown e acoes que o TTS leria literalmente."""
    for pattern, replacement in _CLEANUP_MAP:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text.strip()


# ── Divisao de sentencas ──────────────────────────────────────────────────────

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?...])\s+')
_CLAUSE_SPLIT_RE   = re.compile(r'(?<=[,;:])\s+')


def split_sentences(text: str, max_chars: int = 150) -> list[str]:
    """Divide texto em sentencas curtas.
    Necessario para F5-TTS evitar batching interno com espectrogramas incompativeis."""
    parts = _SENTENCE_SPLIT_RE.split(text)
    result: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            result.append(part)
        else:
            clauses = _CLAUSE_SPLIT_RE.split(part)
            result.extend(c.strip() for c in clauses if c.strip())
    return result or [text]


# ── Audio de referencia ───────────────────────────────────────────────────────

def ref_to_wav(reference_audio: str) -> tuple[str | None, bool]:
    """Resolve caminho do audio de referencia, converte para WAV se necessario.
    Retorna (path, is_temp) — is_temp indica se deve ser deletado apos uso."""
    root = Path(__file__).parent.parent.parent
    ref  = Path(root / reference_audio)

    if not ref.exists():
        logger.warning(f"[TTS] Referencia nao encontrada: {ref} — sintetizando sem clonagem")
        return None, False

    if ref.suffix.lower() != ".wav":
        import soundfile as sf
        data, sr = sf.read(str(ref))
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, data, sr)
        return tmp.name, True

    return str(ref), False
