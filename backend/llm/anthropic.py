"""
llm/anthropic.py — Provider LLM: Anthropic (Claude API).
"""

import logging
import os

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """
    Cliente Anthropic (Claude).

    Config (config.json -> ai, quando provider = "anthropic"):
      api_key      : chave Claude (ou via env ANTHROPIC_API_KEY)
      model        : "claude-sonnet-4-6" | "claude-opus-4-6" | etc.
      max_tokens   : 300
      system_prompt: texto do system prompt
    """

    def __init__(self, cfg: dict):
        self.cfg    = cfg
        self.client = None
        self._init()

    def _init(self) -> None:
        api_key = (
            os.environ.get("ANTHROPIC_API_KEY", "").strip()
            or self.cfg.get("api_key", "").strip()
        )
        if not api_key:
            logger.warning(
                "[LLM/anthropic] api_key nao configurada. "
                "Adicione ANTHROPIC_API_KEY no .env ou ai.api_key no config.json."
            )
            return
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            logger.info("[LLM/anthropic] Cliente inicializado")
        except ImportError:
            logger.error("[LLM/anthropic] Instale: pip install anthropic")
        except Exception as e:
            logger.error(f"[LLM/anthropic] Erro: {e}")

    def chat(self, history: list[dict], cfg: dict) -> str:
        response = self.client.messages.create(
            model=cfg.get("model", "claude-sonnet-4-6"),
            max_tokens=cfg.get("max_tokens", 1024),
            system=cfg.get("system_prompt", "Responda em portugues do Brasil."),
            messages=history,
        )
        return response.content[0].text
