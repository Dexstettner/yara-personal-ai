"""
tts/voicevox.py — Provider TTS: VOICEVOX Engine (vozes anime japonesas, local/offline).

Instale o VOICEVOX separadamente: https://voicevox.hiroshiba.jp/
O servidor deve estar rodando antes de iniciar o assistente.

Speakers populares:
  1  — Shikoku Metan (normal)
  2  — Zundamon (normal)  (padrao)
  8  — Shikoku Metan (sasayaki)
  13 — Kasukabe Tsumugi
Lista completa: GET http://localhost:50021/speakers
"""

import asyncio
import logging

from ._common import play_bytes, tts_preprocess

logger = logging.getLogger(__name__)


class VoiceVox:
    """
    Config (config.json -> tts.voicevox):
      host      : "http://localhost:50021"
      speaker_id: 2
      speed     : 1.0
      pitch     : 0.0
      intonation: 1.0
      volume    : 1.0
    """

    def __init__(self, cfg: dict):
        self._lock      = asyncio.Lock()
        self.host       = cfg.get("host",       "http://localhost:50021")
        self.speaker_id = cfg.get("speaker_id", 2)
        self.speed      = cfg.get("speed",      1.0)
        self.pitch      = cfg.get("pitch",      0.0)
        self.intonation = cfg.get("intonation", 1.0)
        self.volume     = cfg.get("volume",     1.0)
        logger.info(f"[TTS/voicevox] host: {self.host} | speaker: {self.speaker_id}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        async with self._lock:
            try:
                import aiohttp
            except ImportError:
                logger.error("[TTS/voicevox] Instale: pip install aiohttp")
                return

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.host}/audio_query",
                        params={"text": text, "speaker": self.speaker_id},
                        headers={"Connection": "close"},
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"[TTS/voicevox] audio_query HTTP {resp.status}")
                            logger.warning("Certifique-se que o VOICEVOX esta aberto.")
                            return
                        query = await resp.json()

                    query["speedScale"]      = self.speed
                    query["pitchScale"]      = self.pitch
                    query["intonationScale"] = self.intonation
                    query["volumeScale"]     = self.volume

                    async with session.post(
                        f"{self.host}/synthesis",
                        params={"speaker": self.speaker_id},
                        json=query,
                        headers={"Connection": "close"},
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"[TTS/voicevox] synthesis HTTP {resp.status}")
                            return
                        wav_bytes = await resp.read()

                if not stop_event.is_set():
                    await play_bytes(wav_bytes, ".wav", stop_event)

            except aiohttp.ClientConnectorError:
                logger.error("[TTS/voicevox] Nao foi possivel conectar. VOICEVOX esta rodando?")
            except Exception as e:
                logger.error(f"[TTS/voicevox] Erro: {e}")
