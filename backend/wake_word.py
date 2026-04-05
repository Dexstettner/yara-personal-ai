"""
wake_word.py — Detector de palavra de ativação.

Grava chunks curtos de áudio via sounddevice e os envia ao STT service via HTTP
para transcrição. Detecta frases de ativação ("yara") e de parada ("pare").
"""

import asyncio
import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Args:
        stt_client: instância de STTClient (cliente HTTP para o STT service)
        cfg       : config.json → stt.wake_word
        cfg_audio : config.json → audio
    """

    def __init__(self, stt_client, cfg: dict, cfg_audio: dict):
        self.stt_client   = stt_client
        self.cfg          = cfg
        self.cfg_audio    = cfg_audio

        self.wake_phrases = [p.lower() for p in cfg.get("wake_phrases", ["yara"])]
        self.stop_phrases = [p.lower() for p in cfg.get("stop_phrases", ["pare", "para", "yara pare", "yara para"])]
        self.chunk_dur    = cfg.get("chunk_duration", 2.0)
        self.min_rms      = cfg.get("min_rms", 0.008)

        self._enabled     = cfg.get("enabled", True)
        self._task        = None
        self._mic_busy    = threading.Event()
        self._is_speaking = False

        self._on_wake = None
        self._on_stop = None

    # ── API pública ──────────────────────────────────────────────────────────

    def set_callbacks(self, on_wake, on_stop):
        self._on_wake = on_wake
        self._on_stop = on_stop

    def set_mic_busy(self, busy: bool):
        if busy:
            self._mic_busy.set()
        else:
            self._mic_busy.clear()

    def set_speaking(self, speaking: bool):
        """Reduz chunk_duration para 0.6s durante a fala da IA,
        permitindo detecção rápida do stop phrase."""
        self._is_speaking = speaking

    async def start(self):
        if not self._enabled:
            logger.info("[WakeWord] Desativado no config.")
            return

        # Aguarda STT service ficar pronto (modelo Whisper pode demorar)
        logger.info("[WakeWord] Aguardando STT service (até 120s)...")
        ready = await self.stt_client.wait_ready(attempts=60, delay=2.0)
        if not ready:
            logger.warning("[WakeWord] STT service não ficou pronto — wake word desativado.")
            return

        self._task = asyncio.create_task(self._loop())
        logger.info(f"[WakeWord] Ativo | ativação: {self.wake_phrases} | parada: {self.stop_phrases}")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Loop interno ─────────────────────────────────────────────────────────

    async def _loop(self):
        import sounddevice as sd

        loop   = asyncio.get_event_loop()
        sr     = self.cfg_audio.get("sample_rate", 16000)
        device = self.cfg_audio.get("input_device_index")

        while True:
            if self._mic_busy.is_set():
                await asyncio.sleep(0.2)
                continue

            chunk_dur = 0.6 if self._is_speaking else self.chunk_dur
            samples   = int(sr * chunk_dur)

            try:
                audio = await loop.run_in_executor(
                    None, self._record_chunk, sr, samples, device
                )
            except Exception:
                await asyncio.sleep(0.3)
                continue

            if np.sqrt(np.mean(audio ** 2)) < self.min_rms:
                continue

            # Transcreve via STT service (HTTP)
            text = await self.stt_client.transcribe(audio)
            text_lower = text.lower().strip()
            if not text_lower:
                continue

            logger.debug(f"[WakeWord] Ouviu: '{text_lower}'")

            # Parada tem prioridade
            if any(sp in text_lower for sp in self.stop_phrases):
                logger.info(f"[WakeWord] Parada detectada: '{text_lower}'")
                if self._on_stop:
                    await self._on_stop()
                continue

            # Ativação (só quando pipeline inativo)
            if not self._mic_busy.is_set():
                if any(wp in text_lower for wp in self.wake_phrases):
                    logger.info(f"[WakeWord] Ativação detectada: '{text_lower}'")
                    if self._on_wake:
                        await self._on_wake()

    def _record_chunk(self, sr: int, samples: int, device) -> np.ndarray:
        import sounddevice as sd
        rec = sd.rec(samples, samplerate=sr, channels=1,
                     dtype="float32", device=device)
        sd.wait()
        return rec.flatten()
