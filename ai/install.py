"""Установка ИИ-сервиса одной командой:  python ai/install.py

Создаёт окружение ai/.venv, ставит библиотеки, скачивает веса моделей в ai/weights
и модель для Ollama. Интернет нужен только здесь; запущенный сервис в сеть не ходит.

    python ai/install.py --stub     только режим заглушки (без моделей и видеокарты)
    python ai/install.py --cpu      без видеокарты (медленно, для проверки)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request

from _setup import (
    AI_DIR,
    IS_WINDOWS,
    VENV_DIR,
    WEIGHTS_DIR,
    ensure_ollama_running,
    fail,
    find_ollama,
    has_model,
    ollama_models,
    venv_python,
)

ASSETS_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0"
DEFAULT_TORCH_INDEX = "https://download.pytorch.org/whl/cu128"  # CUDA 12.8: нужна для RTX 50xx
DEFAULT_DETECTOR = "yoloe-26l-seg.pt"
DEFAULT_VLM = "qwen2.5vl:7b"
CLIP_REPO = "laion/CLIP-ViT-B-32-laion2B-s34B-b79K"
CLIP_FILES = ["config.json", "preprocessor_config.json", "model.safetensors"]


def run(command: list[str], **kwargs) -> None:
    print("  $", " ".join(str(c) for c in command), flush=True)
    result = subprocess.run([str(c) for c in command], **kwargs)
    if result.returncode != 0:
        fail(f"команда завершилась с кодом {result.returncode}")


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def download(name: str) -> None:
    target = WEIGHTS_DIR / name
    if target.is_file() and target.stat().st_size > 1_000_000:
        print(f"  уже есть: {target}")
        return
    url = f"{ASSETS_URL}/{name}"
    print(f"  скачиваю {url}", flush=True)
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as file:
            while chunk := response.read(1 << 20):
                file.write(chunk)
    except OSError as exc:
        fail(f"не удалось скачать {url}: {exc}")
    partial.replace(target)


def text_encoder_for(detector: str) -> str:
    return "mobileclip2_b.ts" if "yoloe-26" in detector else "mobileclip_blt.ts"


def main() -> None:
    parser = argparse.ArgumentParser(description="Установка ИИ-сервиса")
    parser.add_argument("--stub", action="store_true", help="только режим заглушки, без моделей")
    parser.add_argument("--cpu", action="store_true", help="ставить torch без поддержки видеокарты")
    parser.add_argument("--torch-index", default=None, help=f"каталог сборок torch (по умолчанию в Windows: {DEFAULT_TORCH_INDEX})")
    parser.add_argument("--detector", default=DEFAULT_DETECTOR, help="файл весов детектора")
    parser.add_argument("--vlm", default=DEFAULT_VLM, help="мультимодальная модель в Ollama")
    parser.add_argument("--skip-ollama", action="store_true", help="не скачивать модель для Ollama")
    args = parser.parse_args()

    if not (3, 10) <= sys.version_info[:2] <= (3, 13):
        fail(f"нужен Python 3.10–3.13, запущен {sys.version.split()[0]}")

    step("Окружение Python")
    python = venv_python()
    if not python.is_file():
        run([sys.executable, "-m", "venv", VENV_DIR])
    pip = [python, "-m", "pip", "install", "--disable-pip-version-check"]
    run([python, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"])

    if args.stub:
        run([*pip, "-r", AI_DIR / "requirements-stub.txt"])
        print("\nГотово. Запуск заглушки:  python ai/run.py --stub")
        return

    step("Библиотеки")
    torch_command = [*pip, "torch", "torchvision"]
    if args.cpu:
        torch_command += ["--index-url", "https://download.pytorch.org/whl/cpu"]
    elif args.torch_index or IS_WINDOWS:
        # в Windows сборка torch из общего каталога пакетов не умеет работать с видеокартой
        torch_command += ["--index-url", args.torch_index or DEFAULT_TORCH_INDEX]
    run(torch_command)
    run([*pip, "-r", AI_DIR / "requirements.txt"])

    step("Веса детектора и модели идентификации")
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    download(args.detector)
    download(text_encoder_for(args.detector))
    clip_dir = WEIGHTS_DIR / "clip"
    if all((clip_dir / name).is_file() for name in CLIP_FILES):
        print(f"  уже есть: {clip_dir}")
    else:
        code = (
            "from huggingface_hub import snapshot_download;"
            f"snapshot_download({CLIP_REPO!r}, local_dir={str(clip_dir)!r}, allow_patterns={CLIP_FILES!r})"
        )
        run([python, "-c", code])

    step("Проверка видеокарты")
    check = (
        "import torch;"
        "ok = torch.cuda.is_available();"
        "print('  torch', torch.__version__, '| видеокарта:', torch.cuda.get_device_name(0) if ok else 'НЕ НАЙДЕНА');"
        "print('  видеопамять, МБ:', torch.cuda.mem_get_info()[1] // 2**20) if ok else None;"
        "raise SystemExit(0 if ok else 3)"
    )
    gpu = subprocess.run([str(python), "-c", check]).returncode == 0
    if not gpu and not args.cpu:
        print(
            "  ВНИМАНИЕ: torch не видит видеокарту. Обновите драйвер NVIDIA и повторите установку, указав\n"
            "  каталог сборок под свою версию CUDA: python ai/install.py --torch-index <адрес с pytorch.org>"
        )

    if not args.skip_ollama:
        step(f"Мультимодальная модель {args.vlm} (Ollama)")
        ollama = find_ollama()
        if ollama is None:
            fail("Ollama не установлена. Установите её с https://ollama.com/download и запустите install.py снова")
        if not ensure_ollama_running():
            fail("Ollama установлена, но не отвечает. Запустите её вручную и повторите")
        if has_model(ollama_models() or [], args.vlm):
            print("  модель уже скачана")
        else:
            run([ollama, "pull", args.vlm])

    print("\nГотово. Запуск сервиса:  python ai/run.py")
    if args.detector != DEFAULT_DETECTOR or args.vlm != DEFAULT_VLM:
        print(f"Нестандартные модели — задайте AI_DETECTOR_WEIGHTS={args.detector} и AI_VLM_MODEL={args.vlm}")


if __name__ == "__main__":
    main()
