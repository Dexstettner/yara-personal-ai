# Yara — Personal AI Desktop Assistant

Assistente de IA desktop com avatar animado, voz e personalidade. Roda localmente com Whisper para reconhecimento de fala (STT), múltiplos engines de TTS e suporte a LLMs via Ollama ou API da Anthropic.

---

## Visão Geral

```
┌──────────────────────────────────────────────────────────────────┐
│  Electron (frontend)                                             │
│  ┌──────────────┐   WebSocket   ┌────────────────────────────┐  │
│  │ Avatar + UI  │◄─────────────►│  Python Backend (FastAPI)  │  │
│  │ (Renderer)   │               │                            │  │
│  └──────────────┘               │  STT: faster-whisper       │  │
│                                 │  LLM: Ollama / Anthropic   │  │
│                                 │  TTS: edge-tts / voicevox  │  │
│                                 │       / fish-speech        │  │
│                                 └────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**Fluxo de uma conversa:**
1. Usuário pressiona `Ctrl+Space` (ou diz a wake word)
2. Microfone grava até detectar silêncio por ~400 ms
3. Whisper transcreve o áudio localmente (GPU)
4. LLM gera a resposta (Ollama local ou Claude via API)
5. TTS sintetiza a voz e reproduz com sincronização labial no avatar

---

## Funcionalidades

- Avatar 2D animado com sincronização labial estimada
- STT 100% local via **faster-whisper** + CUDA (GPU)
- Suporte a múltiplos LLMs: **Ollama** (local) ou **Claude** (Anthropic)
- TTS com 3 engines: **edge-tts** (Microsoft Neural, online), **VOICEVOX** (anime, offline) ou **Fish Speech** (multilíngue, offline)
- Wake word configurável (padrão: "yana")
- Hotkeys globais configuráveis
- Histórico de conversa com limite configurável
- Sempre visível sobre outras janelas (always-on-top)
- Minimiza para bandeja do sistema

---

## Pré-requisitos

### Sistema

| Requisito | Versão mínima | Notas |
|-----------|--------------|-------|
| Windows | 10 / 11 | Testado em Windows 11 |
| Python | 3.10+ | Recomendado: 3.11 |
| Node.js | 18+ | Para rodar o Electron |
| CUDA Toolkit | 12.1+ | Necessário para GPU no Whisper |
| cuDNN | 8.x ou 9.x | Compatível com CUDA 12.x |

### Verificar versão CUDA

```bash
nvcc --version
nvidia-smi
```

### Instalar cuDNN via pip (alternativa ao instalador NVIDIA)

Se não tiver cuDNN instalado globalmente, pode instalar via pip junto com as dependências Python:

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

---

## Instalação

### 1. Clonar / baixar o projeto

```bash
git clone <url-do-repositorio>
cd yara-personal-ai
```

### 2. Instalar dependências Node.js

```bash
npm install
```

### 3. Criar e ativar ambiente virtual Python (recomendado)

```bash
python -m venv venv
venv\Scripts\activate
```

### 4. Instalar dependências Python

```bash
pip install -r backend/requirements.txt
```

> **Se usar GPU (CUDA 12.1):** confirme que `ctranslate2` foi instalado com suporte a CUDA. Teste com:
> ```python
> import ctranslate2; print(ctranslate2.get_supported_compute_types("cuda"))
> ```

### 5. Configurar o LLM

#### Opção A — Ollama (local, recomendado)

1. Instale o [Ollama](https://ollama.com/)
2. Baixe um modelo:
   ```bash
   ollama pull gemma3
   ```
3. Em `config.json`, defina:
   ```json
   "ai": { "provider": "ollama", "model": "gemma3" }
   ```

#### Opção B — Claude (Anthropic API)

1. Obtenha uma API key em [console.anthropic.com](https://console.anthropic.com/)
2. Em `config.json`, defina:
   ```json
   "ai": { "provider": "anthropic", "api_key": "sk-ant-...", "model": "claude-sonnet-4-6" }
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

Os logs do backend aparecem no terminal com o prefixo `[Backend]`.

---

## Configuração (`config.json`)

### `ai` — Modelo de linguagem

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `provider` | string | `"ollama"` ou `"anthropic"` |
| `model` | string | Nome do modelo (ex: `"gemma3"`, `"claude-sonnet-4-6"`) |
| `api_key` | string | Chave da Anthropic (deixe `""` para Ollama) |
| `base_url` | string | URL do Ollama (padrão: `http://localhost:11434`) |
| `system_prompt` | string | Personalidade e instruções do assistente |
| `max_tokens` | int | Máximo de tokens na resposta (padrão: 1024) |
| `temperature` | float | Criatividade da resposta, 0.0–1.0 (padrão: 0.8) |

