"""
tts/kokoro.py — Provider TTS: Kokoro-ONNX (preset) + KokoClone server (clonagem).

Dois modos de operação:
  1. Preset  — kokoro-onnx local com voz pré-treinada (padrão, sem servidor extra)
  2. Clone   — POST para o servidor KokoClone quando `clone_server` está configurado
               O servidor roda em Python 3.12 separado: python kokoclone/server.py

Instalação (modo preset):
  pip install kokoro-onnx soundfile

Instalação (modo clone, ambiente separado):
  conda create -n kokoclone python=3.12
  conda activate kokoclone
  pip install git+https://github.com/Ashish-Patnaik/kokoclone.git fastapi uvicorn soundfile

Vozes preset (lang="pt" pode exigir kokoro-onnx >= 0.5.0):
  pf_dora    — feminino português
  af_bella, af_sarah, af_nicole, af_sky  — feminino americano
  am_adam, am_michael                    — masculino americano
  bf_emma, bf_isabella                   — feminino britânico
"""

import asyncio
import logging
import os
import tempfile

from ._common import play_bytes, play_file, tts_preprocess

logger = logging.getLogger(__name__)

_SPEED_MAP: dict[str, float] = {
    "excited":   1.15,
    "happy":     1.05,
    "teasing":   1.10,
    "tsundere":  1.05,
    "angry":     1.10,
    "surprised": 1.10,
    "sad":       0.90,
    "shy":       0.90,
    "calm":      0.85,
    "default":   1.00,
}


class KokoroTTS:
    """
    Config (config.json -> tts.kokoro):
      voice        : "pf_dora"               — voz preset (modo local)
      speed        : 1.0                     — velocidade base
      lang         : "pt"                    — idioma (modo preset)
      clone_server : "http://localhost:8010"  — ativa modo clone (opcional)
    """

    def __init__(self, cfg: dict):
        self.voice        = cfg.get("voice",        "pf_dora")
        self.speed        = cfg.get("speed",        1.0)
        self.lang         = cfg.get("lang",         "pt")
        self.clone_server = cfg.get("clone_server", "").rstrip("/")

        self._kokoro = None  # instância kokoro-onnx (modo preset)

        if self.clone_server:
            logger.info(f"[TTS/kokoro] modo: clone | servidor: {self.clone_server}")
        else:
            logger.info(f"[TTS/kokoro] modo: preset | voz: {self.voice} | lang: {self.lang}")

    # ── Modo preset ───────────────────────────────────────────────────────────

    def _ensure_local(self) -> None:
        if self._kokoro is not None:
            return
        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            logger.error("[TTS/kokoro] Instale: pip install kokoro-onnx soundfile")
            raise

        import urllib.request
        from pathlib import Path

        cache_dir = Path.home() / ".cache" / "kokoro-onnx"
        cache_dir.mkdir(parents=True, exist_ok=True)

        model_path  = cache_dir / "kokoro-v0_19.onnx"
        voices_path = cache_dir / "voices-v1_0.bin"

        base_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

        for fname, fpath in [("kokoro-v0_19.onnx", model_path), ("voices-v1_0.bin", voices_path)]:
            if not fpath.exists():
                logger.info(f"[TTS/kokoro] baixando {fname}...")
                try:
                    urllib.request.urlretrieve(f"{base_url}/{fname}", str(fpath))
                except Exception as e:
                    logger.error(f"[TTS/kokoro] Falha ao baixar {fname}: {e}")
                    raise RuntimeError(f"Não foi possível baixar {fname}") from e

        logger.info("[TTS/kokoro] carregando kokoro-onnx...")
        self._kokoro = Kokoro(str(model_path), str(voices_path))
        logger.info("[TTS/kokoro] kokoro-onnx carregado")

    def _synthesize_local(self, text: str, speed: float):
        return self._kokoro.create(text, voice=self.voice, speed=speed, lang=self.lang)

    # ── Modo clone (servidor KokoClone) ───────────────────────────────────────

    async def _synthesize_clone(self, text: str, speed: float) -> bytes | None:
        try:
            import aiohttp
        except ImportError:
            logger.error("[TTS/kokoro] Instale: pip install aiohttp")
            return None

        url = f"{self.clone_server}/tts"
        payload = {"text": text, "speed": speed}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"[TTS/kokoro] servidor retornou {resp.status}: {body[:200]}")
                        return None
                    return await resp.read()
        except aiohttp.ClientConnectorError:
            logger.error(
                f"[TTS/kokoro] Servidor KokoClone não acessível em {self.clone_server}.\n"
                "  Inicie com: kokoclone\\start.bat"
            )
            return None
        except Exception as e:
            logger.error(f"[TTS/kokoro] Erro ao chamar servidor clone: {e}")
            return None

    # ── Interface pública ─────────────────────────────────────────────────────

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        text = tts_preprocess(text)
        if not text.strip():
            return

        speed = self.speed * _SPEED_MAP.get(emotion, 1.0)

        if self.clone_server:
            # ── modo clone: delega ao servidor KokoClone ──
            audio_bytes = await self._synthesize_clone(text, speed)
            if audio_bytes and not stop_event.is_set():
                await play_bytes(audio_bytes, ".wav", stop_event)
        else:
            # ── modo preset: kokoro-onnx local ──
            try:
                await asyncio.to_thread(self._ensure_local)
            except Exception as e:
                logger.error(f"[TTS/kokoro] Falha ao carregar modelo: {e}")
                return

            try:
                import soundfile as sf

                samples, sample_rate = await asyncio.to_thread(
                    self._synthesize_local, text, speed
                )
                if samples is None or stop_event.is_set():
                    return

                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                try:
                    await asyncio.to_thread(sf.write, tmp.name, samples, sample_rate)
                    await play_file(tmp.name, stop_event)
                finally:
                    try:
                        os.remove(tmp.name)
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"[TTS/kokoro] Erro na síntese: {e}")
