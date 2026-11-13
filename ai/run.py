"""Запуск ИИ-сервиса одной командой:  python ai/run.py

    python ai/run.py --stub              режим заглушки: ответы-примеры без моделей
    python ai/run.py --host 0.0.0.0      принимать запросы с других машин сети
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from _setup import AI_DIR, VENV_DIR, ensure_ollama_running, fail, has_model, ollama_models, venv_python


def main() -> None:
    parser = argparse.ArgumentParser(description="Запуск ИИ-сервиса")
    parser.add_argument("--stub", action="store_true", help="режим заглушки, без моделей")
    parser.add_argument("--host", default=os.environ.get("AI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AI_PORT", "8001")))
    args = parser.parse_args()

    python = venv_python()
    if not python.is_file():
        fail(f"нет окружения {VENV_DIR}. Сначала выполните: python ai/install.py" + (" --stub" if args.stub else ""))

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"  # русский текст в консоли Windows
    stub = args.stub or env.get("AI_STUB", "").lower() in {"1", "true", "yes", "on"}
    env["AI_STUB"] = "1" if stub else "0"

    if not stub:
        vlm = env.get("AI_VLM_MODEL", "qwen2.5vl:7b")
        if not ensure_ollama_running():
            print("ВНИМАНИЕ: Ollama не запущена — /analyze работать не будет, остальные запросы будут.", flush=True)
        elif not has_model(ollama_models() or [], vlm):
            print(f"ВНИМАНИЕ: модель {vlm} не скачана в Ollama (python ai/install.py).", flush=True)

    print(f"ИИ-сервис: http://{args.host}:{args.port}  (проверка готовности: /health)", flush=True)
    command = [str(python), "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port)]
    try:
        raise SystemExit(subprocess.run(command, cwd=AI_DIR, env=env).returncode)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
