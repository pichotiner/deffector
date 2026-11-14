"""PDF презентации из slides.html — без интернета и без установки пакетов.

    python docs/presentation/make_pdf.py
    python docs/presentation/make_pdf.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"

Печатает slides.html в slides.pdf браузером Edge или Chrome в фоновом режиме
(в Windows Edge есть всегда). Один слайд — одна страница 16:9.
Параметр ?pdf в адресе убирает из PDF локальную ссылку на запись сценария: в файле,
выложенном на диск, она не откроется — вместо неё на слайде путь в репозитории.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
NAMES = ["msedge", "google-chrome", "chromium", "chromium-browser", "chrome"]


def find_browser():
    for c in CANDIDATES:
        if Path(c).exists():
            return c
    for n in NAMES:
        found = shutil.which(n)
        if found:
            return found
    return None


def main():
    ap = argparse.ArgumentParser(description="slides.html → slides.pdf")
    ap.add_argument("--browser", help="путь к Edge или Chrome")
    ap.add_argument("--out", default=str(HERE / "slides.pdf"))
    args = ap.parse_args()

    browser = args.browser or find_browser()
    if not browser:
        print("Не нашёл Edge или Chrome. Укажите путь: --browser <путь>, или откройте slides.html "
              "в браузере → Печать → Сохранить как PDF (поля «Нет», фон включить).")
        return 1
    url = (HERE / "slides.html").as_uri() + "?all&pdf"
    out = Path(args.out).resolve()
    # Отдельный профиль не передаёт команду уже открытому браузеру.
    # Старый PDF сохраняем до успешного завершения нового рендера.
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deffector-pdf-", ignore_cleanup_errors=True) as work:
        temp = Path(work).resolve()
        assert temp.parent == Path(tempfile.gettempdir()).resolve()
        rendered = temp / "slides.pdf"
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run",
               "--no-default-browser-check", "--disable-background-networking",
               "--disable-component-update", "--no-pdf-header-footer",
               f"--user-data-dir={temp / 'profile'}", f"--print-to-pdf={rendered}", url]
        if os.name != "nt":
            cmd[1:1] = ["--no-sandbox", "--disable-dev-shm-usage"]
        deadline = time.monotonic() + 90
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        except subprocess.TimeoutExpired:
            pass
        # Windows-лаунчер Edge иногда завершается раньше процесса печати.
        while True:
            try:
                pdf = rendered.read_bytes()
            except OSError:
                pdf = b""
            if pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF"):
                pending = None
                try:
                    # Тот же том: успешный replace заменяет файл целиком.
                    with tempfile.NamedTemporaryFile(dir=out.parent, prefix=out.name + ".",
                                                     suffix=".tmp", delete=False) as target:
                        pending = Path(target.name)
                        target.write(pdf)
                    os.replace(pending, out)
                except OSError as exc:
                    print(f"Не удалось сохранить новый PDF; предыдущий файл сохранён: {exc}")
                    return 1
                finally:
                    if pending is not None:
                        pending.unlink(missing_ok=True)
                break
            if time.monotonic() >= deadline:
                print("PDF не получился; предыдущий файл сохранён. Откройте slides.html "
                      "в браузере и сохраните через «Печать».")
                return 1
            time.sleep(0.25)
    print(f"Готово: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
