"""
stt — Speech-to-Text package.
Troque o provider em config.json -> stt.provider

  faster-whisper : VAD por RMS + CTranslate2 (sem torch)
  silero         : VAD neural silero-vad + faster-whisper
"""

import logging

from .faster_whisper import FasterWhisperSTT
from .silero import SileroSTT

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, tuple[type, str]] = {
    "faster-whisper": (FasterWhisperSTT, "faster_whisper"),
    "silero":         (SileroSTT,        "silero"),
}


class STTEngine:
    """
    Fachada publica — seleciona o provider via config.json -> stt.provider.
    Interface: record_until_silence(), transcribe(), stop_recording(), .model
    """

    def __init__(self, cfg_stt: dict, cfg_audio: dict):
        provider = cfg_stt.get("provider", "faster-whisper").lower()

        if provider == "whisper":
            logger.warning(
                "[STT] Provider 'whisper' renomeado para 'faster-whisper'. "
                "Atualize config.json -> stt.provider."
            )
            provider = "faster-whisper"

        if provider not in _PROVIDERS:
            logger.error(
                f"[STT] Provider '{provider}' invalido. "
                f"Opcoes: {', '.join(_PROVIDERS)}. Usando faster-whisper."
            )
            provider = "faster-whisper"

        cls, cfg_key = _PROVIDERS[provider]
        logger.info(f"[STT] Provider: {provider}")
        self._engine = cls(cfg_stt.get(cfg_key, {}), cfg_audio)

    @property
    def model(self):
        """Exposto para health check em main.py: stt.model is not None."""
        return self._engine.model

    def record_until_silence(self):
        return self._engine.record_until_silence()

    def stop_recording(self) -> None:
        self._engine.stop_recording()

    def transcribe(self, audio) -> str:
        return self._engine.transcribe(audio)
