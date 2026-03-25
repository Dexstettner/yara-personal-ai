"""
llm.py — Integração com LLM: suporta Anthropic (Claude) e Ollama (local)

Configuração em config.json:
  - ai.provider: "anthropic" | "ollama"
  - ai.api_key:  chave Anthropic (deixe vazio para Ollama)
  - ai.model:    ex: "claude-sonnet-4-6" ou "llama3", "gemma3", "mistral"
  - ai.base_url: apenas Ollama — padrão "http://localhost:11434"
"""

import logging

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, cfg: dict):
        self.cfg     = cfg
        self.history = []
        self.client  = None
        self._init_client()

    def _init_client(self):
        provider = self.cfg.get("provider", "anthropic").lower()

        if provider == "anthropic":
            self._init_anthropic()
        elif provider == "ollama":
            self._init_ollama()
        else:
            logger.error(f"[LLM] Provider desconhecido: '{provider}'. Use 'anthropic' ou 'ollama'.")

    # ─── Anthropic / Claude ───────────────────────────────────────────────
    def _init_anthropic(self):
        # Prioridade: .env (ANTHROPIC_API_KEY) → config.json (ai.api_key)
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or self.cfg.get("api_key", "").strip()
        if not api_key:
            logger.warning(
                "[LLM] api_key não configurada. "
                "Adicione ANTHROPIC_API_KEY no .env ou ai.api_key no config.json"
            )
            return
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            logger.info("[LLM] Cliente Anthropic (Claude) inicializado")
        except ImportError:
            logger.error("[LLM] Instale o pacote: pip install anthropic")
        except Exception as e:
            logger.error(f"[LLM] Erro Anthropic: {e}")

    def _chat_anthropic(self, user_text: str) -> str:
        response = self.client.messages.create(
            model=self.cfg.get("model", "claude-sonnet-4-6"),
            max_tokens=self.cfg.get("max_tokens", 1024),
            system=self.cfg.get("system_prompt", "Responda em português do Brasil."),
            messages=self.history,
        )
        return response.content[0].text

    # ─── Ollama (local) ───────────────────────────────────────────────────
    def _init_ollama(self):
        try:
            import ollama
            base_url = self.cfg.get("base_url", "http://localhost:11434")
            timeout   = self.cfg.get("timeout", 120)
            self.client = ollama.Client(host=base_url, timeout=timeout)
            model = self.cfg.get("model", "llama3")
            # Verifica se o modelo está disponível localmente
            # list() pode retornar dict ou objeto dependendo da versão da lib
            result = self.client.list()
            if isinstance(result, dict):
                models = [m.get("name", m.get("model", "")) for m in result.get("models", [])]
            else:
                models = [m.model for m in result.models]

            if not any(model in m for m in models):
                logger.warning(
                    f"[LLM] Modelo '{model}' não encontrado no Ollama. "
                    f"Execute: ollama pull {model}"
                )
            else:
                logger.info(f"[LLM] Ollama pronto com modelo '{model}'")
        except ImportError:
            logger.error("[LLM] Instale o pacote: pip install ollama")
            self.client = None
        except Exception as e:
            logger.error(f"[LLM] Erro ao conectar ao Ollama: {e}. Certifique-se que está rodando.")
            self.client = None

    def _chat_ollama(self, user_text: str) -> str:
        # Libera cache CUDA residual (Whisper) antes da inferência do LLM
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        model = self.cfg.get("model", "llama3")
        system_prompt = self.cfg.get("system_prompt", "Responda em português do Brasil.")

        # Ollama aceita 'system' como primeira mensagem
        messages = [{"role": "system", "content": system_prompt}] + self.history

        options = {
            "temperature": self.cfg.get("temperature", 0.8),
            "num_predict": self.cfg.get("max_tokens", 1024),
            "num_ctx":     self.cfg.get("num_ctx", 4096),
        }
        # num_gpu: null/ausente = Ollama auto-balanceia VRAM+RAM
        # num_gpu: 99 = força tudo na GPU (só se o modelo couber na VRAM)
        num_gpu = self.cfg.get("num_gpu")
        if num_gpu is not None:
            options["num_gpu"] = num_gpu

        response = self.client.chat(
            model=model,
            messages=messages,
            options=options,
        )
        # A lib ollama pode retornar dict ou objeto dependendo da versão
        if isinstance(response, dict):
            return response["message"]["content"]
        return response.message.content

    # ─── Interface pública ────────────────────────────────────────────────
    def chat(self, user_text: str) -> str:
        """Envia mensagem ao LLM configurado e retorna a resposta."""
        if not self.client:
            return (
                "Olá! Ainda não estou conectada ao serviço de IA. "
                "Verifique as configurações em config.json (ai.provider e ai.api_key)."
            )

        self.history.append({"role": "user", "content": user_text})
        # Trunca por caracteres estimados (~3 chars/token) para respeitar num_ctx
        max_chars = self.cfg.get("num_ctx", 2048) * 3
        while len(self.history) > 1 and sum(len(m["content"]) for m in self.history) > max_chars:
            self.history = self.history[2:]  # remove par user/assistant mais antigo

        try:
            provider = self.cfg.get("provider", "anthropic").lower()
            if provider == "anthropic":
                reply = self._chat_anthropic(user_text)
            else:
                reply = self._chat_ollama(user_text)

            self.history.append({"role": "assistant", "content": reply})
            logger.info(f"[LLM] Resposta: '{reply}'")
            return reply

        except Exception as e:
            logger.error(f"[LLM] Erro na chamada: {e}")
            self.history.pop()  # Remove a mensagem do usuário se falhou
            return "Desculpe, ocorreu um erro ao processar sua solicitação."

    def clear_history(self):
        self.history = []
        logger.info("[LLM] Histórico limpo")
