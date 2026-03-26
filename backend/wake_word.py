"""
wake_word.py — Detector de palavra de ativação usando Whisper

Roda em loop de fundo gravando chunks curtos.
Detecta frases de ativação ("yana") e de parada ("yana pare").
Coordena com o pipeline principal via evento de microfone.
"""

import asyncio
import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self, stt, cfg: dict, cfg_audio: dict):
        self.stt          = stt
        self.cfg          = cfg
        self.cfg_audio    = cfg_audio

        self.wake_phrases = [p.lower() for p in cfg.get("wake_phrases", ["yana"])]
        self.stop_phrases = [p.lower() for p in cfg.get("stop_phrases", ["pare", "para", "yana pare", "yana para"])]
        self.chunk_dur    = cfg.get("chunk_duration", 2.0)
        self.min_rms      = cfg.get("min_rms", 0.008)

        self._enabled     = cfg.get("enabled", True)
        self._task        = None
        self._mic_busy    = threading.Event()  # sinaliza que STT principal está gravando
        self._is_speaking = False               # IA está falando (chunk menor para resposta rápida)

        self._on_wake     = None
        self._on_stop     = None

    # ─── API pública ──────────────────────────────────────────────────────────

    def set_callbacks(self, on_wake, on_stop):
        """on_wake e on_stop são corrotinas async."""
        self._on_wake = on_wake
        self._on_stop = on_stop

    def set_mic_busy(self, busy: bool):
        """Chame com True quando o STT principal começar a gravar, False ao terminar."""
        if busy:
            self._mic_busy.set()
        else:
            self._mic_busy.clear()

    def set_speaking(self, speaking: bool):
        """Chame com True quando a IA começar a falar, False ao terminar.
        Reduz chunk_duration para 0.6s durante a fala, permitindo detecção rápida de 'pare'."""
        self._is_speaking = speaking

    async def start(self):
        if not self._enabled:
            logger.info("[WakeWord] Desativado no config.")
            return
        if not self.stt.model:
            logger.info("[WakeWord] Aguardando Whisper carregar (até 60s)...")
            for _ in range(60):
                await asyncio.sleep(1)
                if self.stt.model:
                    break
            if not self.stt.model:
                logger.warning("[WakeWord] Whisper não carregou em 60s, wake word desativado.")
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

    # ─── Loop interno ─────────────────────────────────────────────────────────

    async def _loop(self):
        import sounddevice as sd

        loop      = asyncio.get_event_loop()
        sr        = self.cfg_audio.get("sample_rate", 16000)
        device    = self.cfg_audio.get("input_device_index")

        while True:
            # Espera o microfone ficar livre (STT principal gravando)
            if self._mic_busy.is_set():
                await asyncio.sleep(0.2)
                continue

            # Chunk menor durante fala da IA para detectar "pare" mais rápido
            chunk_dur = 0.6 if self._is_speaking else self.chunk_dur
            samples   = int(sr * chunk_dur)

            try:
                # Grava chunk curto em thread separada
                audio = await loop.run_in_executor(
                    None, self._record_chunk, sr, samples, device
                )
            except Exception as e:
                # Microfone em uso ou outro erro — tenta de novo
                await asyncio.sleep(0.3)
                continue

            # Verifica energia mínima (evita transcrever silêncio)
            if np.sqrt(np.mean(audio ** 2)) < self.min_rms:
                continue

            # Transcreve
            text = await loop.run_in_executor(None, self.stt.transcribe, audio)
            text_lower = text.lower().strip()
            if not text_lower:
                continue

            logger.debug(f"[WakeWord] Ouviu: '{text_lower}'")

            # Parada tem prioridade (funciona mesmo durante fala da IA)
            if any(sp in text_lower for sp in self.stop_phrases):
                logger.info(f"[WakeWord] Parada detectada: '{text_lower}'")
                if self._on_stop:
                    await self._on_stop()
                continue

            # Ativação (só quando microfone livre = pipeline inativo)
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
