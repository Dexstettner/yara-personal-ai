"""
tts — Text-to-Speech package.
Troque o provider em config.json -> tts.provider

  edge-tts    : vozes Microsoft (requer internet, sem API key)
  elevenlabs  : vozes premium (requer internet + API key)
  fish-speech : vozes multilingual (Fish Speech server local)
  kokoro      : TTS local leve, roda em CPU (hexgrad/Kokoro-82M)
"""

import logging
import math
import re

from .edge_tts    import EdgeTTS
from .elevenlabs  import ElevenLabsTTS
from .fish_speech import FishSpeech
from .kokoro      import KokoroTTS

logger = logging.getLogger(__name__)

_ENGINES: dict[str, tuple[type, str]] = {
    "edge-tts":    (EdgeTTS,       "edge_tts"),
    "elevenlabs":  (ElevenLabsTTS, "elevenlabs"),
    "fish-speech": (FishSpeech,    "fish_speech"),
    "kokoro":      (KokoroTTS,     "kokoro"),
}


class TTSEngine:
    """
    Fachada publica — seleciona o provider via config.json -> tts.provider.
    Interface: speak_async(), speak_segments_async(), stop(), estimate_lip_sync()
    """

    def __init__(self, cfg: dict):
        self.cfg      = cfg
        self.provider = cfg.get("provider", "edge-tts").lower()
        self._init_mixer()

        if self.provider not in _ENGINES:
            logger.error(
                f"[TTS] Provider '{self.provider}' invalido. "
                f"Opcoes: {', '.join(_ENGINES)}. Usando edge-tts."
            )
            self.provider = "edge-tts"

        engine_cls, cfg_key = _ENGINES[self.provider]
        logger.info(f"[TTS] Provider: {self.provider}")
        self._engine = engine_cls(cfg.get(cfg_key, {}))

    def _init_mixer(self) -> None:
        try:
            import pygame
            pygame.mixer.pre_init(44100, -16, 2, 1024)
            pygame.mixer.init()
            logger.info("[TTS] pygame mixer inicializado")
        except Exception as e:
            logger.error(f"[TTS] Erro ao inicializar pygame: {e}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        await self._engine.speak_async(text, stop_event, emotion=emotion)

    async def speak_segments_async(
        self, segments: list[tuple[str, str]], stop_event
    ) -> None:
        for emotion, text in segments:
            if stop_event.is_set():
                break
            await self._engine.speak_async(text, stop_event, emotion=emotion)

    async def preload(self) -> None:
        """Pré-carrega o modelo em background se o engine suportar _ensure_model."""
        if hasattr(self._engine, "_ensure_model"):
            logger.info(f"[TTS] Pré-carregando modelo ({self.provider})...")
            import asyncio
            await asyncio.to_thread(self._engine._ensure_model)
            logger.info(f"[TTS] Modelo ({self.provider}) pronto.")

    def stop(self) -> None:
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def estimate_lip_sync(self, text: str, n_frames: int = 40) -> list[float]:
        """Estima movimento labial por contagem de vogais/silabas."""
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
