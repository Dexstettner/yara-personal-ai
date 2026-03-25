"""
tts.py — Multi-engine TTS: chatterbox | edge-tts | voicevox | fish-speech | f5-tts
Troque o provider em config.json → tts.provider

  chatterbox  : clonagem de voz offline (Resemble AI, ~4-7 GB VRAM)
  edge-tts    : vozes neurais Microsoft (requer internet, sem API key)
  voicevox    : vozes anime japonesas (requer VOICEVOX rodando localmente)
  fish-speech : vozes naturais multilíngue (requer Fish Speech server local)
  f5-tts      : flow matching TTS, leve (~300 MB VRAM), clonagem de voz
"""

import asyncio
import logging
import math
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de reprodução via pygame
# ─────────────────────────────────────────────────────────────────────────────

async def _play_file(path: str, stop_event):
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
# Pré-processamento de texto (compartilhado)
# Remove markdown e ações entre asteriscos que TTS leria literalmente
# ─────────────────────────────────────────────────────────────────────────────

_TTS_CLEANUP_MAP = [
    (r'\*\*([^*\n]+)\*\*', r'\1'),   # **bold** → texto
    (r'_([^_\n]+)_',       r'\1'),   # _italic_ → texto
    (r'\*[^*\n]{1,80}\*',  ''),      # *ação* → remove
    (r' {2,}',             ' '),     # espaços duplicados
]

def _tts_preprocess(text: str) -> str:
    for pattern, replacement in _TTS_CLEANUP_MAP:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text.strip()


def _ref_to_wav(reference_audio: str) -> tuple[str | None, bool]:
    """Resolve caminho do áudio de referência.
    Retorna (path, is_temp) — is_temp indica se o arquivo deve ser deletado após uso."""
    root = Path(__file__).parent.parent
    ref  = Path(root / reference_audio)

    if not ref.exists():
        logger.warning(f"[TTS] Referência não encontrada: {ref} — sintetizando sem clonagem")
        return None, False

    if ref.suffix.lower() != ".wav":
        import soundfile as sf
        data, sr = sf.read(str(ref))
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, data, sr)
        return tmp.name, True

    return str(ref), False


# ─────────────────────────────────────────────────────────────────────────────
# Parâmetros de emoção por engine
# ─────────────────────────────────────────────────────────────────────────────

_CHATTERBOX_EMOTION_PARAMS: dict[str, dict] = {
    "default":   {"exaggeration": 0.50, "cfg_weight": 0.50},
    "happy":     {"exaggeration": 0.80, "cfg_weight": 0.40},
    "excited":   {"exaggeration": 1.00, "cfg_weight": 0.30},
    "sad":       {"exaggeration": 0.30, "cfg_weight": 0.60},
    "angry":     {"exaggeration": 1.20, "cfg_weight": 0.30},
    "tsundere":  {"exaggeration": 0.90, "cfg_weight": 0.40},
    "shy":       {"exaggeration": 0.35, "cfg_weight": 0.65},
    "surprised": {"exaggeration": 1.00, "cfg_weight": 0.35},
    "calm":      {"exaggeration": 0.30, "cfg_weight": 0.70},
    "teasing":   {"exaggeration": 0.85, "cfg_weight": 0.40},
}

_F5TTS_EMOTION_SPEED: dict[str, float] = {
    "default":   1.00,
    "happy":     1.10,
    "excited":   1.20,
    "sad":       0.85,
    "angry":     1.05,
    "tsundere":  1.00,
    "shy":       0.90,
    "surprised": 1.10,
    "calm":      0.90,
    "teasing":   1.00,
}


# ─────────────────────────────────────────────────────────────────────────────
# Engine: Chatterbox
# ─────────────────────────────────────────────────────────────────────────────

