"""
clients/tts_client.py — Cliente HTTP assíncrono para o TTS service.
"""

import asyncio
import logging
import threading
from typing import List, Tuple

import httpx

logger = logging.getLogger(__name__)


class TTSClient:
    """
    Wrapper assíncrono para o TTS microservice.

    O método speak() inicia a reprodução no serviço e monitora stop_event:
    se o evento for ativado, envia POST /stop para interromper o áudio.

    Args:
        base_url: URL base do serviço, ex: "http://127.0.0.1:8767"
        timeout : timeout máximo de uma chamada /speak (segundos)
    """

    def __init__(self, base_url: str, timeout: float = 120.0):
        self._url     = base_url.rstrip("/")
        self._timeout = timeout

    async def speak(
        self,
        segments: List[Tuple[str, str]],
        stop_event: threading.Event,
    ) -> None:
        """Envia segmentos ao serviço TTS e aguarda o fim da reprodução.
        Monitora stop_event e chama /stop se necessário."""
        payload = {"segments": [{"emotion": e, "text": t} for e, t in segments]}

        speak_task   = asyncio.create_task(self._post_speak(payload))
        monitor_task = asyncio.create_task(self._monitor_stop(stop_event))

        try:
            done, pending = await asyncio.wait(
                [speak_task, monitor_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Se o monitor terminou primeiro (stop_event ativado), cancela o speak
            if monitor_task in done and not speak_task.done():
                speak_task.cancel()
                try:
                    await speak_task
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            for task in [speak_task, monitor_task]:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

    async def _post_speak(self, payload: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._url}/speak", json=payload)
                resp.raise_for_status()
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException:
            logger.warning("[TTSClient] Timeout no /speak")
        except Exception as e:
            logger.error(f"[TTSClient] Erro em /speak: {e}")

    async def _monitor_stop(self, stop_event: threading.Event) -> None:
        """Monitora stop_event e envia /stop quando ativado."""
        while not stop_event.is_set():
            await asyncio.sleep(0.05)
        await self.stop()

    async def stop(self) -> None:
        """Interrompe reprodução em andamento."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self._url}/stop")
        except Exception as e:
            logger.warning(f"[TTSClient] Erro em /stop: {e}")

    async def estimate_lip_sync(self, text: str, n_frames: int = 40) -> list:
        """Busca estimativa de movimento labial para o texto."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self._url}/lip_sync",
                    params={"text": text, "n_frames": n_frames},
                )
                resp.raise_for_status()
                return resp.json().get("frames", [])
        except Exception as e:
            logger.warning(f"[TTSClient] Erro em /lip_sync: {e}")
            return []

    async def is_ready(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._url}/health")
                return resp.status_code == 200 and resp.json().get("ready", False)
        except Exception:
            return False

    async def wait_ready(self, attempts: int = 30, delay: float = 2.0) -> bool:
        for i in range(attempts):
            if await self.is_ready():
                return True
            if i == 0:
                logger.info("[TTSClient] Aguardando TTS service ficar pronto...")
            await asyncio.sleep(delay)
        logger.error("[TTSClient] TTS service não ficou pronto a tempo")
        return False
