"""
recording.py — Gravação de áudio via sounddevice com VAD por RMS.

Sem dependências de ML — usa apenas sounddevice + numpy.
Responsável pela captura do microfone; a transcrição é delegada ao STT service.
"""

import logging
import queue
import threading

import numpy as np

logger = logging.getLogger(__name__)


class Recorder:
    """
    Grava áudio do microfone até detectar silêncio prolongado (RMS VAD).

    Config (config.json -> audio e stt.faster_whisper):
      sample_rate          : 16000
      channels             : 1
      chunk_size           : 1024
      input_device_index   : null (auto)
      silence_threshold_ms : 400
      silence_rms_threshold: 0.015
      max_record_ms        : 30000
    """

    def __init__(self, cfg_audio: dict, cfg_stt: dict | None = None):
        cfg_stt = cfg_stt or {}
        # Pega parâmetros do provider ativo ou usa defaults
        provider_cfg = cfg_stt.get(
            cfg_stt.get("provider", "faster_whisper").replace("-", "_"), {}
        )

        self._sr       = cfg_audio.get("sample_rate",       16000)
        self._channels = cfg_audio.get("channels",          1)
        self._chunk    = cfg_audio.get("chunk_size",        1024)
        self._dev_idx  = cfg_audio.get("input_device_index")

        self._silence_ms  = provider_cfg.get("silence_threshold_ms",  400)
        self._silence_rms = provider_cfg.get("silence_rms_threshold", 0.015)
        self._max_rec_ms  = provider_cfg.get("max_record_ms",         30000)

        self._audio_q  = queue.Queue()
        self._stop_evt = threading.Event()

    # ── API pública ──────────────────────────────────────────────────────────

    def record_until_silence(self) -> np.ndarray:
        """Bloqueia até detectar silêncio ou atingir max_record_ms.
        Retorna array float32 16 kHz pronto para transcrição."""
        import sounddevice as sd

        sr           = self._sr
        silence_smp  = int(sr * self._silence_ms / 1000)
        max_smp      = int(sr * self._max_rec_ms  / 1000)

        frames: list[np.ndarray] = []
        silent_count  = 0
        total_samples = 0
        has_speech    = False

        # Limpa fila de resíduos de gravações anteriores
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

        logger.debug("[Recorder] Gravação iniciada")
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
                if rms >= self._silence_rms:
                    has_speech   = True
                    silent_count = 0
                elif has_speech:
                    silent_count += len(mono)
                    if silent_count >= silence_smp:
                        break

                if total_samples >= max_smp:
                    logger.warning(f"[Recorder] Limite de {self._max_rec_ms}ms atingido.")
                    break

        logger.debug("[Recorder] Gravação encerrada")
        return np.concatenate(frames) if frames else np.zeros(1, dtype="float32")

    def stop_recording(self) -> None:
        self._stop_evt.set()
