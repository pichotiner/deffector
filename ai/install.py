"""Установка ИИ-сервиса одной командой:  python ai/install.py

Создаёт окружение ai/.venv, ставит библиотеки, скачивает веса моделей в ai/weights
и модель для Ollama. Интернет нужен только здесь; запущенный сервис в сеть не ходит.

    python ai/install.py --stub     только режим заглушки (без моделей и видеокарты)
    python ai/install.py --cpu      без видеокарты (медленно, для проверки)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

from _setup import (
    AI_DIR,
    INSTALLED_FILE,
    IS_WINDOWS,
    PY_MAX,
    PY_MIN,
    VENV_DIR,
    WEIGHTS_DIR,
    base_python,
    ensure_ollama_running,
    fail,
    find_ollama,
    has_model,
    ollama_models,
    venv_ok,
    venv_python,
)

DEFAULT_TORCH_INDEX = "https://download.pytorch.org/whl/cu128"  # CUDA 12.8: нужна для RTX 50xx
DEFAULT_VLM = "qwen2.5vl:7b"
# версии, проверенные на RTX 5070 (Windows 11, 13.11): torch 2.11.0+cu128
TORCH_PACKAGES = ["torch==2.11.0", "torchvision==0.26.0"]
FREE_GB_NEEDED = 8  # torch и библиотеки ~5 ГБ, веса ~1,2 ГБ (модель Ollama — отдельно, ~6 ГБ)
# Модели с Hugging Face: папка в ai/weights -> (репозиторий, нужные файлы)
HF_MODELS = {
    "owlv2": (
        "google/owlv2-base-patch16-ensemble",
        ["config.json", "preprocessor_config.json", "model.safetensors", "tokenizer_config.json",
         "vocab.json", "merges.txt", "special_tokens_map.json"],
    ),
    "clip": (
        "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        ["config.json", "preprocessor_config.json", "model.safetensors"],
    ),
}


def run(command: list[str], hint: str = "", **kwargs) -> None:
    print("  $", subprocess.list2cmdline([str(c) for c in command]), flush=True)
    result = subprocess.run([str(c) for c in command], **kwargs)
    if result.returncode != 0:
        fail(f"команда завершилась с кодом {result.returncode}" + (f". {hint}" if hint else ""))


NET_HINT = "Проверьте интернет (он нужен только для установки) и запустите install.py снова"


def torch_state(python) -> int:
    """0 — torch с CUDA, 1 — torch без CUDA, иное — torch не установлен."""
    code = "import torch, sys; sys.exit(0 if torch.version.cuda else 1)"
    return subprocess.run([str(python), "-c", code], capture_output=True).returncode


def mark_installed(mode: str, vlm: str) -> None:
    INSTALLED_FILE.write_text(json.dumps({"mode": mode, "vlm": vlm}, ensure_ascii=False), encoding="utf-8")


def step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Установка ИИ-сервиса")
    parser.add_argument("--stub", action="store_true", help="только режим заглушки, без моделей")
    parser.add_argument("--cpu", action="store_true", help="ставить torch без поддержки видеокарты")
    parser.add_argument("--torch-index", default=None, help=f"каталог сборок torch (по умолчанию в Windows: {DEFAULT_TORCH_INDEX})")
    parser.add_argument("--vlm", default=DEFAULT_VLM, help="мультимодальная модель в Ollama")
    parser.add_argument("--skip-ollama", action="store_true", help="не скачивать модель для Ollama")
    args = parser.parse_args()

    versions = f"{PY_MIN[0]}.{PY_MIN[1]}–{PY_MAX[0]}.{PY_MAX[1]}"
    if not args.stub:
        # то, что иначе всплывёт только через полчаса установки
        if not args.skip_ollama and find_ollama() is None:
            fail("Ollama не установлена. Установите её обычным установщиком с https://ollama.com/download "
                 "и запустите install.py снова")
        free_gb = shutil.disk_usage(AI_DIR).free / 2**30
        if free_gb < FREE_GB_NEEDED:
            fail(f"на диске с папкой ai свободно {free_gb:.1f} ГБ, нужно не меньше {FREE_GB_NEEDED} ГБ "
                 "(и ещё ~6 ГБ там, где Ollama хранит модели)")

    step("Окружение Python")
    python = venv_python()
    if python.is_file() and not venv_ok(python):
        print(f"  окружение {VENV_DIR} неполное или на другой версии Python — создаю заново", flush=True)
        shutil.rmtree(VENV_DIR)
    if not python.is_file():
        creator = base_python()
        if creator is None:
            fail(f"нужен Python {versions}, запущен {sys.version.split()[0]}. "
                 "Установите Python 3.12 с python.org и запустите install.py снова")
        run([*creator, "-m", "venv", VENV_DIR])
    INSTALLED_FILE.unlink(missing_ok=True)  # отметка появится, только если установка дойдёт до конца
    pip = [python, "-m", "pip", "install", "--disable-pip-version-check"]
    run([python, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], hint=NET_HINT)

    if args.stub:
        run([*pip, "-r", AI_DIR / "requirements-stub.txt"], hint=NET_HINT)
        mark_installed("stub", "")
        print("\nГотово. Запуск заглушки:  python ai/run.py --stub")
        return

    step("Библиотеки")
    torch_command = [*pip, "--no-cache-dir", *TORCH_PACKAGES]  # без кэша: минус ~3 ГБ на диске C
    state = torch_state(python)
    if (not args.cpu and state == 1) or ((args.cpu or args.torch_index) and state == 0):
        torch_command.append("--force-reinstall")  # иначе pip оставит уже стоящую сборку не той версии CUDA
    if args.cpu:
        torch_command += ["--index-url", "https://download.pytorch.org/whl/cpu"]
    elif args.torch_index or IS_WINDOWS:
        # в Windows сборка torch из общего каталога пакетов не умеет работать с видеокартой
        torch_command += ["--index-url", args.torch_index or DEFAULT_TORCH_INDEX]
    run(torch_command, hint=NET_HINT)
    run([*pip, "-r", AI_DIR / "requirements.txt"], hint=NET_HINT)

    step("Веса детектора и модели идентификации")
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    for folder, (repo, files) in HF_MODELS.items():
        target = WEIGHTS_DIR / folder
        if all((target / name).is_file() for name in files):
            print(f"  уже есть: {target}")
            continue
        code = (
            "from huggingface_hub import snapshot_download;"
            f"snapshot_download({repo!r}, local_dir={str(target)!r}, allow_patterns={files!r})"
        )
        run([python, "-c", code], hint=NET_HINT)

    step("Проверка видеокарты")
    check = (
        "import torch;"
        "ok = torch.cuda.is_available();"
        "print('  torch', torch.__version__, '| видеокарта:', torch.cuda.get_device_name(0) if ok else 'НЕ НАЙДЕНА');"
        "print('  видеопамять, МБ:', torch.cuda.mem_get_info()[1] // 2**20) if ok else None;"
        "raise SystemExit(0 if ok else 3)"
    )
    gpu = subprocess.run([str(python), "-c", check]).returncode == 0
    no_gpu_message = (
        "torch не видит видеокарту — сервис работал бы на процессоре, рамки по 4 с на кадр.\n"
        "Обновите драйвер NVIDIA (нужен 570 или новее для CUDA 12.8) и запустите install.py снова;\n"
        "другой каталог сборок: python ai/install.py --torch-index <адрес с pytorch.org>;\n"
        "проверка без видеокарты: python ai/install.py --cpu"
    )
    if not gpu and not args.cpu:
        print("  ВНИМАНИЕ: " + no_gpu_message.splitlines()[0], flush=True)

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
            run([ollama, "pull", args.vlm], hint=NET_HINT)

    if not gpu and not args.cpu:
        fail(no_gpu_message)  # в конце, чтобы предупреждение не ушло за экран
    mark_installed("full", args.vlm)
    print("\nГотово. Запуск сервиса:  python ai/run.py")
    if args.vlm != DEFAULT_VLM:
        print(f"Нестандартная модель — перед запуском задайте переменную AI_VLM_MODEL={args.vlm}")


if __name__ == "__main__":
    main()
