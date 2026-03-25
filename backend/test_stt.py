"""
test_stt.py -- Testa o pipeline STT (Whisper) de forma isolada.
Util para comparar providers, ajustar modelo e calibrar threshold de silencio.

Uso:
  python test_stt.py                              # usa config.json
  python test_stt.py --provider faster-whisper
  python test_stt.py --provider silero
  python test_stt.py --model medium               # sobrescreve o modelo
  python test_stt.py --model large-v3-turbo --device cuda
  python test_stt.py --rounds 3                   # 3 gravacoes consecutivas
  python test_stt.py --compare                    # grava UMA vez, transcreve com ambos
  python test_stt.py --file caminho.wav           # transcreve arquivo existente (sem gravar)
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Garante que o package backend seja encontrado ao rodar de qualquer diretorio
sys.path.insert(0, str(Path(__file__).parent))

ROOT     = Path(__file__).parent.parent
CFG_FILE = ROOT / "config.json"


# ─────────────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not CFG_FILE.exists():
        print(f"[ERRO] config.json nao encontrado em {CFG_FILE}")
        sys.exit(1)
    with open(CFG_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_provider_cfg(cfg_stt: dict, args: argparse.Namespace) -> dict:
    """Aplica overrides CLI sobre o config do provider ativo."""
    provider  = (args.provider or cfg_stt.get("provider", "faster-whisper")).lower()
    cfg_key   = provider.replace("-", "_")
    prov_cfg  = cfg_stt.get(cfg_key, {}).copy()

    if args.model:
        prov_cfg["model"] = args.model
    if args.device:
        prov_cfg["device"] = args.device

    return provider, prov_cfg


def make_engine(provider: str, prov_cfg: dict, cfg_audio: dict):
    """Instancia o provider STT diretamente (sem a fachada STTEngine)."""
    if provider == "faster-whisper":
        from stt.faster_whisper import FasterWhisperSTT
        return FasterWhisperSTT(prov_cfg, cfg_audio)
    if provider == "silero":
        from stt.silero import SileroSTT
        return SileroSTT(prov_cfg, cfg_audio)
    print(f"[ERRO] Provider desconhecido: '{provider}'. Opcoes: faster-whisper, silero")
    sys.exit(1)


def wait_model(engine, timeout: float = 60.0) -> bool:
    """Aguarda o modelo carregar (background thread). Retorna False se falhar."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if engine.model is not None:
            return True
        # Verifica se houve erro de carregamento
        err = getattr(engine, "_load_error", None) or getattr(engine, "_whisper_error", None)
        if err:
            print(f"[ERRO] Modelo nao carregou: {err}")
            return False
        time.sleep(0.5)
        print(".", end="", flush=True)
    print()
    print("[ERRO] Timeout aguardando modelo.")
    return False


def record_audio(engine) -> "np.ndarray":
    """Grava audio do microfone e retorna o array. Lida com KeyboardInterrupt."""
    import numpy as np
    print("\nGravando... (fale algo, pare ao ficar em silencio)")
    print("  Pressione Ctrl+C para encerrar manualmente.\n")
    try:
        audio = engine.record_until_silence()
    except KeyboardInterrupt:
        engine.stop_recording()
        print("\n[Gravacao interrompida pelo usuario]")
        audio = np.zeros(1, dtype="float32")
    return audio


def transcribe_timed(engine, audio) -> tuple[str, float]:
    """Transcreve o audio e retorna (texto, latencia_ms)."""
    t0   = time.monotonic()
    text = engine.transcribe(audio)
    ms   = (time.monotonic() - t0) * 1000
    return text, ms


def print_result(provider: str, text: str, latency_ms: float) -> None:
    pad = " " * max(0, 14 - len(provider))
    result = f'"{text}"' if text else "(sem transcricao)"
    print(f"  [{provider}]{pad}  {latency_ms:6.0f} ms  ->  {result}")


# ─────────────────────────────────────────────────────────────────────────────

def run_single(args: argparse.Namespace, cfg: dict) -> None:
    """Modo padrao: grava e transcreve com um provider."""
    provider, prov_cfg = build_provider_cfg(cfg["stt"], args)
    rounds = args.rounds

    print(f"\n--- STT Test | provider: {provider} | model: {prov_cfg.get('model', '?')} ---")

    engine = make_engine(provider, prov_cfg, cfg.get("audio", {}))

    print("Carregando modelo", end="", flush=True)
    if not wait_model(engine):
        sys.exit(1)
    print(f" ok ({prov_cfg.get('model', '?')})\n")

    latencies: list[float] = []

    for i in range(rounds):
        if rounds > 1:
            print(f"--- Round {i + 1}/{rounds} ---")

        audio = record_audio(engine)
        if len(audio) < 100:
            print("  (audio muito curto, ignorado)\n")
            continue

        print(f"  {len(audio) / cfg['audio'].get('sample_rate', 16000):.1f}s gravados — transcrevendo...")
        text, ms = transcribe_timed(engine, audio)
        latencies.append(ms)
        print_result(provider, text, ms)
        print()

    if len(latencies) > 1:
        avg = sum(latencies) / len(latencies)
        print(f"--- Resumo: {len(latencies)} rounds | media {avg:.0f} ms ---\n")


