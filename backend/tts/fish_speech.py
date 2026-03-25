"""
tts/fish_speech.py — Provider TTS: Fish Speech (vozes naturais multilingual, local/offline).

Inicie o servidor: https://github.com/fishaudio/fish-speech
  uvicorn tools.api_server:app --host 0.0.0.0 --port 50021
"""

import logging

from ._common import play_bytes, tts_preprocess

logger = logging.getLogger(__name__)


class FishSpeech:
    """
    Config (config.json -> tts.fish_speech):
      host        : "http://localhost:50021"
      reference_id: null  (null = voz padrao, ou ID de voz clonada)
    """

    def __init__(self, cfg: dict):
        self.host         = cfg.get("host",         "http://localhost:50021")
        self.reference_id = cfg.get("reference_id")
        logger.info(f"[TTS/fish-speech] host: {self.host}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        try:
            import aiohttp
        except ImportError:
            logger.error("[TTS/fish-speech] Instale: pip install aiohttp")
            return

        payload: dict = {
            "text":      text,
            "format":    "wav",
            "streaming": False,
        }
        if self.reference_id:
            payload["reference_id"] = self.reference_id

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.host}/v1/tts", json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"[TTS/fish-speech] TTS HTTP {resp.status}")
                        logger.warning("Certifique-se que o Fish Speech server esta rodando.")
                        return
                    audio_bytes = await resp.read()

            if not stop_event.is_set():
                await play_bytes(audio_bytes, ".wav", stop_event)

        except aiohttp.ClientConnectorError:
            logger.error("[TTS/fish-speech] Nao foi possivel conectar. Servidor rodando?")
        except Exception as e:
            logger.error(f"[TTS/fish-speech] Erro: {e}")
