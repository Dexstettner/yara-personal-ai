"""
llm/llama_cpp.py — Provider LLM: llama-cpp-python (in-process, sem daemon externo).

Vantagens vs Ollama:
  - Sem IPC overhead (roda no mesmo processo)
  - ~13% mais rapido em geracao de tokens
  - ~10x mais rapido em processamento de prompt (416 t/s vs 42 t/s)
  - TTFT ~50ms menor (~200ms vs ~250ms)
  - Sem servico externo para gerenciar

Instalacao:
  Windows CUDA 12.x:
    set CMAKE_ARGS=-DGGML_CUDA=on
    set FORCE_CMAKE=1
    pip install llama-cpp-python --no-cache-dir --force-reinstall

  CPU only:
    pip install llama-cpp-python

Config (config.json -> ai.llama_cpp):
  model_path   : caminho relativo ao projeto para o .gguf  (ex: "models/fast-llama.gguf")
  n_gpu_layers : -1 = todas as camadas na GPU | 0 = CPU only | N = N camadas na GPU
  n_threads    : null = auto | N = numero de threads CPU
  n_ctx        : tamanho do contexto (default: ai.num_ctx ou 2048)
  temperature  : default: ai.temperature ou 0.8
  max_tokens   : default: ai.max_tokens ou 300
"""

import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class LlamaCppProvider:
    """
    Carrega um modelo GGUF diretamente in-process via llama-cpp-python.
    Elimina o overhead de IPC do Ollama para menor latencia.
    """

    def __init__(self, cfg: dict):
        self._full_cfg   = cfg
        llama_cfg        = cfg.get("llama_cpp", {})

        self.model_path    = llama_cfg.get("model_path",   "")
        self.n_gpu_layers  = llama_cfg.get("n_gpu_layers", -1)
        self.n_threads     = llama_cfg.get("n_threads",    None)
        self.n_ctx         = llama_cfg.get("n_ctx",        cfg.get("num_ctx", 2048))

        self.client      = None
        self._load_error = None
        self._lock       = threading.Lock()

        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self) -> None:
        with self._lock:
            if self.client is not None or self._load_error is not None:
                return

            if not self.model_path:
                self._load_error = (
                    "model_path nao configurado. "
                    "Adicione ai.llama_cpp.model_path em config.json."
                )
                logger.error(f"[LLM/llama-cpp] {self._load_error}")
                return

            root      = Path(__file__).parent.parent.parent
            full_path = root / self.model_path

            if not full_path.exists():
                self._load_error = f"Arquivo nao encontrado: {full_path}"
                logger.error(f"[LLM/llama-cpp] {self._load_error}")
                return

            try:
                from llama_cpp import Llama

                kwargs: dict = {
                    "model_path":    str(full_path),
                    "n_gpu_layers":  self.n_gpu_layers,
                    "n_ctx":         self.n_ctx,
                    "verbose":       False,
                }
                if self.n_threads is not None:
                    kwargs["n_threads"] = self.n_threads

                logger.info(
                    f"[LLM/llama-cpp] Carregando '{full_path.name}' | "
                    f"gpu_layers: {self.n_gpu_layers} | ctx: {self.n_ctx}"
                )
                self.client = Llama(**kwargs)
                logger.info(f"[LLM/llama-cpp] '{full_path.name}' carregado")

            except ImportError:
                self._load_error = "llama-cpp-python nao instalado"
                logger.error(
                    "[LLM/llama-cpp] llama-cpp-python nao instalado. "
                    "Ver instrucoes de instalacao no topo deste arquivo."
                )
            except Exception as e:
                self._load_error = str(e)
                logger.error(f"[LLM/llama-cpp] Erro ao carregar modelo: {e}")

    def chat(self, history: list[dict], cfg: dict) -> str:
        if self._load_error:
            raise RuntimeError(f"[LLM/llama-cpp] Modelo nao disponivel: {self._load_error}")
        if self.client is None:
            raise RuntimeError("[LLM/llama-cpp] Modelo ainda carregando...")

        llama_cfg     = cfg.get("llama_cpp", {})
        system_prompt = cfg.get("system_prompt", "Responda em portugues do Brasil.")
        temperature   = llama_cfg.get("temperature", cfg.get("temperature", 0.8))
        max_tokens    = llama_cfg.get("max_tokens",  cfg.get("max_tokens",  300))

        messages = [{"role": "system", "content": system_prompt}] + history

        response = self.client.create_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response["choices"][0]["message"]["content"]
