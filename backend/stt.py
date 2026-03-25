"""
stt.py — Speech-to-Text local usando faster-whisper
"""

import logging
import queue
import threading
import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

class STTEngine:
    def __init__(self, cfg_stt: dict, cfg_audio: dict):
        self.cfg_stt   = cfg_stt
        self.cfg_audio = cfg_audio
        self.model     = None
        self._audio_q  = queue.Queue()
        self._stop_evt = threading.Event()
        self._load_model()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            model_size   = self.cfg_stt.get("model", "base")
            device       = self.cfg_stt.get("device", "cpu")
            compute_type = self.cfg_stt.get("compute_type", "int8")
            logger.info(f"[STT] Carregando Whisper '{model_size}' em {device}/{compute_type}")
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
            logger.info("[STT] Modelo carregado com sucesso")
        except Exception as e:
            logger.error(f"[STT] Erro ao carregar Whisper: {e}")
            self.model = None

    def record_until_silence(self) -> np.ndarray:
        """
        Grava áudio do microfone até detectar silêncio.
        Retorna array numpy float32 com as amostras.
        """
        sr          = self.cfg_audio.get("sample_rate", 16000)
        channels    = self.cfg_audio.get("channels", 1)
        chunk_size  = self.cfg_audio.get("chunk_size", 1024)
        device      = self.cfg_audio.get("input_device_index")
        silence_ms    = self.cfg_stt.get("silence_threshold_ms", 700)
        silence_smp   = int(sr * silence_ms / 1000)
        silence_rms   = self.cfg_stt.get("silence_rms_threshold", 0.015)
        vad_filter    = self.cfg_stt.get("vad_filter", True)

        frames        = []
        silent_count  = 0
        has_speech    = False
        self._stop_evt.clear()

        def callback(indata, frame_count, time_info, status):
            self._audio_q.put(indata.copy())

        stream = sd.InputStream(
            samplerate=sr,
            channels=channels,
            dtype='float32',
            blocksize=chunk_size,
            device=device,
            callback=callback,
        )

        logger.debug("[STT] Gravação iniciada")
        with stream:
            while not self._stop_evt.is_set():
                try:
                    chunk = self._audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue

                mono = chunk[:, 0] if chunk.ndim > 1 else chunk
                frames.append(mono)

                rms = float(np.sqrt(np.mean(mono ** 2)))
                is_silent = rms < silence_rms

                if not is_silent:
                    has_speech   = True
                    silent_count = 0
                elif has_speech:
                    silent_count += len(mono)
                    if silent_count >= silence_smp:
                        break

        logger.debug("[STT] Gravação encerrada")
        if not frames:
            return np.zeros(1, dtype='float32')
        return np.concatenate(frames)

    def stop_recording(self):
        self._stop_evt.set()

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcreve áudio para texto."""
        if self.model is None:
            return ""
        if len(audio) < 100:
            return ""
        try:
            language    = self.cfg_stt.get("language", "pt")
            vad_filter  = self.cfg_stt.get("vad_filter", True)
            segments, info = self.model.transcribe(
                audio,
                language=language,
                vad_filter=vad_filter,
                beam_size=5,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info(f"[STT] Transcrição: '{text}'")
            return text
        except Exception as e:
            logger.error(f"[STT] Erro na transcrição: {e}")
            return ""
