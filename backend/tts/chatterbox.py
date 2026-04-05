"""
tts/chatterbox.py — Provider TTS: Chatterbox (clonagem de voz offline, ~4-7 GB VRAM).

Instalacao (conda yara):
  1. conda install -c conda-forge pynini
  2. pip install chatterbox-tts --no-deps
  3. pip install resemble-perth conformer diffusers einops "transformers<4.50.0"

CONFLITO: nao instale chatterbox e f5-tts na mesma env (conflito transformers).
"""

import asyncio
import importlib
import logging
import os
import tempfile

from ._common import play_file, ref_to_wav, tts_preprocess

logger = logging.getLogger(__name__)

EMOTION_PARAMS: dict[str, dict] = {
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

_VARIANT_IMPORTS = {
    "turbo":        ("chatterbox.tts_turbo", "ChatterboxTurboTTS"),
    "standard":     ("chatterbox.tts",       "ChatterboxTTS"),
    "multilingual": ("chatterbox.mtl_tts",   "ChatterboxMultilingualTTS"),
}


class ChatterboxTTS:
    """
    Chatterbox TTS — sintese de voz com clonagem (Resemble AI).

    Config (config.json -> tts.chatterbox):
      device         : "cuda" | "cpu"
      reference_audio: "backend/assets/reference_voice.wav"
      variant        : "turbo" | "standard" | "multilingual"
      exaggeration   : 0.5
      cfg_weight     : 0.5
      language_id    : "pt"  (so para variante multilingual)
    """

    def __init__(self, cfg: dict):
        self.device          = cfg.get("device",          "cuda")
        self.reference_audio = cfg.get("reference_audio", "backend/assets/reference_voice.wav")
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

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        if self._load_error is not None:
            raise RuntimeError(
                f"Carregamento anterior falhou: {self._load_error}\n"
                "  Corrija o problema e reinicie o backend."
            )

        import torch
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("[TTS/chatterbox] CUDA nao disponivel — usando CPU.")
            self.device = "cpu"

        if self.variant not in _VARIANT_IMPORTS:
            logger.warning(f"[TTS/chatterbox] Variante '{self.variant}' invalida — usando turbo.")
            self.variant = "turbo"

        module_path, cls_name = _VARIANT_IMPORTS[self.variant]
        try:
            cls = getattr(importlib.import_module(module_path), cls_name)
            self._model = cls.from_pretrained(device=self.device)
        except Exception as e:
            self._load_error = str(e)
            raise
        logger.info(f"[TTS/chatterbox] Modelo '{self.variant}' carregado em {self.device}")

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        text = tts_preprocess(text)
        if not text.strip():
            return

        ep = EMOTION_PARAMS.get(emotion, EMOTION_PARAMS["default"])
        ref_path, ref_is_tmp = ref_to_wav(self.reference_audio)
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
                await play_file(tmp_out.name, stop_event)

        except Exception as e:
            logger.error(f"[TTS/chatterbox] Erro: {e}")
        finally:
            for path, should_del in [(tmp_out.name, True), (ref_path, ref_is_tmp)]:
                if should_del and path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
