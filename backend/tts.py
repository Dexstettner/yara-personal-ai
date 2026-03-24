"""
tts.py — Multi-engine TTS: edge-tts | voicevox | fish-speech
Troque o provider em config.json → tts.provider

  edge-tts    : vozes neurais Microsoft (requer internet, sem API key)
  voicevox    : vozes anime japonesas (requer VOICEVOX rodando localmente)
  fish-speech : vozes naturais multilíngue (requer Fish Speech server local)
"""

import asyncio
import logging
import math
import os
import re
import tempfile

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de reprodução via pygame
# ─────────────────────────────────────────────────────────────────────────────

async def _play_file(path: str, stop_event, suffix: str = ""):
    """Reproduz arquivo de áudio (mp3/wav) via pygame e aguarda terminar."""
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


async def _play_bytes(data: bytes, suffix: str, stop_event):
    """Salva bytes em arquivo temporário e reproduz."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    try:
        await _play_file(tmp.name, stop_event)
    finally:
        if os.path.exists(tmp.name):
            try:
                os.remove(tmp.name)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Engine: edge-tts
# ─────────────────────────────────────────────────────────────────────────────

class _EdgeTTS:
    """
    Vozes neurais da Microsoft via Edge (gratuito, requer internet).
    Vozes PT-BR:
      pt-BR-ThalitaNeural   — feminino, jovem/casual  ← padrão
      pt-BR-FranciscaNeural — feminino, profissional
      pt-BR-AntonioNeural   — masculino
    """

    def __init__(self, cfg: dict):
        self.voice  = cfg.get("voice",      "pt-BR-ThalitaNeural")
        self.rate   = cfg.get("rate_pct",   "+0%")
        self.volume = cfg.get("volume_pct", "+0%")
        logger.info(f"[TTS/edge-tts] voz: {self.voice}")

    async def speak_async(self, text: str, stop_event):
        import edge_tts

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            communicate = edge_tts.Communicate(
                text, self.voice,
                rate=self.rate, volume=self.volume
            )
            await communicate.save(tmp.name)
            if not stop_event.is_set():
                await _play_file(tmp.name, stop_event)
        except Exception as e:
            logger.error(f"[TTS/edge-tts] Erro: {e}")
        finally:
            if os.path.exists(tmp.name):
                try:
                    os.remove(tmp.name)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# Engine: VOICEVOX
# ─────────────────────────────────────────────────────────────────────────────

class _VoiceVox:
    """
    Vozes anime japonesas via VOICEVOX Engine (local, gratuito, offline).
    Instale: https://voicevox.hiroshiba.jp/
    O VOICEVOX deve estar rodando antes de iniciar o assistente.

    Speakers populares:
      1  — Shikoku Metan (normal)
      2  — Zundamon (normal)     ← padrão
      3  — Zundamon (amaama)
      8  — Shikoku Metan (sasayaki)
      13 — Kasukabe Tsumugi
    Lista completa: GET http://localhost:50021/speakers
    """

    def __init__(self, cfg: dict):
        self._lock = asyncio.Lock()
        self.host       = cfg.get("host",       "http://localhost:50021")
        self.speaker_id = cfg.get("speaker_id", 2)
        self.speed      = cfg.get("speed",      1.0)
        self.pitch      = cfg.get("pitch",      0.0)
        self.intonation = cfg.get("intonation", 1.0)
        self.volume     = cfg.get("volume",     1.0)
        logger.info(f"[TTS/voicevox] host: {self.host} | speaker: {self.speaker_id}")

    async def speak_async(self, text: str, stop_event):
        async with self._lock:
            try:
                import aiohttp
            except ImportError:
                logger.error("[TTS/voicevox] Instale: pip install aiohttp")
                return

            try:
                async with aiohttp.ClientSession() as session:
                    # 1. Gera parâmetros de áudio
                    async with session.post(
                        f"{self.host}/audio_query",
                        params={"text": text, "speaker": self.speaker_id},
                        headers={"Connection": "close"}
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"[TTS/voicevox] audio_query HTTP {resp.status}")
                            logger.warning("Certifique-se que o VOICEVOX está aberto.")
                            return
                        query = await resp.json()

                    query["speedScale"]      = self.speed
                    query["pitchScale"]      = self.pitch
                    query["intonationScale"] = self.intonation
                    query["volumeScale"]     = self.volume

                    # 2. Síntese
                    async with session.post(
                        f"{self.host}/synthesis",
                        params={"speaker": self.speaker_id},
                        json=query,
                        headers={"Connection": "close"}
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"[TTS/voicevox] synthesis HTTP {resp.status}")
                            return
                        wav_bytes = await resp.read()

                if not stop_event.is_set():
                    await _play_bytes(wav_bytes, ".wav", stop_event)

            except aiohttp.ClientConnectorError:
                logger.error("[TTS/voicevox] Não foi possível conectar. VOICEVOX está rodando?")
            except Exception as e:
                logger.error(f"[TTS/voicevox] Erro: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Engine: Fish Speech
# ─────────────────────────────────────────────────────────────────────────────

class _FishSpeech:
    """
    Vozes naturais multilíngue via Fish Speech (local, gratuito, offline).
    Instale/inicie o servidor: https://github.com/fishaudio/fish-speech
    Comando para iniciar: uvicorn tools.api_server:app --host 0.0.0.0 --port 50021

    reference_id: ID de uma voz clonada (deixe null para voz padrão).
    """

    def __init__(self, cfg: dict):
        self.host         = cfg.get("host",         "http://localhost:50021")
        self.reference_id = cfg.get("reference_id") # None = voz padrão
        self.format       = "wav"
        logger.info(f"[TTS/fish-speech] host: {self.host}")

    async def speak_async(self, text: str, stop_event):
        try:
            import aiohttp
        except ImportError:
            logger.error("[TTS/fish-speech] Instale: pip install aiohttp")
            return

        payload = {
            "text":      text,
            "format":    self.format,
            "streaming": False,
        }
        if self.reference_id:
            payload["reference_id"] = self.reference_id

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.host}/v1/tts", json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"[TTS/fish-speech] TTS HTTP {resp.status}")
                        logger.warning("Certifique-se que o Fish Speech server está rodando.")
                        return
                    audio_bytes = await resp.read()

            if not stop_event.is_set():
                await _play_bytes(audio_bytes, ".wav", stop_event)

        except aiohttp.ClientConnectorError:
            logger.error("[TTS/fish-speech] Não foi possível conectar. Servidor rodando?")
        except Exception as e:
            logger.error(f"[TTS/fish-speech] Erro: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TTSEngine — fachada pública
# ─────────────────────────────────────────────────────────────────────────────

_ENGINES = {
    "edge-tts":    (_EdgeTTS,    "edge_tts"),
    "voicevox":    (_VoiceVox,   "voicevox"),
    "fish-speech": (_FishSpeech, "fish_speech"),
}


class TTSEngine:
    def __init__(self, cfg: dict):
        self.cfg      = cfg
        self.provider = cfg.get("provider", "edge-tts").lower()
        self._init_mixer()

        if self.provider not in _ENGINES:
            logger.error(
                f"[TTS] Provider '{self.provider}' inválido. "
                f"Opções: {', '.join(_ENGINES)}. Usando edge-tts."
            )
            self.provider = "edge-tts"

        engine_cls, cfg_key = _ENGINES[self.provider]
        self._engine = engine_cls(cfg.get(cfg_key, {}))

    def _init_mixer(self):
        try:
            import pygame
            pygame.mixer.pre_init(44100, -16, 2, 1024)
            pygame.mixer.init()
            logger.info("[TTS] pygame mixer inicializado")
        except Exception as e:
            logger.error(f"[TTS] Erro ao inicializar pygame: {e}")

    async def speak_async(self, text: str, stop_event) -> None:
        await self._engine.speak_async(text, stop_event)

    def stop(self):
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def estimate_lip_sync(self, text: str, n_frames: int = 40) -> list[float]:
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
