"""
tts.py — Multi-engine TTS: edge-tts | voicevox | fish-speech | index-tts2
Troque o provider em config.json → tts.provider

  edge-tts    : vozes neurais Microsoft (requer internet, sem API key)
  voicevox    : vozes anime japonesas (requer VOICEVOX rodando localmente)
  fish-speech : vozes naturais multilíngue (requer Fish Speech server local)
  index-tts2  : TTS offline por clonagem de voz (requer reference_audio .wav)
"""

import asyncio
import ctypes
import logging
import math
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _to_short_path(path: str) -> str:
    """Converte para caminho curto (8.3) no Windows — evita falhas de libs C++
    com caminhos contendo caracteres especiais (ex: 'Área de Trabalho').
    No-op em outros sistemas."""
    if os.name != 'nt':
        return path
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024):
        return buf.value
    return path  # fallback: retorna original se falhar


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de reprodução via pygame
# ─────────────────────────────────────────────────────────────────────────────

async def _play_file(path: str, stop_event, suffix: str = ""):
    """Reproduz arquivo de áudio (mp3/wav) via pygame e aguarda terminar."""
    import pygame
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if stop_event.is_set():
                pygame.mixer.music.stop()
                break
            await asyncio.sleep(0.05)
    finally:
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass


async def _play_bytes(data: bytes, suffix: str, stop_event):
    """Salva bytes em arquivo temporário e reproduz."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(data)
    tmp.close()
    try:
        await _play_file(tmp.name, stop_event)
    finally:
        if os.path.exists(tmp.name):
            try:
                os.remove(tmp.name)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Pré-processamento de texto (compartilhado)
# Remove markdown e ações entre asteriscos que TTS leria literalmente
# ─────────────────────────────────────────────────────────────────────────────

_TTS_CLEANUP_MAP = [
    (r'\*\*([^*\n]+)\*\*', r'\1'),   # **bold** → texto
    (r'_([^_\n]+)_',       r'\1'),   # _italic_ → texto
    (r'\*[^*\n]{1,80}\*',  ''),      # *ação* → remove
    (r' {2,}',             ' '),     # espaços duplicados
]

def _tts_preprocess(text: str) -> str:
    for pattern, replacement in _TTS_CLEANUP_MAP:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Engine: IndexTTS2
# ─────────────────────────────────────────────────────────────────────────────

class _IndexTTS2:
    """
    IndexTTS2 — TTS offline de alta qualidade por clonagem de voz.
    Modelo: IndexTeam/IndexTTS-2 (HuggingFace, ~650 MB).
    Download automático no primeiro uso.

    SOBRE PT-BR:
      O modelo clona o timbre do reference_audio fornecido.
      Coloque um .wav/.mp3 de 5 a 30 s de um falante PT-BR em:
        assets/reference_voice.mp3

    INSTALAÇÃO (IndexTTS v2 — obrigatório para o modelo IndexTeam/IndexTTS-2):
      pip uninstall indextts -y
      pip install git+https://github.com/index-tts/index-tts.git
      pip install wetext   # normalização numérica no Windows

    Configuração em config.json → tts.index_tts2:
      reference_audio : caminho relativo à raiz do projeto
      model_dir       : onde salvar os checkpoints (padrão: models/index-tts2)
      device          : "cuda" ou "cpu"
      use_fp16        : true para GPU (menor VRAM, mais rápido)
    """

    HF_REPO_V2 = "IndexTeam/IndexTTS-2"
    HF_REPO_V1 = "IndexTeam/IndexTTS"

    def __init__(self, cfg: dict):
        self.model_dir         = cfg.get("model_dir",         "models/index-tts2")
        self.reference_audio   = cfg.get("reference_audio",   "assets/reference_voice.wav")
        self.device            = cfg.get("device",            "cuda")
        self.use_fp16          = cfg.get("use_fp16",          True)
        self.use_cuda_kernel   = cfg.get("use_cuda_kernel",   False)
        self.use_accel         = cfg.get("use_accel",         False)
        self.use_torch_compile = cfg.get("use_torch_compile", False)
        self._model            = None
        self._api_v2           = False
        self._load_error       = None

        logger.info(
            f"[TTS/index-tts2] device: {self.device} | fp16: {self.use_fp16} | "
            f"cuda_kernel: {self.use_cuda_kernel} | torch_compile: {self.use_torch_compile}"
        )

    # ── carregamento lazy ────────────────────────────────────────────────────

    def _ensure_model(self):
        if self._model is not None:
            return
        if self._load_error is not None:
            raise RuntimeError(
                f"Carregamento anterior falhou: {self._load_error}\n"
                "  Corrija o problema e reinicie o backend."
            )

        # Detecta versão da biblioteca instalada
        try:
            from indextts.infer_v2 import IndexTTS2 as IndexTTSClass
            self._api_v2 = True
            hf_repo = self.HF_REPO_V2
            logger.info("[TTS/index-tts2] Biblioteca v2 detectada (infer_v2.IndexTTS2)")
        except ImportError:
            try:
                from indextts.infer import IndexTTS as IndexTTSClass
                self._api_v2 = False
                hf_repo = self.HF_REPO_V1
                logger.warning(
                    "[TTS/index-tts2] infer_v2 não encontrado — usando IndexTTS v1.\n"
                    "  Para usar IndexTTS-2, reinstale:\n"
                    "    pip uninstall indextts -y\n"
                    "    pip install git+https://github.com/index-tts/index-tts.git"
                )
            except ImportError:
                raise RuntimeError(
                    "[TTS/index-tts2] indextts não instalado.\n"
                    "  Execute: pip install git+https://github.com/index-tts/index-tts.git"
                )

        import torch
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("[TTS/index-tts2] CUDA não disponível — usando CPU. "
                           "Instale torch com suporte CUDA ou mude device para 'cpu' no config.json.")
            self.device = "cpu"

        root = Path(__file__).parent.parent
        mdir = root / self.model_dir
        mdir.mkdir(parents=True, exist_ok=True)

        if not (mdir / "gpt.pth").exists():
            logger.info(f"[TTS/index-tts2] Baixando {hf_repo} (~650 MB)...")
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=hf_repo, local_dir=str(mdir))
            logger.info("[TTS/index-tts2] Download concluído.")

        cfg_path = str(mdir / "config.yaml")
        is_fp16  = self.use_fp16 and self.device == "cuda"

        # Parâmetros diferem entre v1 e v2 — passa apenas o que o construtor aceita
        import inspect
        sig    = inspect.signature(IndexTTSClass.__init__)
        params = sig.parameters

        is_cuda = self.device == "cuda"
        kwargs = {"model_dir": _to_short_path(str(mdir)), "cfg_path": _to_short_path(cfg_path)}
        # mapeia todos os nomes conhecidos de fp16 entre versões do indextts
        for fp16_key in ("use_fp16", "is_fp16", "is_half", "fp16"):
            if fp16_key in params:
                kwargs[fp16_key] = is_fp16
        if "device"           in params: kwargs["device"]           = self.device
        if "use_cuda_kernel"  in params: kwargs["use_cuda_kernel"]  = self.use_cuda_kernel and is_cuda
        if "use_torch_compile"in params: kwargs["use_torch_compile"]= self.use_torch_compile
        if "use_accel"     in params: kwargs["use_accel"]     = self.use_accel
        if "use_deepspeed" in params: kwargs["use_deepspeed"] = False

        try:
            self._model = IndexTTSClass(**kwargs)
        except Exception as e:
            self._load_error = str(e)
            raise
        logger.info(f"[TTS/index-tts2] Modelo carregado (params: {list(kwargs.keys())})")

    # ── inferência ───────────────────────────────────────────────────────────

    async def speak_async(self, text: str, stop_event):
        text = _tts_preprocess(text)
        if not text.strip():
            return

        root     = Path(__file__).parent.parent
        ref_path = Path(root / self.reference_audio)

        # Converte automaticamente mp3 → wav se necessário
        if ref_path.exists() and ref_path.suffix.lower() != ".wav":
            import soundfile as sf
            data, sr = sf.read(str(ref_path))
            wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            wav_tmp.close()
            sf.write(wav_tmp.name, data, sr)
            ref_path = Path(wav_tmp.name)
            logger.info(f"[TTS/index-tts2] Referência convertida: {wav_tmp.name}")

        if not ref_path.exists():
            logger.error(
                f"[TTS/index-tts2] Áudio de referência não encontrado: {ref_path}\n"
                "  → Coloque um .mp3 ou .wav PT-BR (5-30s) em assets/reference_voice.mp3"
            )
            return

        ref_str = _to_short_path(str(ref_path))
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()

        try:
            await asyncio.to_thread(self._ensure_model)

            if stop_event.is_set():
                return

            def _gen():
                if self._api_v2:
                    # IndexTTS-2: parâmetro renomeado para spk_audio_prompt
                    self._model.infer(
                        spk_audio_prompt=ref_str,
                        text=text,
                        output_path=tmp.name,
                    )
                else:
                    # IndexTTS v1
                    self._model.infer(
                        audio_prompt=ref_str,
                        text=text,
                        output_path=tmp.name,
                    )

            await asyncio.to_thread(_gen)

            if not stop_event.is_set():
                await _play_file(tmp.name, stop_event)

        except Exception as e:
            logger.error(f"[TTS/index-tts2] Erro: {e}")
        finally:
            if os.path.exists(tmp.name):
                try:
                    os.remove(tmp.name)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# Engine: edge-tts
# ─────────────────────────────────────────────────────────────────────────────

class _EdgeTTS:
    """
    Vozes neurais da Microsoft via Edge (gratuito, requer internet).
    Vozes PT-BR:
      pt-BR-ThalitaNeural   — feminino, jovem/casual  ← padrão
      pt-BR-FranciscaNeural — feminino, profissional
      pt-BR-AntonioNeural   — masculino
    """

    def __init__(self, cfg: dict):
        self.voice  = cfg.get("voice",      "pt-BR-ThalitaNeural")
        self.rate   = cfg.get("rate_pct",   "+0%")
        self.volume = cfg.get("volume_pct", "+0%")
        logger.info(f"[TTS/edge-tts] voz: {self.voice}")

    async def speak_async(self, text: str, stop_event):
        import edge_tts

        text = _tts_preprocess(text)
        tmp  = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            communicate = edge_tts.Communicate(
                text, self.voice,
                rate=self.rate, volume=self.volume
            )
            await communicate.save(tmp.name)
            if not stop_event.is_set():
                await _play_file(tmp.name, stop_event)
        except Exception as e:
            logger.error(f"[TTS/edge-tts] Erro: {e}")
        finally:
            if os.path.exists(tmp.name):
                try:
                    os.remove(tmp.name)
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# Engine: VOICEVOX
# ─────────────────────────────────────────────────────────────────────────────

class _VoiceVox:
    """
    Vozes anime japonesas via VOICEVOX Engine (local, gratuito, offline).
    Instale: https://voicevox.hiroshiba.jp/
    O VOICEVOX deve estar rodando antes de iniciar o assistente.

    Speakers populares:
      1  — Shikoku Metan (normal)
      2  — Zundamon (normal)     ← padrão
      3  — Zundamon (amaama)
      8  — Shikoku Metan (sasayaki)
      13 — Kasukabe Tsumugi
    Lista completa: GET http://localhost:50021/speakers
    """

    def __init__(self, cfg: dict):
        self._lock = asyncio.Lock()
        self.host       = cfg.get("host",       "http://localhost:50021")
        self.speaker_id = cfg.get("speaker_id", 2)
        self.speed      = cfg.get("speed",      1.0)
        self.pitch      = cfg.get("pitch",      0.0)
        self.intonation = cfg.get("intonation", 1.0)
        self.volume     = cfg.get("volume",     1.0)
        logger.info(f"[TTS/voicevox] host: {self.host} | speaker: {self.speaker_id}")

    async def speak_async(self, text: str, stop_event):
        async with self._lock:
            try:
                import aiohttp
            except ImportError:
                logger.error("[TTS/voicevox] Instale: pip install aiohttp")
                return

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.host}/audio_query",
                        params={"text": text, "speaker": self.speaker_id},
                        headers={"Connection": "close"}
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"[TTS/voicevox] audio_query HTTP {resp.status}")
                            logger.warning("Certifique-se que o VOICEVOX está aberto.")
                            return
                        query = await resp.json()

                    query["speedScale"]      = self.speed
                    query["pitchScale"]      = self.pitch
                    query["intonationScale"] = self.intonation
                    query["volumeScale"]     = self.volume

                    async with session.post(
                        f"{self.host}/synthesis",
                        params={"speaker": self.speaker_id},
                        json=query,
                        headers={"Connection": "close"}
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"[TTS/voicevox] synthesis HTTP {resp.status}")
                            return
                        wav_bytes = await resp.read()

                if not stop_event.is_set():
                    await _play_bytes(wav_bytes, ".wav", stop_event)

            except aiohttp.ClientConnectorError:
                logger.error("[TTS/voicevox] Não foi possível conectar. VOICEVOX está rodando?")
            except Exception as e:
                logger.error(f"[TTS/voicevox] Erro: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Engine: Fish Speech
# ─────────────────────────────────────────────────────────────────────────────

class _FishSpeech:
    """
    Vozes naturais multilíngue via Fish Speech (local, gratuito, offline).
    Instale/inicie o servidor: https://github.com/fishaudio/fish-speech
    Comando para iniciar: uvicorn tools.api_server:app --host 0.0.0.0 --port 50021

    reference_id: ID de uma voz clonada (deixe null para voz padrão).
    """

    def __init__(self, cfg: dict):
        self.host         = cfg.get("host",         "http://localhost:50021")
        self.reference_id = cfg.get("reference_id")
        self.format       = "wav"
        logger.info(f"[TTS/fish-speech] host: {self.host}")

    async def speak_async(self, text: str, stop_event):
        try:
            import aiohttp
        except ImportError:
            logger.error("[TTS/fish-speech] Instale: pip install aiohttp")
            return

        payload = {
            "text":      text,
            "format":    self.format,
            "streaming": False,
        }
        if self.reference_id:
            payload["reference_id"] = self.reference_id

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.host}/v1/tts", json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"[TTS/fish-speech] TTS HTTP {resp.status}")
                        logger.warning("Certifique-se que o Fish Speech server está rodando.")
                        return
                    audio_bytes = await resp.read()

            if not stop_event.is_set():
                await _play_bytes(audio_bytes, ".wav", stop_event)

        except aiohttp.ClientConnectorError:
            logger.error("[TTS/fish-speech] Não foi possível conectar. Servidor rodando?")
        except Exception as e:
            logger.error(f"[TTS/fish-speech] Erro: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TTSEngine — fachada pública
# ─────────────────────────────────────────────────────────────────────────────

_ENGINES = {
    "index-tts2":  (_IndexTTS2,  "index_tts2"),
    "edge-tts":    (_EdgeTTS,    "edge_tts"),
    "voicevox":    (_VoiceVox,   "voicevox"),
    "fish-speech": (_FishSpeech, "fish_speech"),
}


class TTSEngine:
    def __init__(self, cfg: dict):
        self.cfg      = cfg
        self.provider = cfg.get("provider", "edge-tts").lower()
        self._init_mixer()

        if self.provider not in _ENGINES:
            logger.error(
                f"[TTS] Provider '{self.provider}' inválido. "
                f"Opções: {', '.join(_ENGINES)}. Usando edge-tts."
            )
            self.provider = "edge-tts"

        engine_cls, cfg_key = _ENGINES[self.provider]
        self._engine = engine_cls(cfg.get(cfg_key, {}))

    def _init_mixer(self):
        try:
            import pygame
            pygame.mixer.pre_init(44100, -16, 2, 1024)
            pygame.mixer.init()
            logger.info("[TTS] pygame mixer inicializado")
        except Exception as e:
            logger.error(f"[TTS] Erro ao inicializar pygame: {e}")

    async def speak_async(self, text: str, stop_event) -> None:
        await self._engine.speak_async(text, stop_event)

    def stop(self):
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:
            pass

    def estimate_lip_sync(self, text: str, n_frames: int = 40) -> list[float]:
        vowels    = len(re.findall(r'[aeiouáéíóúàèìòùâêîôûãõ]', text.lower()))
        syllables = max(vowels, 1)
        frames    = []
        for i in range(n_frames):
            phase = i / n_frames * syllables * math.pi * 1.5
            val   = max(0.0, math.sin(phase)) * 0.85
            noise = ((hash(text + str(i)) % 100) / 100) * 0.15
            frames.append(min(1.0, val + noise * 0.3))
        fade = max(2, n_frames // 8)
        for i in range(fade):
            t = i / fade
            frames[i]            *= t
            frames[n_frames-1-i] *= t
        return frames
