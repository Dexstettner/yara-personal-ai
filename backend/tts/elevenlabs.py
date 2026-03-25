"""
tts/elevenlabs.py — Provider TTS: ElevenLabs (vozes neurais premium, requer API key).

Configure: ELEVENLABS_API_KEY=sk-... no .env
"""

import logging
import os

from ._common import play_bytes, tts_preprocess

logger = logging.getLogger(__name__)

EMOTION_PARAMS: dict[str, dict] = {
    "default":   {"stability": 0.50, "similarity_boost": 0.75, "style": 0.00},
    "happy":     {"stability": 0.35, "similarity_boost": 0.70, "style": 0.30},
    "excited":   {"stability": 0.25, "similarity_boost": 0.65, "style": 0.50},
    "sad":       {"stability": 0.65, "similarity_boost": 0.80, "style": 0.10},
    "angry":     {"stability": 0.20, "similarity_boost": 0.60, "style": 0.60},
    "tsundere":  {"stability": 0.30, "similarity_boost": 0.70, "style": 0.40},
    "shy":       {"stability": 0.70, "similarity_boost": 0.85, "style": 0.05},
    "surprised": {"stability": 0.25, "similarity_boost": 0.65, "style": 0.45},
    "calm":      {"stability": 0.80, "similarity_boost": 0.85, "style": 0.00},
    "teasing":   {"stability": 0.30, "similarity_boost": 0.70, "style": 0.35},
}

_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class ElevenLabsTTS:
    """
    Config (config.json -> tts.elevenlabs):
      voice_id       : ID da voz (elevenlabs.io/voice-library)
      model_id       : "eleven_flash_v2_5" | "eleven_multilingual_v2"
      output_format  : "mp3_44100_128"
      stability      : 0.5
      similarity_boost: 0.75
      style          : 0.0
    """

    def __init__(self, cfg: dict):
        self.api_key   = (
            os.environ.get("ELEVENLABS_API_KEY", "").strip()
            or cfg.get("api_key", "").strip()
        )
        self.voice_id      = cfg.get("voice_id",        "21m00Tcm4TlvDq8ikWAM")
        self.model_id      = cfg.get("model_id",        "eleven_flash_v2_5")
        self.output_format = cfg.get("output_format",   "mp3_44100_128")
        self.stability     = cfg.get("stability",        0.5)
        self.similarity    = cfg.get("similarity_boost", 0.75)
        self.style         = cfg.get("style",            0.0)

        if not self.api_key:
            logger.warning(
                "[TTS/elevenlabs] API key nao configurada. "
                "Adicione ELEVENLABS_API_KEY ao .env ou tts.elevenlabs.api_key."
            )
        logger.info(f"[TTS/elevenlabs] voice: {self.voice_id} | model: {self.model_id}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        text = tts_preprocess(text)
        if not text.strip():
            return
        if not self.api_key:
            logger.error("[TTS/elevenlabs] API key ausente — configure antes de usar.")
            return

        try:
            import aiohttp
        except ImportError:
            logger.error("[TTS/elevenlabs] Instale: pip install aiohttp")
            return

        ep  = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["default"])
        url = _API_URL.format(voice_id=self.voice_id)

        headers = {
            "xi-api-key":   self.api_key,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }
        payload = {
            "text":     text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability":         ep["stability"],
                "similarity_boost":  ep["similarity_boost"],
                "style":             ep["style"],
                "use_speaker_boost": True,
            },
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers,
                    params={"output_format": self.output_format},
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"[TTS/elevenlabs] HTTP {resp.status}: {body[:300]}")
                        return
                    audio_bytes = await resp.read()

            if not stop_event.is_set():
                await play_bytes(audio_bytes, ".mp3", stop_event)

        except aiohttp.ClientConnectorError:
            logger.error("[TTS/elevenlabs] Falha de conexao. Verifique sua internet.")
        except Exception as e:
            logger.error(f"[TTS/elevenlabs] Erro: {e}")
