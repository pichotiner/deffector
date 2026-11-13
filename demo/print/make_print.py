"""Файлы для печати: QR-коды и таблички с маркировкой и серийным номером.

    pip install qrcode
    python demo/print/make_print.py

Создаёт print.html рядом со скриптом (и print.pdf, если установлен Playwright для Python;
иначе откройте print.html в браузере и распечатайте на A4). Готовый print.pdf лежит в репозитории.
Данные берутся из демо-данных бэкенда, чтобы номера всегда совпадали с базой.
QR, маркировка и номер — на отдельных карточках: так на показе можно проверить
каждый способ идентификации по отдельности.
"""

import html
import io
import sys
from pathlib import Path

import qrcode
import qrcode.image.svg

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "backend"))

from app.seed import EQUIPMENT  # noqa: E402


def qr_svg(text):
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return svg[svg.index("<svg"):]


def card(eq):
    e = {k: html.escape(str(v or "")) for k, v in eq.items()}
    return f"""
<section class="sheet">
  <div class="card qr">
    {qr_svg(eq["qr_code"])}
    <div class="cap">{e["qr_code"]}</div>
    <div class="sub">{e["name"]} {e["model"]} · QR-код</div>
  </div>
  <div class="card plate">
    <div class="big">{e["marking"]}</div>
    <div class="sub">{e["name"]} · маркировка</div>
  </div>
  <div class="card plate">
    <div class="label">S/N</div>
    <div class="big">{e["serial_number"]}</div>
    <div class="sub">{e["name"]} · серийный номер</div>
  </div>
</section>"""


PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Deffector — файлы для печати</title>
<style>
  @page {{ size: A4; margin: 12mm; }}
  body {{ margin: 0; font-family: "DejaVu Sans", Arial, sans-serif; color: #000; background: #fff; }}
  .sheet {{ page-break-after: always; display: flex; flex-direction: column; gap: 10mm; align-items: center; }}
  .card {{ border: 0.6mm solid #000; border-radius: 3mm; padding: 6mm 10mm; text-align: center; width: 150mm; box-sizing: border-box; }}
  .qr svg {{ width: 70mm; height: 70mm; }}
  .cap {{ font: 600 7mm/1.2 "DejaVu Sans Mono", monospace; margin-top: 2mm; }}
  .big {{ font: 700 20mm/1.1 "DejaVu Sans Mono", "Courier New", monospace; letter-spacing: 1mm; }}
  .plate .big {{ font-size: 12mm; white-space: nowrap; }}
  .label {{ font: 600 6mm/1 "DejaVu Sans", Arial, sans-serif; text-align: left; }}
  .sub {{ font-size: 4mm; color: #333; margin-top: 3mm; }}
</style></head><body>
{cards}
</body></html>
"""


def main():
    out = HERE / "print.html"
    out.write_text(PAGE.format(cards="".join(card(e) for e in EQUIPMENT)), encoding="utf-8")
    print(f"Готово: {out}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright не установлен — откройте print.html в браузере и распечатайте (A4).")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(out.as_uri())
        page.pdf(path=str(HERE / "print.pdf"), format="A4", print_background=True)
        browser.close()
    print(f"Готово: {HERE / 'print.pdf'}")


if __name__ == "__main__":
    main()
