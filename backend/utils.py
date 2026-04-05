"""
utils.py — Utilitários puros do backend (sem deps de ML).

Funções reutilizadas por main.py e pelos serviços.
"""

import math
import re


# ── Lip-sync estimado ────────────────────────────────────────────────────────

def estimate_lip_sync(text: str, n_frames: int = 40) -> list[float]:
    """Estima movimento labial por contagem de vogais/sílabas.
    Retorna lista de n_frames floats [0.0, 1.0]."""
    vowels    = len(re.findall(r'[aeiouáéíóúàèìòùâêîôûãõ]', text.lower()))
    syllables = max(vowels, 1)
    frames    = []
    for i in range(n_frames):
        phase = i / n_frames * syllables * math.pi * 1.5
        val   = max(0.0, math.sin(phase)) * 0.85
        noise = ((hash(text + str(i)) % 100) / 100) * 0.15
        frames.append(min(1.0, val + noise * 0.3))
    fade = max(2, n_frames // 8)
    for i in range(fade):
        t = i / fade
        frames[i]            *= t
        frames[n_frames-1-i] *= t
    return frames


# ── Parser de emoção ─────────────────────────────────────────────────────────

_VALID_EMOTIONS = {
    "happy", "excited", "sad", "angry", "tsundere",
    "shy", "surprised", "calm", "teasing",
}
_SEGMENT_RE = re.compile(r'\[(\w+)\]\s*', re.IGNORECASE)


def parse_segments(text: str) -> list[tuple[str, str]]:
    """Divide texto em segmentos (emoção, trecho) pelas tags de emoção.
    Ex: '[tsundere] Tch! [angry] Me irritou...' →
        [('tsundere', 'Tch!'), ('angry', 'Me irritou...')]
    Texto antes da primeira tag recebe emoção 'default'.
    """
    parts = _SEGMENT_RE.split(text)
    segments: list[tuple[str, str]] = []

    if parts[0].strip():
        segments.append(("default", parts[0].strip()))

    i = 1
    while i + 1 < len(parts):
        tag      = parts[i].lower()
        seg_text = parts[i + 1].strip()
        emotion  = tag if tag in _VALID_EMOTIONS else "default"
        if seg_text:
            segments.append((emotion, seg_text))
        i += 2

    return segments or [("default", text.strip())]


def display_text(segments: list[tuple[str, str]]) -> str:
    """Junta todos os trechos sem as tags para exibição no chat bubble."""
    return " ".join(t for _, t in segments)