class _ChatterboxTTS:
    """
    Chatterbox TTS — síntese de voz com clonagem (Resemble AI).
    Modelos baixados automaticamente do HuggingFace (~5 GB no primeiro uso).

    Variantes (config.json → tts.chatterbox.variant):
      turbo        : ~4.5 GB VRAM, mais rápido, clonagem de voz
      standard     : ~6-7 GB VRAM, melhor qualidade, clonagem de voz
      multilingual : ~6-7 GB VRAM, 23+ idiomas (usa language_id: "pt")

    Parâmetros:
      exaggeration : expressividade emocional (0.25–2.0, padrão 0.5)
      cfg_weight   : aderência à voz de referência/ritmo (0.0–1.0, padrão 0.5)
      language_id  : só para variante multilingual (ex: "pt", "en", "ja")

    Instalação (dentro do conda yara):
      pip install chatterbox-tts --no-deps
      pip install resemble-perth conformer diffusers einops
      pip install "transformers<4.50.0"   # necessário após remover indextts
    """

    _VARIANT_IMPORTS = {
        "turbo":        ("chatterbox.tts_turbo", "ChatterboxTurboTTS"),
        "standard":     ("chatterbox.tts",       "ChatterboxTTS"),
        "multilingual": ("chatterbox.mtl_tts",   "ChatterboxMultilingualTTS"),
    }

    def __init__(self, cfg: dict):
        self.device          = cfg.get("device",          "cuda")
        self.reference_audio = cfg.get("reference_audio", "assets/reference_voice.wav")
        self.variant         = cfg.get("variant",         "turbo")
        self.exaggeration    = cfg.get("exaggeration",    0.5)
        self.cfg_weight      = cfg.get("cfg_weight",      0.5)
        self.language_id     = cfg.get("language_id",     "pt")
        self._model          = None
        self._load_error     = None

        logger.info(
            f"[TTS/chatterbox] variant: {self.variant} | device: {self.device} | "
            f"exaggeration: {self.exaggeration} | cfg_weight: {self.cfg_weight}"
        )

    def _ensure_model(self):
        if self._model is not None:
            return
        if self._load_error is not None:
            raise RuntimeError(
                f"Carregamento anterior falhou: {self._load_error}\n"
                "  Corrija o problema e reinicie o backend."
            )

        import torch
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("[TTS/chatterbox] CUDA não disponível — usando CPU.")
            self.device = "cpu"

        if self.variant not in self._VARIANT_IMPORTS:
            logger.warning(f"[TTS/chatterbox] Variante '{self.variant}' inválida — usando turbo.")
            self.variant = "turbo"

        module_path, cls_name = self._VARIANT_IMPORTS[self.variant]
        try:
            import importlib
            cls = getattr(importlib.import_module(module_path), cls_name)
            self._model = cls.from_pretrained(device=self.device)
        except Exception as e:
            self._load_error = str(e)
            raise
        logger.info(f"[TTS/chatterbox] Modelo '{self.variant}' carregado em {self.device}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default"):
        text = _tts_preprocess(text)
        if not text.strip():
            return

        ep = _CHATTERBOX_EMOTION_PARAMS.get(emotion, _CHATTERBOX_EMOTION_PARAMS["default"])
        ref_path, ref_is_tmp = _ref_to_wav(self.reference_audio)
        tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_out.close()

        try:
            await asyncio.to_thread(self._ensure_model)
            if stop_event.is_set():
                return

            def _gen():
                import torchaudio
                kwargs = {
                    "text":         text,
                    "exaggeration": ep["exaggeration"],
                    "cfg_weight":   ep["cfg_weight"],
                }
                if ref_path:
                    kwargs["audio_prompt_path"] = ref_path
                if self.variant == "multilingual":
                    kwargs["language_id"] = self.language_id

                wav = self._model.generate(**kwargs)
                torchaudio.save(tmp_out.name, wav, self._model.sr)

            await asyncio.to_thread(_gen)

            if not stop_event.is_set():
                await _play_file(tmp_out.name, stop_event)

        except Exception as e:
            logger.error(f"[TTS/chatterbox] Erro: {e}")
        finally:
            for path, should_delete in [(tmp_out.name, True), (ref_path, ref_is_tmp)]:
                if should_delete and path and os.path.exists(path):
                    try:
                        os.remove(path)
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

    async def speak_async(self, text: str, stop_event, emotion: str = "default"):
        import edge_tts

        text = _tts_preprocess(text)
        tmp  = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
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

    async def speak_async(self, text: str, stop_event, emotion: str = "default"):
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
        self.reference_id = cfg.get("reference_id")
        self.format       = "wav"
        logger.info(f"[TTS/fish-speech] host: {self.host}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default"):
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
# Engine: F5-TTS
# ─────────────────────────────────────────────────────────────────────────────

