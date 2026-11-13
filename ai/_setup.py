"""Общие функции для install.py и run.py. Только стандартная библиотека."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent
VENV_DIR = AI_DIR / ".venv"
WEIGHTS_DIR = Path(os.environ.get("AI_WEIGHTS_DIR") or AI_DIR / "weights")
OLLAMA_URL = os.environ.get("AI_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
IS_WINDOWS = os.name == "nt"


def venv_python() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def find_ollama() -> str | None:
    """Ищет программу Ollama: сначала в PATH, затем в стандартных папках установки Windows."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates = []
    for variable in ("LOCALAPPDATA", "ProgramFiles"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Programs" / "Ollama" / "ollama.exe")
            candidates.append(Path(base) / "Ollama" / "ollama.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _local_opener() -> urllib.request.OpenerDirector:
    # Обращение к локальному Ollama: системные прокси не используем
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ollama_models() -> list[str] | None:
    """Список скачанных моделей или None, если Ollama не отвечает."""
    try:
        with _local_opener().open(f"{OLLAMA_URL}/api/tags", timeout=3) as response:
            return [m.get("name", "") for m in json.load(response).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def ensure_ollama_running(wait_seconds: int = 40) -> bool:
    """Запускает `ollama serve`, если сервер ещё не отвечает. Возвращает готовность."""
    if ollama_models() is not None:
        return True
    exe = find_ollama()
    if exe is None:
        return False
    env = dict(os.environ)
    env.setdefault("OLLAMA_KEEP_ALIVE", "-1")  # не выгружать модель из видеопамяти
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": env}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    print("Запускаю Ollama…", flush=True)
    subprocess.Popen([exe, "serve"], **kwargs)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if ollama_models() is not None:
            return True
        time.sleep(1)
    return False


def has_model(models: list[str], wanted: str) -> bool:
    return wanted in models or f"{wanted}:latest" in models


def fail(message: str) -> "NoReturn":  # noqa: F821
    print(f"\nОШИБКА: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)
