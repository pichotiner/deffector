"""Установка и запуск бэкенда одной командой.

    python backend/run.py            # установить зависимости (при первом запуске) и запустить
    python backend/run.py --port 8080
    python backend/run.py --quiet    # без строки на каждый запрос (так запускает stand.py)

Работает одинаково в Windows и Linux. Создаёт виртуальное окружение backend/.venv,
ставит туда зависимости из requirements.txt и запускает сервер на всех сетевых
интерфейсах, чтобы телефон мог подключиться по адресу ПК в локальной сети.
"""

import argparse
import hashlib
import os
import socket
import subprocess
import sys
import venv
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
VENV = BACKEND / ".venv"
REQUIREMENTS = BACKEND / "requirements.txt"
STAMP = VENV / "requirements.sha256"


def venv_python():
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def ensure_venv():
    if not venv_python().exists():
        print("Создаю виртуальное окружение backend/.venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV)

    digest = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == digest:
        return
    print("Ставлю зависимости (нужен интернет только в этот раз) ...")
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-q",
                           "--disable-pip-version-check",
                           "-r", str(REQUIREMENTS)])
    STAMP.write_text(digest)


def lan_addresses():
    """Адреса ПК в локальной сети. Пакеты наружу не отправляются."""
    addrs = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # UDP connect не шлёт пакетов
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for a in socket.gethostbyname_ex(socket.gethostname())[2]:
            addrs.add(a)
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))


def main():
    parser = argparse.ArgumentParser(description="Запуск бэкенда Deffector")
    parser.add_argument("--host", default=os.environ.get("DEFFECTOR_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DEFFECTOR_PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="перезапуск при изменении кода")
    parser.add_argument("--quiet", action="store_true",
                        help="не писать строку на каждый запрос; ошибки пишутся всегда")
    args = parser.parse_args()

    ensure_venv()

    print()
    print(f"Бэкенд запускается на порту {args.port}.")
    for a in lan_addresses():
        print(f"  Адрес для телефона: http://{a}:{args.port}   (проверка: /api/health)")
    print("  Остановить: Ctrl+C")
    print()

    cmd = [str(venv_python()), "-m", "uvicorn", "app.main:app",
           "--host", args.host, "--port", str(args.port)]
    if args.reload:
        cmd.append("--reload")
    if args.quiet:
        cmd.append("--no-access-log")
    try:
        return subprocess.call(cmd, cwd=str(BACKEND))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
