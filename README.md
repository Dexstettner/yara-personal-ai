# Yara — Personal AI Desktop Assistant

Assistente de IA desktop com avatar animado, voz e personalidade. Roda localmente com Whisper para reconhecimento de fala (STT), múltiplos engines de TTS e suporte a LLMs via Ollama, API da Anthropic ou modelos GGUF locais.

---

## Visão Geral

```
┌──────────────────────────────────────────────────────────────────────┐
│  Electron (frontend)                                                 │
│  ┌──────────────┐   WebSocket   ┌──────────────────────────────────┐ │
│  │ Avatar + UI  │◄─────────────►│  Python Backend (FastAPI)        │ │
│  │ (Renderer)   │               │                                  │ │
│  └──────────────┘               │  STT: faster-whisper | silero    │ │
│                                 │  LLM: Ollama | Anthropic |       │ │
│                                 │       llama-cpp                  │ │
│                                 │  TTS: f5-tts | edge-tts |        │ │
│                                 │       elevenlabs | voicevox |    │ │
│                                 │       fish-speech | chatterbox   │ │
│                                 └──────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

**Fluxo de uma conversa:**
1. Usuário pressiona `Ctrl+Space` ou diz a wake word (ex: "yana")
2. Microfone grava até detectar silêncio
3. Whisper transcreve o áudio localmente (GPU)
4. LLM gera a resposta com personalidade tsundere
5. TTS sintetiza a voz e reproduz com sincronização labial no avatar

---

## Funcionalidades

- Avatar 2D animado com lip-sync estimado e efeitos de partículas
- STT 100% local via **faster-whisper** (VAD por RMS) ou **silero** (VAD neural)
- Wake word configurável — ativa o microfone por voz ("yana" por padrão)
- Suporte a 3 provedores LLM: **Ollama** (local), **Claude** (Anthropic API), **llama-cpp** (GGUF in-process)
- TTS com 6 engines: **f5-tts**, **edge-tts**, **ElevenLabs**, **VOICEVOX**, **Fish Speech**, **Chatterbox**
- Balão de fala com histórico, indicador de digitação e efeito typewriter
- Hotkeys globais configuráveis
- Histórico de conversa com limite configurável
- Sempre visível sobre outras janelas (always-on-top)
- Minimiza para bandeja do sistema
- Painel de debug integrado (texto → LLM → voz / texto → voz direto)
- Suporte a execução do backend via **Docker** (com GPU)

---

## Pré-requisitos

### Sistema

| Requisito | Versão mínima | Notas |
|-----------|--------------|-------|
| Windows | 10 / 11 | Testado em Windows 11 |
| Python | 3.10+ | Recomendado: 3.11 |
| Node.js | 18+ | Para rodar o Electron |
| CUDA Toolkit | 12.1+ | Necessário para GPU (Whisper, f5-tts) |

### Verificar CUDA

```bash
nvcc --version
nvidia-smi
```

### cuDNN via pip (alternativa ao instalador NVIDIA)

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

---

## Instalação

### 1. Clonar o projeto

```bash
git clone <url-do-repositorio>
cd yara-personal-ai
```

### 2. Instalar dependências Node.js

```bash
npm install
```

### 3. Criar ambiente conda (recomendado)

```bash
conda create -n yara python=3.11 -y
conda activate yara
```

### 4. Instalar dependências Python

O `setup_env.py` lê o `config.json` e instala apenas os providers configurados:

```bash
python backend/setup_env.py
```

Ou instale manualmente por provider:

```bash
pip install -r backend/requirements/base.txt
pip install -r backend/requirements/stt_silero.txt    # STT: silero
pip install -r backend/requirements/llm_ollama.txt    # LLM: ollama
pip install -r backend/requirements/tts_f5.txt        # TTS: f5-tts
```

### 5. Configurar o LLM

#### Opção A — Ollama (local, recomendado)

1. Instale o [Ollama](https://ollama.com/)
2. Baixe um modelo:
   ```bash
   ollama pull gemma3
   ```
3. Em `config.json`:
   ```json
   "ai": { "provider": "ollama", "model": "gemma3" }
   ```

#### Opção B — Claude (Anthropic API)

1. Obtenha uma API key em [console.anthropic.com](https://console.anthropic.com/)
2. Em `config.json`:
   ```json
   "ai": { "provider": "anthropic", "api_key": "sk-ant-...", "model": "claude-sonnet-4-6" }
   ```

#### Opção C — llama-cpp (GGUF in-process, sem daemon)

```json
"ai": {
  "provider": "llama-cpp",
  "llama_cpp": {
    "model_path": "models/seu-modelo.gguf",
    "n_gpu_layers": -1,
    "n_ctx": 2048
  }
}
```

---

## Executar

### Modo normal

```bat
start.bat
```

### Modo desenvolvimento (com DevTools)

```bat
start_dev.bat
```

### Modo Docker (backend em container)

```bat
start_docker_dev.bat
```

> Veja a seção [Docker](#docker) para configuração completa.

---

## Configuração (`config.json`)

### `ai` — Modelo de linguagem

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `provider` | string | `"ollama"`, `"anthropic"` ou `"llama-cpp"` |
| `model` | string | Nome do modelo (ex: `"gemma3"`, `"claude-sonnet-4-6"`) |
| `api_key` | string | Chave da Anthropic (deixe `""` para Ollama) |
| `base_url` | string | URL do Ollama (padrão: `http://localhost:11434`) |
| `system_prompt` | string | Personalidade e instruções do assistente |
| `max_tokens` | int | Máximo de tokens na resposta |
| `temperature` | float | Criatividade 0.0–1.0 (padrão: 0.8) |
| `num_gpu` | int | Camadas na GPU Ollama (99 = todas) |
| `num_ctx` | int | Tamanho do contexto em tokens |
| `timeout` | int | Timeout da chamada LLM em segundos |

