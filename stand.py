"""Стенд одной командой: ИИ-сервис и бэкенд на ПК Павла (план, раздел 4.2).

    python stand.py                   # запустить ИИ-сервис, затем бэкенд; Ctrl+C — остановить оба
    python stand.py --reset           # сначала сбросить базу к демо-данным (перед показом)
    python stand.py --reset --check --image demo/photos/pump.jpg   # и сразу проверить сценарий
    python stand.py --stub            # без ИИ-сервиса, с заглушкой — только для проверки приложения

Порядок: ИИ-сервис (`ai/run.py`) → ждём, пока загрузит модели (`GET /health` = 200) →
бэкенд (`backend/run.py`) в режиме настоящего ИИ → ждём `GET /api/health` → «СТЕНД ГОТОВ»
и адрес для телефона. Дальше скрипт следит за обеими службами: если одна упала, пишет,
какая, показывает конец её журнала и останавливает вторую.

Журналы служб — `logs/stand-ai.log` и `logs/stand-backend.log` (перезаписываются при запуске).
Только стандартная библиотека Python; Windows и Linux одинаково.
"""

import argparse
import collections
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_RUN = ROOT / "backend" / "run.py"
AI_RUN = ROOT / "ai" / "run.py"
LOGS = ROOT / "logs"

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # только этот ПК
_PRINT = threading.Lock()


def say(text=""):
    with _PRINT:
        print(text, flush=True)


def http_get(url, timeout=2.0):
    """(код, тело) или (None, b"") — если никто не отвечает."""
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except OSError:
        return None, b""


