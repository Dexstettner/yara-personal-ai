"""
stt/faster_whisper.py — Provider STT: VAD por RMS + faster-whisper (CTranslate2).
Nao requer torch.
"""

import logging
import queue
import threading

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class FasterWhisperSTT:
    """
    Grava com VAD por RMS e transcreve em batch via faster-whisper (CTranslate2).

    Config (config.json -> stt.faster_whisper):
      model                     : "large-v3-turbo" | "medium" | "small" | "base"
      device                    : "cpu" | "cuda"
      compute_type              : "int8" | "float16" | "float32"
      beam_size                 : 1  (greedy) a 5 (qualidade maxima)
      language                  : "pt"
      vad_filter                : true  (silero interno do faster-whisper)
      condition_on_previous_text: false
      silence_threshold_ms      : 400
      silence_rms_threshold     : 0.015
      max_record_ms             : 30000
    """

    def __init__(self, cfg: dict, cfg_audio: dict):
        self.model_size   = cfg.get("model",                      "large-v3-turbo")
        self.device       = cfg.get("device",                     "cpu")
        self.compute_type = cfg.get("compute_type",               "int8")
        self.beam_size    = cfg.get("beam_size",                  1)
        self.language     = cfg.get("language",                   "pt")
        self.vad_filter   = cfg.get("vad_filter",                 True)
        self.cond_prev    = cfg.get("condition_on_previous_text", False)
        self.silence_ms   = cfg.get("silence_threshold_ms",       400)
        self.silence_rms  = cfg.get("silence_rms_threshold",      0.015)
        self.max_rec_ms   = cfg.get("max_record_ms",              30000)

        self._sr       = cfg_audio.get("sample_rate",      16000)
        self._channels = cfg_audio.get("channels",         1)
        self._chunk    = cfg_audio.get("chunk_size",       1024)
        self._dev_idx  = cfg_audio.get("input_device_index")

        self._model      = None
        self._load_error = None
        self._lock       = threading.Lock()
        self._audio_q    = queue.Queue()
        self._stop_evt   = threading.Event()

        threading.Thread(target=self._ensure_model, daemon=True).start()

    def _ensure_model(self) -> None:
        with self._lock:
            if self._model is not None or self._load_error is not None:
                return
            try:
                from faster_whisper import WhisperModel
                logger.info(
                    f"[STT/faster-whisper] Carregando '{self.model_size}' "
                    f"em {self.device}/{self.compute_type}"
                )
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                logger.info("[STT/faster-whisper] Modelo carregado")
            except Exception as e:
                self._load_error = str(e)
                logger.error(f"[STT/faster-whisper] Erro ao carregar modelo: {e}")

    @property
    def model(self):
        return self._model

    def record_until_silence(self) -> np.ndarray:
        sr          = self._sr
        silence_smp = int(sr * self.silence_ms / 1000)
        max_smp     = int(sr * self.max_rec_ms  / 1000)

        frames: list[np.ndarray] = []
        silent_count  = 0
        total_samples = 0
        has_speech    = False

        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                break
        self._stop_evt.clear()

        def _cb(indata, _frames, _time, _status):
            self._audio_q.put(indata.copy())

        stream = sd.InputStream(
            samplerate=sr,
            channels=self._channels,
            dtype="float32",
            blocksize=self._chunk,
            device=self._dev_idx,
            callback=_cb,
        )

        logger.debug("[STT/faster-whisper] Gravacao iniciada")
        with stream:
            while not self._stop_evt.is_set():
                try:
                    chunk = self._audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue

                mono = chunk[:, 0] if chunk.ndim > 1 else chunk.flatten()
                frames.append(mono)
                total_samples += len(mono)

                rms = float(np.sqrt(np.mean(mono ** 2)))
                if rms >= self.silence_rms:
                    has_speech   = True
                    silent_count = 0
                elif has_speech:
                    silent_count += len(mono)
                    if silent_count >= silence_smp:
                        break

                if total_samples >= max_smp:
                    logger.warning(
                        f"[STT/faster-whisper] Limite de {self.max_rec_ms}ms atingido."
                    )
                    break

        logger.debug("[STT/faster-whisper] Gravacao encerrada")
        return np.concatenate(frames) if frames else np.zeros(1, dtype="float32")

    def stop_recording(self) -> None:
        self._stop_evt.set()

    def transcribe(self, audio: np.ndarray) -> str:
        if self._load_error:
            logger.error(f"[STT/faster-whisper] Modelo nao carregou: {self._load_error}")
            return ""
        if self._model is None:
            logger.warning("[STT/faster-whisper] Modelo ainda carregando...")
            return ""
        if len(audio) < 100:
            return ""
        try:
            segments, _ = self._model.transcribe(
                audio,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                condition_on_previous_text=self.cond_prev,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info(f"[STT/faster-whisper] '{text}'")
            return text
        except Exception as e:
            logger.error(f"[STT/faster-whisper] Erro na transcricao: {e}")
            return ""