### `stt` — Reconhecimento de voz

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `provider` | string | `"faster-whisper"` ou `"silero"` |

#### Provider `faster-whisper` — VAD por RMS, sem torch

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `model` | string | `"tiny"`, `"base"`, `"small"`, `"medium"`, `"large-v3"`, `"large-v3-turbo"` |
| `device` | string | `"cuda"` ou `"cpu"` |
| `compute_type` | string | `"float16"` (GPU), `"int8"` (CPU) |
| `language` | string | `"pt"`, `"en"`, etc. |
| `vad_filter` | bool | Filtro de silêncio interno |
| `silence_threshold_ms` | int | ms de silêncio para encerrar |

#### Provider `silero` — VAD neural (mais robusto a ruído)

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `model` | string | Modelo Whisper para transcrição |
| `device` | string | `"cuda"` ou `"cpu"` |
| `vad_threshold` | float | Sensibilidade 0.0–1.0 (padrão: 0.5) |
| `min_silence_ms` | int | Silêncio mínimo para encerrar |

> **Recomendação:** Use `silero` para ambientes com ruído de fundo. Use `faster-whisper` para setups simples sem torch.

#### Wake Word

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `enabled` | bool | Ativa/desativa a wake word |
| `wake_phrases` | array | Frases de ativação (padrão: `["yana"]`) |
| `stop_phrases` | array | Frases de parada (padrão: `["pare", "para"]`) |
| `chunk_duration` | float | Duração dos chunks de escuta em segundos |
| `min_rms` | float | Energia mínima para processar chunk |

### `tts` — Síntese de voz

| `provider` | Descrição | Requisito |
|---|---|---|
| `"f5-tts"` | Flow matching, ~300 MB VRAM, clonagem de voz | torch + CUDA |
| `"edge-tts"` | Vozes Microsoft Neural | Internet |
| `"elevenlabs"` | Vozes premium, API key necessária | Internet + API key |
| `"voicevox"` | Vozes anime japonesas | Servidor VOICEVOX local |
| `"fish-speech"` | Voz multilíngue | Servidor Fish Speech local |
| `"chatterbox"` | Clonagem de voz offline, ~4–7 GB VRAM | torch + CUDA |

