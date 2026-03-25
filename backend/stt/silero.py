"""
stt/silero.py — Provider STT: VAD neural silero-vad + faster-whisper.

Requer: pip install silero-vad onnxruntime faster-whisper
"""

import logging
import queue
import threading

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class SileroSTT:
    """
    Grava com VAD neural silero (robusto a ruido) e transcreve via faster-whisper.

    Diferencas vs faster-whisper provider:
      - Deteccao de fala por probabilidade neural (nao por RMS fixo)
      - Nao sensivel ao ganho do microfone
      - Lida melhor com vozes baixas, sotaques e ruido de fundo

    Config (config.json -> stt.silero):
      model         : "large-v3-turbo" | "medium" | etc. (whisper para transcricao)
      device        : "cpu" | "cuda"
      compute_type  : "int8" | "float16"
      beam_size     : 1
      language      : "pt"
      vad_threshold : 0.5   (0.0-1.0 — menor = mais sensivel)
      min_silence_ms: 500   (silencio minimo para encerrar fala)
      max_record_ms : 30000
    """

    # silero-vad exige exatamente 512 amostras por chunk a 16 kHz (32 ms)
    _VAD_CHUNK = 512
    _VAD_SR    = 16000

    def __init__(self, cfg: dict, cfg_audio: dict):
        self.model_size    = cfg.get("model",          "large-v3-turbo")
        self.device        = cfg.get("device",         "cpu")
        self.compute_type  = cfg.get("compute_type",   "int8")
        self.beam_size     = cfg.get("beam_size",      1)
        self.language      = cfg.get("language",       "pt")
        self.vad_threshold = cfg.get("vad_threshold",  0.5)
        self.min_sil_ms    = cfg.get("min_silence_ms", 500)
        self.max_rec_ms    = cfg.get("max_record_ms",  30000)
        self._dev_idx      = cfg_audio.get("input_device_index")

        self._whisper_model = None
        self._vad_model     = None
        self._whisper_error = None
        self._vad_error     = None
        self._whisper_lock  = threading.Lock()
        self._vad_lock      = threading.Lock()
        self._audio_q       = queue.Queue()
        self._stop_evt      = threading.Event()

        threading.Thread(target=self._ensure_whisper, daemon=True).start()
        threading.Thread(target=self._ensure_vad,     daemon=True).start()

    # ── Whisper ──────────────────────────────────────────────────────────────

    def _ensure_whisper(self) -> None:
        with self._whisper_lock:
            if self._whisper_model is not None or self._whisper_error is not None:
                return
            try:
                from faster_whisper import WhisperModel
                logger.info(
                    f"[STT/silero] Carregando Whisper '{self.model_size}' "
                    f"em {self.device}/{self.compute_type}"
                )
                self._whisper_model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                logger.info("[STT/silero] Whisper carregado")
            except Exception as e:
                self._whisper_error = str(e)
                logger.error(f"[STT/silero] Erro ao carregar Whisper: {e}")

    @property
    def model(self):
        return self._whisper_model

    # ── silero-vad ───────────────────────────────────────────────────────────

    def _ensure_vad(self) -> None:
        with self._vad_lock:
            if self._vad_model is not None or self._vad_error is not None:
                return
            try:
                from silero_vad import load_silero_vad
                logger.info("[STT/silero] Carregando silero-vad...")
                self._vad_model = load_silero_vad()
                logger.info("[STT/silero] silero-vad carregado")
            except ImportError:
                self._vad_error = "silero-vad nao instalado"
                logger.error(
                    "[STT/silero] silero-vad nao instalado. "
                    "Execute: pip install silero-vad onnxruntime"
                )
            except Exception as e:
                self._vad_error = str(e)
                logger.error(f"[STT/silero] Erro ao carregar silero-vad: {e}")

    # ── Gravacao ──────────────────────────────────────────────────────────────

    def record_until_silence(self) -> np.ndarray:
        if self._vad_error:
            logger.error(f"[STT/silero] VAD nao disponivel: {self._vad_error}")
            return np.zeros(1, dtype="float32")
        if self._vad_model is None:
            logger.warning("[STT/silero] VAD ainda carregando, aguardando...")
            self._vad_lock.acquire()
            self._vad_lock.release()
            if self._vad_model is None:
                return np.zeros(1, dtype="float32")

        try:
            from silero_vad import VADIterator
        except ImportError as e:
            logger.error(f"[STT/silero] {e}")
            return np.zeros(1, dtype="float32")

        sr         = self._VAD_SR
        chunk      = self._VAD_CHUNK
        max_chunks = int(self.max_rec_ms / 1000 * sr / chunk)

        vad_iter = VADIterator(
            self._vad_model,
            threshold=self.vad_threshold,
            sampling_rate=sr,
            min_silence_duration_ms=self.min_sil_ms,
            speech_pad_ms=100,
        )
        vad_iter.reset_states()

        frames: list[np.ndarray] = []
        total_chunks   = 0
        speech_started = False

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
            channels=1,
            dtype="float32",
            blocksize=chunk,
            device=self._dev_idx,
            callback=_cb,
        )

        logger.debug("[STT/silero] Gravacao iniciada (VAD neural)")
        with stream:
            while not self._stop_evt.is_set() and total_chunks < max_chunks:
                try:
                    indata = self._audio_q.get(timeout=0.1)
                except queue.Empty:
                    continue

                mono = (indata[:, 0] if indata.ndim > 1 else indata.flatten()).copy()
                frames.append(mono)
                total_chunks += 1

                result = vad_iter(mono, return_seconds=False)
                if result is not None:
                    if "start" in result:
                        speech_started = True
                        logger.debug("[STT/silero] Fala detectada")
                    elif "end" in result and speech_started:
                        logger.debug("[STT/silero] Fim de fala detectado")
                        break

            if total_chunks >= max_chunks:
                logger.warning(f"[STT/silero] Limite de {self.max_rec_ms}ms atingido.")

        logger.debug("[STT/silero] Gravacao encerrada")
        vad_iter.reset_states()
        return np.concatenate(frames) if frames else np.zeros(1, dtype="float32")

    def stop_recording(self) -> None:
        self._stop_evt.set()

    # ── Transcricao ───────────────────────────────────────────────────────────

    def transcribe(self, audio: np.ndarray) -> str:
        if self._whisper_error:
            logger.error(f"[STT/silero] Whisper nao carregou: {self._whisper_error}")
            return ""
        if self._whisper_model is None:
            logger.warning("[STT/silero] Whisper ainda carregando...")
            return ""
        if len(audio) < 100:
            return ""
        try:
            segments, _ = self._whisper_model.transcribe(
                audio,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info(f"[STT/silero] '{text}'")
            return text
        except Exception as e:
            logger.error(f"[STT/silero] Erro na transcricao: {e}")
            return ""
