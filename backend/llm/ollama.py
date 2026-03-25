"""
llm/ollama.py — Provider LLM: Ollama (modelos locais).
"""

import logging

logger = logging.getLogger(__name__)


class OllamaProvider:
    """
    Cliente Ollama para modelos locais (llama, gemma, mistral, etc.).

    Config (config.json -> ai, quando provider = "ollama"):
      model      : "fast-llama" | "llama3" | "gemma3" | etc.
      base_url   : "http://localhost:11434"
      timeout    : 120
      temperature: 0.8
      max_tokens : 300
      num_ctx    : 2048
      num_gpu    : 99  (null = auto, 99 = forca GPU)
      system_prompt: texto do system prompt
    """

    def __init__(self, cfg: dict):
        self.cfg    = cfg
        self.client = None
        self._init()

    def _init(self) -> None:
        try:
            import ollama
            base_url = self.cfg.get("base_url", "http://localhost:11434")
            timeout  = self.cfg.get("timeout",  120)
            self.client = ollama.Client(host=base_url, timeout=timeout)

            model  = self.cfg.get("model", "llama3")
            result = self.client.list()
            if isinstance(result, dict):
                models = [m.get("name", m.get("model", "")) for m in result.get("models", [])]
            else:
                models = [m.model for m in result.models]

            if not any(model in m for m in models):
                logger.warning(
                    f"[LLM/ollama] Modelo '{model}' nao encontrado. "
                    f"Execute: ollama pull {model}"
                )
            else:
                logger.info(f"[LLM/ollama] Pronto com modelo '{model}'")
        except ImportError:
            logger.error("[LLM/ollama] Instale: pip install ollama")
            self.client = None
        except Exception as e:
            logger.error(f"[LLM/ollama] Erro ao conectar: {e}. Certifique-se que esta rodando.")
            self.client = None

    def chat(self, history: list[dict], cfg: dict) -> str:
        # Libera cache CUDA residual (Whisper/TTS) antes da inferencia
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        model         = cfg.get("model",         "llama3")
        system_prompt = cfg.get("system_prompt", "Responda em portugues do Brasil.")
        messages      = [{"role": "system", "content": system_prompt}] + history

        options: dict = {
            "temperature": cfg.get("temperature", 0.8),
            "num_predict": cfg.get("max_tokens",  1024),
            "num_ctx":     cfg.get("num_ctx",     4096),
        }
        num_gpu = cfg.get("num_gpu")
        if num_gpu is not None:
            options["num_gpu"] = num_gpu

        response = self.client.chat(model=model, messages=messages, options=options)
        if isinstance(response, dict):
            return response["message"]["content"]
        return response.message.content