**Vozes PT-BR para edge-tts:**
- `pt-BR-ThalitaNeural` — feminino, jovem/casual (padrão)
- `pt-BR-FranciscaNeural` — feminino, profissional
- `pt-BR-AntonioNeural` — masculino

### `app` — Aplicação

| Campo | Descrição |
|-------|-----------|
| `hotkey_listen` | Hotkey para iniciar escuta (padrão: `ctrl+space`) |
| `hotkey_toggle` | Hotkey para mostrar/esconder avatar (padrão: `ctrl+shift+h`) |
| `backend_port` | Porta WebSocket do backend (padrão: 8765) |
| `save_history` | Salvar histórico de conversa |
| `max_history` | Máximo de mensagens no histórico |

---

## TTS Providers

### f5-tts (padrão, recomendado)

Sintetizador de alta qualidade com clonagem de voz via arquivo de referência.

```json
"f5_tts": {
  "device": "cuda",
  "reference_audio": "assets/f5_tts_reference.mp3",
  "ref_text": "Texto falado no áudio de referência.",
  "model": "F5TTS_v1_Base",
  "speed": 0.4
}
```

### ElevenLabs

```json
"elevenlabs": {
  "api_key": "sua-chave",
  "voice_id": "ID_da_voz",
  "model_id": "eleven_flash_v2_5"
}
```

### VOICEVOX (vozes anime, offline)

