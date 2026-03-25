"""
tts/edge_tts.py — Provider TTS: vozes neurais Microsoft Edge (gratuito, requer internet).

Vozes PT-BR:
  pt-BR-ThalitaNeural   — feminino, jovem/casual  (padrao)
  pt-BR-FranciscaNeural — feminino, profissional
  pt-BR-AntonioNeural   — masculino
"""

import logging
import os
import tempfile

from ._common import play_file, tts_preprocess

logger = logging.getLogger(__name__)


class EdgeTTS:
    """
    Config (config.json -> tts.edge_tts):
      voice     : "pt-BR-ThalitaNeural"
      rate_pct  : "+0%"
      volume_pct: "+0%"
    """

    def __init__(self, cfg: dict):
        self.voice  = cfg.get("voice",      "pt-BR-ThalitaNeural")
        self.rate   = cfg.get("rate_pct",   "+0%")
        self.volume = cfg.get("volume_pct", "+0%")
        logger.info(f"[TTS/edge-tts] voz: {self.voice}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        import edge_tts

        text = tts_preprocess(text)
        tmp  = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            communicate = edge_tts.Communicate(
                text, self.voice,
                rate=self.rate, volume=self.volume
            )
            await communicate.save(tmp.name)
            if not stop_event.is_set():
                await play_file(tmp.name, stop_event)
        except Exception as e:
            logger.error(f"[TTS/edge-tts] Erro: {e}")
        finally:
            if os.path.exists(tmp.name):
                try:
                    os.remove(tmp.name)
                except Exception:
                    pass
