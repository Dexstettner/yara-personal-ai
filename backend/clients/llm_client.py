"""
clients/llm_client.py — Cliente HTTP assíncrono para o LLM service.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Wrapper assíncrono para o LLM microservice.
    O histórico de conversa é mantido no serviço (stateful).

    Args:
        base_url: URL base do serviço, ex: "http://127.0.0.1:8768"
        timeout : timeout de uma chamada /chat (segundos)
    """

    def __init__(self, base_url: str, timeout: float = 120.0):
        self._url     = base_url.rstrip("/")
        self._timeout = timeout

    async def chat(self, text: str) -> str:
        """Envia mensagem ao LLM e retorna a resposta."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/chat",
                    json={"text": text},
                )
                resp.raise_for_status()
                return resp.json().get("reply", "")
        except httpx.TimeoutException:
            logger.error("[LLMClient] Timeout na chamada LLM")
            return "Desculpe, a IA demorou demais para responder."
        except Exception as e:
            logger.error(f"[LLMClient] Erro: {e}")
            return "Desculpe, ocorreu um erro ao processar sua solicitação."

    async def clear_history(self) -> None:
        """Limpa o histórico de conversa no serviço."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self._url}/clear_history")
        except Exception as e:
            logger.warning(f"[LLMClient] Erro ao limpar histórico: {e}")

    async def is_ready(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._url}/health")
                return resp.status_code == 200 and resp.json().get("ready", False)
        except Exception:
            return False

    async def wait_ready(self, attempts: int = 30, delay: float = 2.0) -> bool:
        import asyncio
        for i in range(attempts):
            if await self.is_ready():
                return True
            if i == 0:
                logger.info("[LLMClient] Aguardando LLM service ficar pronto...")
            await asyncio.sleep(delay)
        logger.error("[LLMClient] LLM service não ficou pronto a tempo")
        return False
