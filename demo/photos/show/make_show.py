"""Пакет для показа: кадры узлов и эталоны идентификации — по листу A4 на каждый.

    python demo/photos/show/make_show.py
    python demo/photos/show/make_show.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe"

Создаёт show.html рядом со скриптом и печатает его в show.pdf браузером Edge или Chrome
(тот же способ, что docs/presentation/make_pdf.py). Распечатать show.pdf или открыть
листы на втором мониторе — и наводить на них телефон.
"""
from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(REPO / "docs" / "presentation"))

from make_pdf import find_browser  # noqa: E402

WIKI = "Wikimedia Commons, автор и лицензия — demo/photos/README.md"
CASE = "фото заказчика из материалов кейса"

# (файл от корня репозитория, заголовок, что ожидать на показе, источник)
# Ожидания — по прогону на видеокарте 13.11 (ai/README.md, «Результаты»).
NODES = [
    ("demo/photos/pump_unit_drawing_01.jpg", "Общий вид насосного агрегата",
     "Рамки: двигатель и два фланца. Порядок рамок слева направо сопоставляется с карточкой PU-001.", WIKI),
    ("demo/photos/pump_room_01.jpg", "Насосная: два двигателя",
     "Рамки на обоих двигателях.", WIKI),
    ("demo/photos/motor_corrosion_01.jpg", "Двигатель с коррозией",
     "Рамка на двигателе → «Анализировать»: «обнаружены признаки возможного дефекта», коррозия.", WIKI),
    ("demo/photos/gauge_corrosion_01.jpg", "Манометр с коррозией",
     "Рамка на манометре → коррозия, категория «обнаружены признаки возможного дефекта» "
     "или «рекомендуется проверка».", WIKI),
    ("demo/photos/flange_corrosion_02.jpg", "Фланец с коррозией",
     "Рамка на фланце → коррозия.", WIKI),
    ("docs/case/Запорная арматура/cca9d029-459e-5007-8f88-181843ed8665.jpg", "Шаровой кран с течью",
     "Рамка на арматуре → течь/подтёки. Фото маленькое — печатать не крупнее половины листа "
     "или показывать на мониторе.", CASE),
    ("docs/case/Запорная арматура/0831c2a9-3a2b-5bf7-b70f-05f1d51f5cdb (1).jpg", "Задвижка с коррозией",
     "Рамка на арматуре → коррозия. Фото маленькое.", CASE),
    ("docs/case/Насосные агрегаты/photo_2026-11-13_12-48-02.jpg", "Клеммная коробка двигателя: перегрев",
     "Запасной кадр: анализ находит «следы перегрева», но рамки двигателя на этом крупном плане "
     "может не быть — тогда кадр не показывать.", CASE),
    ("demo/photos/pump_unit_01.jpg", "Агрегат без видимых дефектов",
     "Рамка на двигателе → «видимых проблем не обнаружено» с оговоркой. "
     "gauge_clean_01.jpg для «чистого» не брать: модель видит на нём коррозию.", WIKI),
]

REFERENCES = [
    ("demo/reference/PU-001/case_pump_01.jpg", "Эталон PU-001 — насосный агрегат Wilo",
     "«Определить по фото» → PU-001. Снять этот лист телефоном 2–3 раза и положить снимки "
     "в demo/reference/PU-001/.", CASE),
    ("demo/reference/PU-001/wilo_manual_01.jpg", "Эталон PU-001 — насосы Wilo CronoLine",
     "«Определить по фото» → PU-001.", "руководство Wilo из материалов кейса"),
    ("demo/reference/PU-002/ams_manual_01.jpg", "Эталон PU-002 — винтовой агрегат AMS",
     "«Определить по фото» → PU-002. Снять этот лист телефоном 2–3 раза и положить снимки "
     "в demo/reference/PU-002/.", "инструкция AMS из материалов кейса"),
    ("demo/reference/PU-002/ams_manual_02.jpg", "Эталон PU-002 — винтовой агрегат AMS",
     "«Определить по фото» → PU-002.", "инструкция AMS из материалов кейса"),
]