class Service:
    def __init__(self, name, cmd, health_url, log_name, env=None):
        self.name, self.cmd, self.health_url = name, cmd, health_url
        self.log_path = LOGS / log_name
        self.env = env or {}
        self.tail = collections.deque(maxlen=15)
        self.proc = None

    def start(self):
        LOGS.mkdir(exist_ok=True)
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", **self.env)
        kwargs = {}
        if os.name == "nt":
            # Своя группа: Ctrl+C получает только этот скрипт и сам останавливает службы
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(self.cmd, cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        threading.Thread(target=self._relay, daemon=True).start()

    def _relay(self):
        with open(self.log_path, "w", encoding="utf-8") as log:
            for raw in self.proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                log.write(line + "\n")
                log.flush()
                self.tail.append(line)
                say(f"[{self.name}] {line}")

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def ready(self):
        return http_get(self.health_url)[0] == 200

    def stop(self):
        if not self.alive():
            return
        if os.name == "nt":
            # taskkill /T останавливает и дочерние процессы (uvicorn, загрузчики моделей)
            subprocess.call(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.kill()

    def explain_crash(self):
        say(f"\n[XX] {self.name}: служба остановилась (код {self.proc.returncode}). "
            f"Последние строки журнала {self.log_path.relative_to(ROOT)}:")
        for line in self.tail:
            say(f"     {line}")


def wait_ready(service, seconds):
    started = time.monotonic()
    next_note = 15
    while time.monotonic() - started < seconds:
        if not service.alive():
            service.explain_crash()
            return False
        if service.ready():
            say(f"[OK] {service.name}: готов за {time.monotonic() - started:.0f} с")
            return True
        waited = time.monotonic() - started
        if waited >= next_note:
            say(f"[..] {service.name}: ещё запускается, прошло {waited:.0f} с")
            next_note += 15
        time.sleep(1)
    say(f"[XX] {service.name}: не ответил на {service.health_url} за {seconds} с. "
        f"Журнал: {service.log_path.relative_to(ROOT)}")
    return False


def port_busy(port):
    return http_get(f"http://127.0.0.1:{port}/", timeout=1)[0] is not None


def lan_addresses():
    spec = importlib.util.spec_from_file_location("backend_run", BACKEND_RUN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.lan_addresses()


def banner(port, ai_text):
    say("\n" + "=" * 64)
    say("СТЕНД ГОТОВ")
    addrs = lan_addresses()
    for a in addrs:
        say(f"  Адрес для телефона:  http://{a}:{port}")
    if not addrs:
        say("  [!!] ПК не подключён к сети — телефон не сможет подключиться")
    say(f"  ИИ:                  {ai_text}")
    say("  Проверить сценарий:  python backend/check_scenario.py --image <снимок>.jpg")
    say("  Сбросить базу:       python backend/reset_db.py")
    say("  Остановить всё:      Ctrl+C в этом окне")
    say("=" * 64 + "\n")


def main():
    ap = argparse.ArgumentParser(description="Запуск стенда: ИИ-сервис и бэкенд")
    ap.add_argument("--stub", action="store_true",
                    help="без ИИ-сервиса, с заглушкой ИИ (не для показа: рамки ненастоящие)")
    ap.add_argument("--reset", action="store_true", help="сбросить базу к демо-данным перед запуском")
    ap.add_argument("--check", action="store_true", help="после запуска проверить сценарий")
    ap.add_argument("--image", help="снимок оборудования для --check")
    ap.add_argument("--port", type=int, default=8000, help="порт бэкенда (по умолчанию 8000)")
    ap.add_argument("--ai-port", type=int, default=8001, help="порт ИИ-сервиса (по умолчанию 8001)")
    ap.add_argument("--ai-wait", type=int, default=600,
                    help="сколько секунд ждать загрузки моделей (по умолчанию 600)")
    args = ap.parse_args()

    use_ai = not args.stub
    if use_ai and not AI_RUN.exists():
        say("[!!] ИИ-сервиса в репозитории ещё нет (ai/run.py) — запускаю бэкенд с заглушкой ИИ.")
        use_ai = False

    for port, what in ((args.port, "бэкенда"), (args.ai_port, "ИИ-сервиса")):
        if (what == "бэкенда" or use_ai) and port_busy(port):
            say(f"[XX] Порт {port} {what} уже занят — стенд, похоже, уже запущен в другом окне. "
                "Закройте то окно (или Ctrl+C в нём) и запустите снова.")
            return 1

    if args.reset:
        say("Сбрасываю базу к демо-данным ...")
        if subprocess.call([sys.executable, str(ROOT / "backend" / "reset_db.py")]) != 0:
            say("[XX] Сбросить базу не удалось")
            return 1

    ai_url = f"http://127.0.0.1:{args.ai_port}"
    services = []
    if use_ai:
        services.append(Service("ИИ", [sys.executable, str(AI_RUN), "--port", str(args.ai_port)],
                                f"{ai_url}/health", "stand-ai.log"))
    services.append(Service(
        "бэкенд", [sys.executable, str(BACKEND_RUN), "--port", str(args.port), "--quiet"],
        f"http://127.0.0.1:{args.port}/api/health", "stand-backend.log",
        env={"DEFFECTOR_AI_MODE": "real" if use_ai else "stub", "DEFFECTOR_AI_URL": ai_url}))

    try:
        for s in services:
            say(f"Запускаю: {s.name} ...")
            s.start()
            # Первый запуск ставит зависимости — даём время; модели ИИ грузятся долго
            if not wait_ready(s, args.ai_wait if s.name == "ИИ" else 300):
                if s.name == "ИИ":
                    say("     Сообщите Тимофею. Проверить приложение без ИИ: python stand.py --stub")
                return 1

        _, body = http_get(f"http://127.0.0.1:{args.port}/api/health")
        ai = json.loads(body or b"{}").get("ai", {})
        if not use_ai:
            ai_text = "ЗАГЛУШКА — рамки и анализ ненастоящие, для показа не годится"
        elif ai.get("status") == "ok":
            ai_text = f"настоящий, {ai_url}"
        else:
            ai_text = "[!!] бэкенд не видит ИИ-сервис — см. журнал logs/stand-ai.log"
        banner(args.port, ai_text)

        if args.check:
            cmd = [sys.executable, str(ROOT / "backend" / "check_scenario.py"),
                   "--url", f"http://127.0.0.1:{args.port}"]
            if args.image:
                cmd += ["--image", args.image]
            subprocess.call(cmd)
            say("\nСтенд продолжает работать. Остановить: Ctrl+C")

        return watch(services)
    except KeyboardInterrupt:
        say("\nОстанавливаю стенд ...")
        return 0
    finally:
        for s in reversed(services):
            s.stop()
        say("Стенд остановлен.")


def watch(services):
    """Следим за службами, пока не нажат Ctrl+C."""
    ai = next((s for s in services if s.name == "ИИ"), None)
    ai_ok, tick = True, 0
    while True:
        time.sleep(1)
        tick += 1
        for s in services:
            if not s.alive():
                s.explain_crash()
                say("[XX] Стенд остановлен из-за ошибки. Запустите снова: python stand.py")
                return 1
        if ai and tick % 10 == 0:
            now_ok = ai.ready()
            if now_ok != ai_ok:
                say("[OK] ИИ-сервис снова отвечает" if now_ok
                    else "[!!] ИИ-сервис не отвечает на /health — анализ на телефоне не пройдёт")
                ai_ok = now_ok


if __name__ == "__main__":
    sys.exit(main())