def run_compare(args: argparse.Namespace, cfg: dict) -> None:
    """
    Modo comparacao: grava UMA vez com faster-whisper,
    transcreve o mesmo audio com ambos os providers.
    """
    providers_to_test = ["faster-whisper", "silero"]
    cfg_audio         = cfg.get("audio", {})
    cfg_stt           = cfg["stt"]

    print(f"\n--- STT Compare: {' vs '.join(providers_to_test)} ---\n")

    # Inicializa ambos os engines
    engines: dict[str, object] = {}
    for p in providers_to_test:
        cfg_key  = p.replace("-", "_")
        prov_cfg = cfg_stt.get(cfg_key, {}).copy()
        if args.model:
            prov_cfg["model"] = args.model
        engines[p] = make_engine(p, prov_cfg, cfg_audio)

    # Aguarda todos carregarem
    print("Carregando modelos", end="", flush=True)
    for p, eng in engines.items():
        if not wait_model(eng):
            print(f"\n[ERRO] Falha ao carregar provider '{p}'")
            sys.exit(1)
    print(" ok\n")

    # Grava UMA vez com o primeiro provider (so para capturar o audio)
    first_engine = engines[providers_to_test[0]]
    audio = record_audio(first_engine)

    if len(audio) < 100:
        print("(audio muito curto)")
        return

    sr       = cfg_audio.get("sample_rate", 16000)
    duration = len(audio) / sr
    print(f"  {duration:.1f}s gravados — transcrevendo com ambos os providers...\n")

    # Transcreve o mesmo audio com cada provider
    print(f"  {'Provider':<20}  {'Latencia':>8}  Resultado")
    print(f"  {'-'*20}  {'-'*8}  {'-'*40}")

    for p, eng in engines.items():
        text, ms = transcribe_timed(eng, audio)
        print_result(p, text, ms)

    print()


def run_file(args: argparse.Namespace, cfg: dict) -> None:
    """Modo arquivo: transcreve um .wav existente sem gravar."""
    import numpy as np
    import soundfile as sf

    wav_path = Path(args.file)
    if not wav_path.exists():
        print(f"[ERRO] Arquivo nao encontrado: {wav_path}")
        sys.exit(1)

    provider, prov_cfg = build_provider_cfg(cfg["stt"], args)

    print(f"\n--- STT File | provider: {provider} | arquivo: {wav_path.name} ---\n")

    audio, file_sr = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]

    target_sr = cfg.get("audio", {}).get("sample_rate", 16000)
    if file_sr != target_sr:
        print(f"[AVISO] Sample rate do arquivo ({file_sr} Hz) != esperado ({target_sr} Hz).")
        print("  Resampling... ", end="", flush=True)
        import resampy
        audio = resampy.resample(audio, file_sr, target_sr)
        print("ok\n")

    print(f"  {len(audio) / target_sr:.1f}s de audio carregado")

    engine = make_engine(provider, prov_cfg, cfg.get("audio", {}))
    print("Carregando modelo", end="", flush=True)
    if not wait_model(engine):
        sys.exit(1)
    print(" ok\n")

    print("  Transcrevendo...")
    text, ms = transcribe_timed(engine, audio)
    print_result(provider, text, ms)
    print()


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Testa o pipeline STT de forma isolada.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--provider", help="Provider STT: faster-whisper | silero")
    parser.add_argument("--model",    help="Modelo Whisper: large-v3-turbo | medium | small | base")
    parser.add_argument("--device",   help="Dispositivo: cpu | cuda")
    parser.add_argument("--rounds",   type=int, default=1, help="Numero de gravacoes consecutivas")
    parser.add_argument("--compare",  action="store_true", help="Compara faster-whisper vs silero com o mesmo audio")
    parser.add_argument("--file",     help="Transcreve um arquivo .wav existente (sem gravar)")
    args = parser.parse_args()

    cfg = load_config()

    if args.file:
        run_file(args, cfg)
    elif args.compare:
        run_compare(args, cfg)
    else:
        run_single(args, cfg)


if __name__ == "__main__":
    main()