1. Baixe e instale: [voicevox.hiroshiba.jp](https://voicevox.hiroshiba.jp/)
2. Abra o VOICEVOX antes de iniciar o assistente
3. Configure `"provider": "voicevox"` e `"speaker_id": 2` (Zundamon)
4. Liste todos os speakers: `GET http://localhost:50021/speakers`

### Fish Speech (multilíngue, offline)

1. Clone e configure: [github.com/fishaudio/fish-speech](https://github.com/fishaudio/fish-speech)
2. Inicie o servidor Fish Speech
3. Configure `"provider": "fish-speech"`

### Chatterbox (clonagem offline)

Requer passos de instalação manual — veja `backend/requirements/tts_chatterbox.txt`.

---

## Wake Word

O detector usa o próprio Whisper para transcrever chunks curtos de 2 segundos em background.

- **Ativação:** diga `"yana"` (configurável em `config.json → stt.wake_word.wake_phrases`)
- **Parada:** diga `"pare"` ou `"para"` (interrompe TTS mesmo durante a fala)
- O detector pausa automaticamente enquanto o microfone principal está gravando

---

## Painel de Debug

Clique no ícone ⚙ no canto superior direito do avatar para abrir o painel de debug:

- **Pensar (LLM → voz):** envia texto direto para o LLM e fala a resposta (pula STT)
- **Falar direto:** fala o texto diretamente via TTS (pula STT e LLM)

Os mesmos comandos estão disponíveis via WebSocket:
- `{ "type": "debug_think", "text": "..." }` — texto → LLM → TTS
- `{ "type": "debug_speak", "text": "..." }` — texto → TTS direto

---

## Docker

O backend Python pode rodar em container Docker (com GPU via WSL2).

### Pré-requisitos

- Docker Desktop com suporte GPU habilitado (WSL2 + driver NVIDIA)
- Ollama rodando no host Windows

### Configuração obrigatória antes de usar Docker

No `config.json`, altere a URL do Ollama para acessar o host:
```json
"base_url": "http://host.docker.internal:11434"
```

### Executar

```bat
start_docker_dev.bat
```

Esse script faz build do container, aguarda o health check e inicia o Electron apontando para o backend Docker.

### Logs em tempo real

```bash
docker compose logs -f backend
```

### Áudio no Docker (microfone e speaker)

O Docker não acessa dispositivos de áudio diretamente no Windows. Para habilitar:

1. Instale o [PulseAudio para Windows](https://pgaskin.net/pulseaudio-win32/)
2. Configure `default.pa` com: `load-module module-native-protocol-tcp auth-anonymous=1`
3. O `docker-compose.yml` já aponta `PULSE_SERVER=tcp:host.docker.internal:4713`

---

## Estrutura do Projeto

```
yara-personal-ai/
├── app/
│   ├── main.js              # Processo principal Electron + spawn/conexão ao backend
│   ├── preload.js           # Bridge segura Electron ↔ Renderer
│   └── renderer/
│       ├── index.html       # Interface principal
│       ├── avatar.js        # Renderização, animações, lip-sync
│       ├── ui.js            # Lógica de UI e WebSocket client
│       └── style.css
├── backend/
│   ├── main.py              # Servidor FastAPI/WebSocket + orquestração do pipeline
│   ├── wake_word.py         # Detector de wake word via Whisper
│   ├── stt/                 # Package STT
│   │   ├── faster_whisper.py
│   │   └── silero.py
│   ├── tts/                 # Package TTS
│   │   ├── f5_tts.py
│   │   ├── edge_tts.py
│   │   ├── elevenlabs.py
│   │   ├── voicevox.py
│   │   ├── fish_speech.py
│   │   └── chatterbox.py
│   ├── llm/                 # Package LLM
│   │   ├── ollama.py
│   │   ├── anthropic.py
│   │   └── llama_cpp.py
│   ├── requirements/        # Deps por provider
│   │   ├── base.txt
│   │   ├── stt_silero.txt
│   │   ├── stt_faster_whisper.txt
│   │   ├── tts_f5.txt
│   │   ├── tts_edge.txt
│   │   ├── tts_elevenlabs.txt
│   │   ├── tts_chatterbox.txt
│   │   ├── llm_ollama.txt
│   │   ├── llm_anthropic.txt
│   │   └── llm_llama_cpp.txt
│   └── setup_env.py         # Instala apenas os providers do config.json
├── assets/
│   ├── thinking.png         # Imagem do avatar
│   └── f5_tts_reference.mp3 # Áudio de referência para f5-tts
├── Dockerfile               # Backend containerizado
├── docker-compose.yml       # Orquestração com GPU
├── config.json              # Configuração central
├── start.bat                # Inicialização normal
├── start_dev.bat            # Inicialização modo dev
└── start_docker_dev.bat     # Inicialização com backend Docker
```

---

## Solução de Problemas

### Backend não inicia / erro de porta

```bash
netstat -ano | findstr :8765
taskkill /PID <pid> /F
```

### Whisper lento / sem GPU

```python
python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"
```

Se retornar lista vazia, reinstale com suporte CUDA ou use `"device": "cpu"`.

### numpy: "Unable to compare versions" / found=None

O numpy foi instalado via conda sem metadados pip. Solução:

```bash
conda remove -n yara numpy --force -y
pip install numpy
```

### Ollama: modelo não encontrado

```bash
ollama list
ollama pull gemma3
```

### Wake word não ativa

1. Verifique se `stt.wake_word.enabled` é `true` no `config.json`
2. Confirme que o Whisper carregou (aguarda até 60s após startup)
3. Verifique nos logs: `[WakeWord] Ativo | ativação: ['yana']`
4. Teste com `min_rms` menor (ex: `0.004`) se o microfone for fraco

---

## Requisitos de Hardware

| Componente | Mínimo | Recomendado |
|-----------|--------|-------------|
| GPU | GTX 1060 6GB | RTX 3060+ |
| VRAM | 4 GB | 8 GB+ (f5-tts + Whisper simultâneos) |
| RAM | 8 GB | 16 GB+ |
| Microfone | Qualquer | Headset com cancelamento de ruído |