### `stt` — Reconhecimento de voz

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `model` | string | Modelo Whisper: `"tiny"`, `"base"`, `"small"`, `"medium"`, `"large-v3"`, `"distil-large-v3"` |
| `language` | string | Idioma do áudio (ex: `"pt"`, `"en"`) |
| `device` | string | `"cuda"` (GPU) ou `"cpu"` |
| `compute_type` | string | `"float16"` (GPU rápido), `"int8"` (CPU), `"float32"` |
| `vad_filter` | bool | Filtragem de silêncio via VAD (recomendado: `true`) |
| `silence_threshold_ms` | int | ms de silêncio para encerrar gravação (padrão: 400) |

> **Modelos recomendados:**
> - `distil-large-v3` — melhor qualidade + velocidade para PT-BR com GPU
> - `small` — bom equilíbrio para CPU

### `tts` — Síntese de voz

| Campo | Valor | Descrição |
|-------|-------|-----------|
| `provider` | `"edge-tts"` | Voz neural Microsoft (requer internet) |
| `provider` | `"voicevox"` | Vozes anime japonesas (requer [VOICEVOX](https://voicevox.hiroshiba.jp/) rodando) |
| `provider` | `"fish-speech"` | Voz natural multilíngue (requer [Fish Speech](https://github.com/fishaudio/fish-speech) rodando) |

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
| `max_history` | Máximo de mensagens no histórico (padrão: 50) |

---

## TTS providers opcionais

### VOICEVOX (vozes anime, offline)

1. Baixe e instale: [voicevox.hiroshiba.jp](https://voicevox.hiroshiba.jp/)
2. Abra o VOICEVOX **antes** de iniciar o assistente
3. Configure `"provider": "voicevox"` no `config.json`
4. Speakers populares: Zundamon (2), Shikoku Metan (1), Kasukabe Tsumugi (13)
5. Liste todos: `GET http://localhost:50021/speakers`

### Fish Speech (multilíngue, offline)

1. Clone e configure: [github.com/fishaudio/fish-speech](https://github.com/fishaudio/fish-speech)
2. Inicie o servidor: `uvicorn tools.api_server:app --host 0.0.0.0 --port 50021`
3. Configure `"provider": "fish-speech"` no `config.json`

---

## Wake Word

O detector de wake word usa o próprio Whisper para transcrever chunks curtos de 2 segundos em background.

Frases padrão (configuráveis em `config.json → stt`):
- **Ativação:** `"yana"`
- **Parada:** `"pare"`, `"para"`, `"yana pare"`

---

## Estrutura do Projeto

```
yara-personal-ai/
├── app/
│   ├── main.js          # Processo principal Electron + spawn do backend
│   ├── preload.js       # Bridge segura Electron ↔ Renderer
│   └── renderer/
│       ├── index.html   # Interface principal
│       ├── avatar.js    # Renderização e animação do avatar
│       ├── ui.js        # Lógica de UI e WebSocket client
│       └── style.css
├── backend/
│   ├── main.py          # Servidor FastAPI/WebSocket + orquestração
│   ├── stt.py           # STT: faster-whisper
│   ├── tts.py           # TTS: edge-tts / voicevox / fish-speech
│   ├── llm.py           # LLM: Anthropic / Ollama
│   ├── wake_word.py     # Detector de wake word
│   └── requirements.txt
├── assets/
│   └── AI_Profile.png   # Imagem do avatar
├── config.json          # Configuração central
├── start.bat            # Inicialização normal
└── start_dev.bat        # Inicialização modo dev
```

---

## Solução de Problemas

### Backend não inicia / erro de porta

O `start.bat` mata automaticamente processos na porta 8765. Se persistir:
```bash
netstat -ano | findstr :8765
taskkill /PID <pid> /F
```

### Whisper lento / sem GPU

Confirme que `device: "cuda"` está no config e que o CTranslate2 tem suporte CUDA:
```python
python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"
```
Se retornar lista vazia, reinstale com suporte CUDA ou troque para `"device": "cpu"`.

### Caracteres com acento aparecem errados no terminal

Execute com UTF-8 forçado:
```bash
set PYTHONUTF8=1
python backend/main.py
```
Isso já é configurado automaticamente quando iniciado pelo Electron.

### Ollama: modelo não encontrado

```bash
ollama list          # lista modelos instalados
ollama pull gemma3   # baixa o modelo
```

---

## Requisitos de Hardware (recomendado)

| Componente | Mínimo | Recomendado |
|-----------|--------|-------------|
| GPU | GTX 1060 6GB | RTX 3060+ |
| VRAM | 4 GB | 8 GB+ |
| RAM | 8 GB | 16 GB+ |
| Microfone | Qualquer | Headset com cancelamento de ruído |
