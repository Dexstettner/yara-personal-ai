"""
clients/stt_client.py — Cliente HTTP assíncrono para o STT service.
"""

import base64
import logging

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class STTClient:
    """
    Wrapper assíncrono para o STT microservice.

    Args:
        base_url: URL base do serviço, ex: "http://127.0.0.1:8766"
        timeout : timeout das chamadas HTTP em segundos
    """

    def __init__(self, base_url: str, timeout: float = 60.0):
        self._url     = base_url.rstrip("/")
        self._timeout = timeout

    async def transcribe(self, audio: np.ndarray) -> str:
        """Envia áudio float32 ao serviço e retorna o texto transcrito."""
        audio_b64 = base64.b64encode(audio.astype(np.float32).tobytes()).decode()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/transcribe",
                    json={"audio_b64": audio_b64, "sample_rate": 16000},
                )
                resp.raise_for_status()
                return resp.json().get("text", "")
        except httpx.TimeoutException:
            logger.error("[STTClient] Timeout na transcrição")
            return ""
        except Exception as e:
            logger.error(f"[STTClient] Erro: {e}")
            return ""

    async def is_ready(self) -> bool:
        """Verifica se o serviço está pronto (modelo carregado)."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._url}/health")
                return resp.status_code == 200 and resp.json().get("ready", False)
        except Exception:
            return False

    async def wait_ready(self, attempts: int = 60, delay: float = 2.0) -> bool:
        """Aguarda o serviço ficar pronto (modelo Whisper pode demorar)."""
        import asyncio
        for i in range(attempts):
            if await self.is_ready():
                return True
            if i == 0:
                logger.info("[STTClient] Aguardando STT service ficar pronto...")
            await asyncio.sleep(delay)
        logger.error("[STTClient] STT service não ficou pronto a tempo")
        return False
