"""
tts/f5_tts.py — Provider TTS: F5-TTS (flow matching, ~300 MB VRAM, clonagem de voz).

Instalacao:
  pip install f5-tts
"""

import asyncio
import logging
import os
import tempfile

from ._common import play_file, ref_to_wav, split_sentences, tts_preprocess

logger = logging.getLogger(__name__)

EMOTION_SPEED: dict[str, float] = {
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


class F5TTS:
    """
    F5-TTS — flow matching TTS com clonagem de voz.

    Config (config.json -> tts.f5_tts):
      device         : "cuda" | "cpu"
      reference_audio: caminho para .wav de referencia
      ref_text       : transcricao do audio de referencia (vazio = auto-detecta)
      model          : "F5TTS_v1_Base"
      speed          : fator de velocidade base (1.0)
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
            logger.warning("[TTS/f5-tts] CUDA nao disponivel — usando CPU.")
            self.device = "cpu"

        try:
            from f5_tts.api import F5TTS as _F5TTS
            self._model = _F5TTS(model=self.model_name, device=self.device)
        except Exception as e:
            self._load_error = str(e)
            raise
        logger.info(f"[TTS/f5-tts] Modelo '{self.model_name}' carregado em {self.device}")

    def _get_ref(self) -> tuple[str | None, bool]:
        ref_path, ref_is_tmp = ref_to_wav(self.reference_audio)
        if not ref_path:
            logger.error(
                "[TTS/f5-tts] reference_audio nao encontrado — F5-TTS exige ref_file. "
                "Configure tts.f5_tts.reference_audio com um .wav valido."
            )
        return ref_path, ref_is_tmp

    def _infer_one(self, text: str, emotion: str, ref_path: str):
        """Sintetiza um trecho e retorna (wav_array, sample_rate)."""
        speed = EMOTION_SPEED.get(emotion, 1.0) * self.speed
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

    async def speak_async(self, text: str, stop_event, emotion: str = "default") -> None:
        text = tts_preprocess(text)
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
                import numpy as np
                import soundfile as sf
                sentences = split_sentences(text)
                wavs      = [self._infer_one(s, emotion, ref_path) for s in sentences]
                combined  = np.concatenate([w for w, _ in wavs]) if len(wavs) > 1 else wavs[0][0]
                sr        = wavs[0][1]
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                sf.write(tmp.name, combined, sr)
                return tmp.name

            tmp_path = await asyncio.to_thread(_gen)
            if not stop_event.is_set():
                await play_file(tmp_path, stop_event)

        except Exception as e:
            logger.error(f"[TTS/f5-tts] Erro: {e}")
        finally:
            for path, should_del in [(tmp_path, True), (ref_path, ref_is_tmp)]:
                if should_del and path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass

    async def speak_segments_async(
        self, segments: list[tuple[str, str]], stop_event
    ) -> None:
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
                sr_out   = None
                for emotion, seg_text in segments:
                    seg_text = tts_preprocess(seg_text)
                    if not seg_text.strip():
                        continue
                    for sentence in split_sentences(seg_text):
                        wav, sr = self._infer_one(sentence, emotion, ref_path)
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
                await play_file(tmp_path, stop_event)

        except Exception as e:
            logger.error(f"[TTS/f5-tts] Erro nos segmentos: {e}")
        finally:
            for path, should_del in [(tmp_path, True), (ref_path, ref_is_tmp)]:
                if should_del and path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
