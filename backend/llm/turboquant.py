"""
llm/turboquant.py — Provider LLM: TurboQuant (Google, 2026).

Conecta ao turboquant-server, que expõe API compatível com OpenAI.
Para iniciar o servidor:
    pip install turboquant
    turboquant-server --model Qwen/Qwen2.5-7B-Instruct --bits 4 --port 8000

Config (config.json -> ai, quando provider = "turboquant"):
  turboquant:
    base_url : "http://localhost:8000"  (porta do turboquant-server)
    model    : "Qwen/Qwen2.5-7B-Instruct"  (modelo HuggingFace)
    bits     : 4  (quantização do KV cache: 3 ou 4; 4 recomendado para <7B)
  timeout      : 120
  temperature  : 0.8
  max_tokens   : 300
  system_prompt: texto do system prompt
"""

import logging

logger = logging.getLogger(__name__)


class TurboQuantProvider:
    def __init__(self, cfg: dict):
        self.cfg    = cfg
        self.client = None
        self._init()

    def _init(self) -> None:
        tq_cfg   = self.cfg.get("turboquant", {})
        base_url = tq_cfg.get("base_url", "http://localhost:8000")
        model    = tq_cfg.get("model", self.cfg.get("model", "Qwen/Qwen2.5-7B-Instruct"))
        bits     = tq_cfg.get("bits", 4)
        timeout  = self.cfg.get("timeout", 120)

        try:
            from openai import OpenAI
            self.client = OpenAI(
                base_url=f"{base_url.rstrip('/')}/v1",
                api_key="none",
                timeout=timeout,
                max_retries=0,
            )
            # Testa conexão listando modelos
            try:
                self.client.models.list()
                logger.info(f"[LLM/turboquant] Pronto — modelo '{model}', {bits}-bit KV cache")
            except Exception:
                logger.warning(
                    f"[LLM/turboquant] Servidor não respondeu em {base_url}. "
                    f"Inicie com: turboquant-server --model {model} --bits {bits} --port 8000"
                )
                self.client = None
        except ImportError:
            logger.error("[LLM/turboquant] Instale: pip install openai")
            self.client = None

    def chat(self, history: list[dict], cfg: dict) -> str:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        tq_cfg        = cfg.get("turboquant", {})
        model         = tq_cfg.get("model", cfg.get("model", "Qwen/Qwen2.5-7B-Instruct"))
        system_prompt = cfg.get("system_prompt", "Responda em portugues do Brasil.")
        messages      = [{"role": "system", "content": system_prompt}] + history

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=cfg.get("temperature", 0.8),
            max_tokens=cfg.get("max_tokens", 300),
        )
        return response.choices[0].message.content
