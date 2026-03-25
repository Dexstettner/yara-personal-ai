"""
llm — Large Language Model package.
Troque o provider em config.json -> ai.provider

  anthropic : Claude via API Anthropic
  ollama    : modelos locais via Ollama
"""

import logging

from .anthropic import AnthropicProvider
from .ollama import OllamaProvider

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, type] = {
    "anthropic": AnthropicProvider,
    "ollama":    OllamaProvider,
}


class LLMClient:
    """
    Fachada publica — gerencia historico e delega ao provider configurado.
    Interface: chat(user_text), clear_history()
    """

    def __init__(self, cfg: dict):
        self.cfg     = cfg
        self.history: list[dict] = []

        provider = cfg.get("provider", "ollama").lower()
        if provider not in _PROVIDERS:
            logger.error(
                f"[LLM] Provider '{provider}' invalido. "
                f"Opcoes: {', '.join(_PROVIDERS)}. Usando ollama."
            )
            provider = "ollama"

        logger.info(f"[LLM] Provider: {provider}")
        self._provider = _PROVIDERS[provider](cfg)

    @property
    def client(self):
        """Exposto para retrocompatibilidade caso algum codigo externo acesse."""
        return self._provider.client

    def chat(self, user_text: str) -> str:
        """Envia mensagem ao LLM e retorna a resposta."""
        if not self._provider.client:
            return (
                "Ola! Ainda nao estou conectada ao servico de IA. "
                "Verifique as configuracoes em config.json (ai.provider e ai.api_key)."
            )

        self.history.append({"role": "user", "content": user_text})

        # Trunca historico por caracteres estimados (~3 chars/token)
        max_chars = self.cfg.get("num_ctx", 2048) * 3
        while len(self.history) > 1 and sum(len(m["content"]) for m in self.history) > max_chars:
            self.history = self.history[2:]  # remove par user/assistant mais antigo

        try:
            reply = self._provider.chat(self.history, self.cfg)
            self.history.append({"role": "assistant", "content": reply})
            logger.info(f"[LLM] Resposta: '{reply}'")
            return reply
        except Exception as e:
            logger.error(f"[LLM] Erro na chamada: {e}")
            self.history.pop()
            return "Desculpe, ocorreu um erro ao processar sua solicitacao."

    def clear_history(self) -> None:
        self.history = []
        logger.info("[LLM] Historico limpo")