class _F5TTS:
    """
    F5-TTS — flow matching TTS com clonagem de voz (~300 MB VRAM).

    Instalação (dentro do conda yara):
      pip install f5-tts

    Parâmetros em config.json → tts.f5_tts:
      device         : "cuda" ou "cpu"
      reference_audio: caminho para .wav de referência
      ref_text       : transcrição do áudio de referência (vazio = auto-detecta)
      model          : "F5TTS_v1_Base" (padrão)
      speed          : fator de velocidade base (padrão 1.0)
    """

    def __init__(self, cfg: dict):
        self.device          = cfg.get("device",          "cuda")
        self.reference_audio = cfg.get("reference_audio", "assets/reference_voice.wav")
        self.ref_text        = cfg.get("ref_text",        "")
        self.model_name      = cfg.get("model",           "F5TTS_v1_Base")
        self.speed           = cfg.get("speed",           1.0)
        self._model          = None
        self._load_error     = None

        logger.info(f"[TTS/f5-tts] model: {self.model_name} | device: {self.device}")

    def _ensure_model(self):
        if self._model is not None:
            return
        if self._load_error is not None:
            raise RuntimeError(
                f"Carregamento anterior falhou: {self._load_error}\n"
                "  Corrija o problema e reinicie o backend."
            )

        import torch
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("[TTS/f5-tts] CUDA não disponível — usando CPU.")
            self.device = "cpu"

        try:
            from f5_tts.api import F5TTS
            self._model = F5TTS(model=self.model_name, device=self.device)
        except Exception as e:
            self._load_error = str(e)
            raise
        logger.info(f"[TTS/f5-tts] Modelo '{self.model_name}' carregado em {self.device}")

    def _get_ref(self) -> tuple[str | None, bool]:
        ref_path, ref_is_tmp = _ref_to_wav(self.reference_audio)
        if not ref_path:
            logger.error(
                "[TTS/f5-tts] reference_audio não encontrado — F5-TTS exige ref_file. "
                "Configure tts.f5_tts.reference_audio com um .wav válido."
            )
        return ref_path, ref_is_tmp

    def _infer_one(self, text: str, emotion: str, ref_path: str):
        """Sintetiza um trecho e retorna (wav_array, sample_rate).
        Deve ser chamado dentro de asyncio.to_thread."""
        speed = _F5TTS_EMOTION_SPEED.get(emotion, 1.0) * self.speed
        kwargs: dict = {
            "ref_file":       ref_path,
            "gen_text":       text,
            "speed":          speed,
            "remove_silence": True,
        }
        if self.ref_text:
            kwargs["ref_text"] = self.ref_text
        wav, sr, _ = self._model.infer(**kwargs)
        return wav, sr

    async def speak_async(self, text: str, stop_event, emotion: str = "default"):
        text = _tts_preprocess(text)
        if not text.strip():
            return

        ref_path, ref_is_tmp = self._get_ref()
        if not ref_path:
            return

        tmp_path = None
        try:
            await asyncio.to_thread(self._ensure_model)
            if stop_event.is_set():
                return

            def _gen():
                import soundfile as sf
                wav, sr = self._infer_one(text, emotion, ref_path)
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                sf.write(tmp.name, wav, sr)
                return tmp.name

            tmp_path = await asyncio.to_thread(_gen)

            if not stop_event.is_set():
                await _play_file(tmp_path, stop_event)

        except Exception as e:
            logger.error(f"[TTS/f5-tts] Erro: {e}")
        finally:
            for path, should_delete in [(tmp_path, True), (ref_path, ref_is_tmp)]:
                if should_delete and path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    async def speak_segments_async(
        self, segments: list[tuple[str, str]], stop_event
    ):
        """Sintetiza todos os segmentos, concatena e reproduz de uma vez."""
        ref_path, ref_is_tmp = self._get_ref()
        if not ref_path:
            return

        tmp_path = None
        try:
            await asyncio.to_thread(self._ensure_model)
            if stop_event.is_set():
                return

            def _gen_all():
                import numpy as np
                import soundfile as sf
                all_wavs = []
                sr_out = None
                for emotion, text in segments:
                    text = _tts_preprocess(text)
                    if not text.strip():
                        continue
                    wav, sr = self._infer_one(text, emotion, ref_path)
                    all_wavs.append(wav)
                    sr_out = sr
                if not all_wavs:
                    return None
                combined = np.concatenate(all_wavs) if len(all_wavs) > 1 else all_wavs[0]
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                sf.write(tmp.name, combined, sr_out)
                return tmp.name

            tmp_path = await asyncio.to_thread(_gen_all)

            if tmp_path and not stop_event.is_set():
                await _play_file(tmp_path, stop_event)

        except Exception as e:
            logger.error(f"[TTS/f5-tts] Erro nos segmentos: {e}")
        finally:
            for path, should_delete in [(tmp_path, True), (ref_path, ref_is_tmp)]:
                if should_delete and path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass


# ─────────────────────────────────────────────────────────────────────────────
# TTSEngine — fachada pública
# ─────────────────────────────────────────────────────────────────────────────

_ENGINES = {
    "chatterbox":  (_ChatterboxTTS, "chatterbox"),
    "edge-tts":    (_EdgeTTS,       "edge_tts"),
    "voicevox":    (_VoiceVox,      "voicevox"),
    "fish-speech": (_FishSpeech,    "fish_speech"),
    "f5-tts":      (_F5TTS,        "f5_tts"),
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

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        await self._engine.speak_async(text, stop_event, emotion=emotion)

    async def speak_segments_async(
        self, segments: list[tuple[str, str]], stop_event
    ) -> None:
        """Sintetiza e reproduz segmentos.
        Engines que implementam speak_segments_async próprio (ex: F5-TTS)
        sintetizam em batch e concatenam antes de reproduzir.
        Os demais reproduzem segmento a segmento."""
        if hasattr(self._engine, "speak_segments_async"):
            await self._engine.speak_segments_async(segments, stop_event)
        else:
            for emotion, text in segments:
                if stop_event.is_set():
                    break
                await self._engine.speak_async(text, stop_event, emotion=emotion)

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
