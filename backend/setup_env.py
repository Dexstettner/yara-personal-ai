"""
setup_env.py -- Instala apenas as dependencias dos providers ativos.

Le os providers de config.json ou aceita sobrescritas via argumentos.
Providers com conflito de dependencias (f5-tts vs chatterbox) recebem aviso.

Uso:
  python setup_env.py                                    # usa config.json
  python setup_env.py --tts f5-tts                       # sobrescreve TTS
  python setup_env.py --stt faster-whisper --llm ollama --tts edge-tts
  python setup_env.py --check                            # lista sem instalar
  python setup_env.py --all                              # instala tudo

Providers disponiveis:
  --stt  : faster-whisper | silero
  --llm  : anthropic | ollama
  --tts  : edge-tts | f5-tts | chatterbox | voicevox | fish-speech | elevenlabs
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT     = Path(__file__).parent.parent
CFG_FILE = ROOT / "config.json"
REQ_DIR  = Path(__file__).parent / "requirements"

# Providers que conflitam entre si -- nao instalar juntos na mesma env
_CONFLICT_GROUPS: list[set[str]] = [
    {"f5-tts", "chatterbox"},   # transformers version mismatch
]

# Mapeamento provider -> arquivo de requirements
_TTS_REQ: dict[str, str] = {
    "edge-tts":    "tts_edge.txt",
    "f5-tts":      "tts_f5.txt",
    "chatterbox":  "tts_chatterbox.txt",
    "voicevox":    "tts_voicevox.txt",
    "fish-speech": "tts_fish.txt",
    "elevenlabs":  "tts_elevenlabs.txt",
}

_STT_REQ: dict[str, str] = {
    "faster-whisper": "stt_faster_whisper.txt",
    "silero":         "stt_silero.txt",
    # alias legado
    "whisper":        "stt_faster_whisper.txt",
}

_LLM_REQ: dict[str, str] = {
    "anthropic": "llm_anthropic.txt",
    "ollama":    "llm_ollama.txt",
}

# Providers que precisam de passos manuais (nao instaláveis so via pip)
_MANUAL_STEPS: dict[str, list[str]] = {
    "chatterbox": [
        "  [ATENCAO] Chatterbox requer passos manuais ANTES deste script:",
        "     1. conda install -c conda-forge pynini",
        "     2. pip install chatterbox-tts --no-deps",
        "     3. Execute este script novamente para as demais dependencias.",
    ],
}


# -----------------------------------------------------------------------------

def load_config() -> dict:
    if not CFG_FILE.exists():
        print(f"[AVISO] {CFG_FILE} nao encontrado -- usando defaults.")
        return {}
    with open(CFG_FILE, encoding="utf-8") as f:
        return json.load(f)


def resolve_providers(args: argparse.Namespace, cfg: dict) -> dict[str, str]:
    """Retorna {'stt': '...', 'llm': '...', 'tts': '...'} com precedencia CLI > config."""
    return {
        "stt": (args.stt or cfg.get("stt", {}).get("provider", "whisper")).lower(),
        "llm": (args.llm or cfg.get("ai",  {}).get("provider", "ollama")).lower(),
        "tts": (args.tts or cfg.get("tts", {}).get("provider", "edge-tts")).lower(),
    }


def check_conflicts(providers: dict[str, str]) -> list[str]:
    """Retorna lista de mensagens de conflito, ou lista vazia."""
    active = set(providers.values())
    warnings = []
    for group in _CONFLICT_GROUPS:
        hit = active & group
        if len(hit) > 1:
            warnings.append(
                f"  [CONFLITO] {' e '.join(sorted(hit))} nao devem estar na mesma env.\n"
                f"     Crie envs conda separadas ou escolha apenas um provider por vez."
            )
    return warnings


def collect_req_files(providers: dict[str, str]) -> list[tuple[str, Path]]:
    """Retorna lista de (nome, Path) com os arquivos de requirements a instalar."""
    files: list[tuple[str, Path]] = [("base", REQ_DIR / "base.txt")]

    for req_map, key in [(_STT_REQ, "stt"), (_LLM_REQ, "llm"), (_TTS_REQ, "tts")]:
        provider = providers[key]
        filename = req_map.get(provider)
        if filename:
            files.append((provider, REQ_DIR / filename))
        else:
            print(f"  [AVISO] Provider '{provider}' ({key.upper()}) desconhecido -- ignorado.")

    return files


def has_installable_deps(req_file: Path) -> bool:
    """Retorna True se o arquivo tem ao menos uma linha de dep instalavel (nao comentario)."""
    for line in req_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


def pip_install(req_file: Path) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [ERRO] Falha ao instalar {req_file.name} (codigo {result.returncode})")
        sys.exit(result.returncode)


# -----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instala dependencias apenas dos providers ativos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--stt",   help="Provider STT  (ex: faster-whisper, silero)")
    parser.add_argument("--llm",   help="Provider LLM  (ex: ollama, anthropic)")
    parser.add_argument("--tts",   help="Provider TTS  (ex: f5-tts, edge-tts, chatterbox)")
    parser.add_argument("--check", action="store_true", help="Lista o que seria instalado, sem instalar")
    parser.add_argument("--all",   action="store_true", help="Instala todos os providers")
    args = parser.parse_args()

    cfg       = load_config()
    providers = resolve_providers(args, cfg)

    print("\n==============================================")
    print("  Yara -- Configuracao de Ambiente")
    print("==============================================")
    print(f"  STT : {providers['stt']}")
    print(f"  LLM : {providers['llm']}")
    print(f"  TTS : {providers['tts']}")

    # Avisos de conflito
    conflicts = check_conflicts(providers)
    if conflicts:
        print()
        for msg in conflicts:
            print(msg)

    # Avisos de instalacao manual
    for key, provider in providers.items():
        if provider in _MANUAL_STEPS:
            print()
            for line in _MANUAL_STEPS[provider]:
                print(line)

    # Coleta arquivos (ou todos se --all)
    if args.all:
        req_files = [("tudo", f) for f in sorted(REQ_DIR.glob("*.txt"))]
    else:
        req_files = collect_req_files(providers)

    print("\n----------------------------------------------")
    print("  Requirements a instalar:")
    for name, path in req_files:
        installable = has_installable_deps(path)
        status = "" if installable else "  (sem deps pip)"
        print(f"    {name:20s} <- {path.name}{status}")

    if args.check:
        print("\n  [--check] Nada foi instalado.")
        print("  Execute sem --check para instalar.\n")
        return

    if conflicts:
        print("\n  Continue mesmo com conflito? [s/N] ", end="", flush=True)
        resp = input().strip().lower()
        if resp not in ("s", "sim", "y", "yes"):
            print("  Instalacao cancelada.")
            sys.exit(0)

    print()
    for name, path in req_files:
        if has_installable_deps(path):
            print(f"  > Instalando {name} ({path.name}) ...")
            pip_install(path)
        else:
            print(f"  ok {name} -- sem deps pip adicionais.")

    print("\n==============================================")
    print("  Ambiente configurado com sucesso!")
    print("==============================================\n")


if __name__ == "__main__":
    main()