STYLE = """
@page { size: A4 landscape; margin: 8mm; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #111; background: #fff; }
.sheet { height: 194mm; display: flex; flex-direction: column; page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
.photo { flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; }
.photo img { max-width: 100%; max-height: 100%; object-fit: contain; }
.small img { max-width: 55%; max-height: 80%; }
.cap { padding-top: 3mm; border-top: 1px solid #bbb; font-size: 11pt; line-height: 1.3; }
.cap b { font-size: 13pt; }
.src { color: #666; font-size: 8.5pt; }
.cover h1 { font-size: 22pt; margin: 0 0 6mm; }
.cover li { margin: 1.5mm 0; font-size: 11pt; }
"""


def sheet(number: str, path: str, title: str, expect: str, source: str) -> str:
    img = REPO / path
    if not img.is_file():
        raise SystemExit(f"Нет файла: {path}")
    try:
        from PIL import Image

        small = Image.open(img).width < 600  # маленькое фото не растягиваем на весь лист
    except ImportError:
        small = False
    src = quote(Path(os.path.relpath(img, HERE)).as_posix())  # относительный путь: работает на любом ПК
    return f"""
<section class="sheet">
  <div class="photo{' small' if small else ''}"><img src="{src}"></div>
  <div class="cap"><b>{number}. {html.escape(title)}</b><br>{html.escape(expect)}
  <div class="src">{html.escape(path)} · {html.escape(source)}</div></div>
</section>"""


def build() -> str:
    items = [f"<li>{i}. {html.escape(t)}</li>" for i, (_, t, _, _) in enumerate(NODES, 1)]
    refs = [f"<li>Э{i}. {html.escape(t)}</li>" for i, (_, t, _, _) in enumerate(REFERENCES, 1)]
    cover = f"""
<section class="sheet cover">
  <h1>Листы для показа ИИ</h1>
  <p>Наводить телефон в режиме AR-осмотра с открытой карточкой <b>PU-001</b>: рамки появляются
  на узлах, «Анализировать» — оценка выбранного узла. Листы Э — для «Определить по фото».
  Что ожидать — под каждым листом (по прогону на видеокарте 13.11). Кадр, который на стенде
  ведёт себя нестабильно, на показ не брать.</p>
  <ol style="list-style:none;padding:0">{''.join(items)}</ol>
  <ol style="list-style:none;padding:0">{''.join(refs)}</ol>
  <p class="src">Собрано скриптом demo/photos/show/make_show.py.</p>
</section>"""
    sheets = [sheet(str(i), *row) for i, row in enumerate(NODES, 1)]
    sheets += [sheet(f"Э{i}", *row) for i, row in enumerate(REFERENCES, 1)]
    return ("<!doctype html><html lang='ru'><head><meta charset='utf-8'><title>Листы для показа ИИ</title>"
            f"<style>{STYLE}</style></head><body>{cover}{''.join(sheets)}</body></html>")


def main() -> int:
    ap = argparse.ArgumentParser(description="Листы для показа ИИ → show.pdf")
    ap.add_argument("--browser", help="путь к Edge или Chrome")
    args = ap.parse_args()
    page = HERE / "show.html"
    page.write_text(build(), encoding="utf-8")
    browser = args.browser or find_browser()
    if not browser:
        print(f"Готово: {page}. Edge или Chrome не найден — откройте файл в браузере и распечатайте.")
        return 0
    out = HERE / "show.pdf"
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--disable-background-networking", "--disable-component-update", "--no-pdf-header-footer",
           "--allow-file-access-from-files", f"--print-to-pdf={out}", page.as_uri()]
    if os.name != "nt":
        cmd[1:1] = ["--no-sandbox", "--disable-dev-shm-usage"]
    out.unlink(missing_ok=True)
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except subprocess.TimeoutExpired:
        pass
    if not out.exists() or out.stat().st_size == 0:
        print(f"PDF не получился — откройте {page} в браузере и распечатайте.")
        return 1
    print(f"Готово: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
