"""Выгрузка отчёта об осмотре оборудования: Excel (.xlsx) и PDF.

Ответ организаторов: «выгрузка отчета (PDF, Excel)». Один набор данных — два формата:
паспорт оборудования, состояние узлов (ресурс, визуальный анализ, причины, рекомендуемое
действие), параметры с уставками и история осмотров за выбранный период.

Excel собирается стандартной библиотекой. PDF — библиотекой reportlab со шрифтом
DejaVu Sans из app/fonts (кириллица), всё с диска, интернет не нужен.
"""

import io
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from . import config
from .enums import (INSPECTION_TYPES, NO_ISSUES_NOTE, PARAMETER_STATUS_LABELS,
                    RESOURCE_STATUS_LABELS, VISUAL_CATEGORY_LABELS)

FORMATS = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

ATTENTION_LABELS = {
    "defect": "Требует внимания",
    "check": "Рекомендуется проверка",
    "none": "Замечаний нет",
    "unknown": "Недостаточно данных",
}

TITLE = "Отчёт об осмотре оборудования"
PRELIMINARY = ("ИИ-анализ — инструмент предварительного осмотра по изображению: внутренние "
               "неисправности так не определяются. " + NO_ISSUES_NOTE + ".")


class PdfUnavailable(Exception):
    """Библиотека reportlab не установлена — нужен однократный запуск установки."""


# ---------- данные отчёта ----------

def _date(iso):
    """2026-11-13 или 2026-11-13T10:00:00+03:00 → 13.11.2026 (и время, если есть)."""
    if not iso:
        return "—"
    d = f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"
    return f"{d} {iso[11:16]}" if len(iso) > 10 else d


def _num(v):
    if v is None:
        return "—"
    return str(int(v)) if float(v).is_integer() else str(round(v, 2)).replace(".", ",")


def _value(v, unit=None):
    return "—" if v is None else f"{_num(v)} {unit}".strip() if unit else _num(v)


def _text(v):
    return "—" if v in (None, "") else str(v)


def build(card: dict, date_from: date | None, date_to: date | None, author: dict | None) -> dict:
    """card — цифровая карточка (Card.full()). История ограничивается периодом,
    состояние узлов и параметры — на момент формирования отчёта."""
    names = {c["id"]: c["name"] for c in card["components"]}

    def in_period(h):
        day = date.fromisoformat(h["performed_at"][:10])
        return (date_from is None or day >= date_from) and (date_to is None or day <= date_to)

    history = [h for h in card["history"] if in_period(h)]
    if date_from and date_to:
        period = f"{date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}"
    elif date_from:
        period = f"с {date_from:%d.%m.%Y}"
    elif date_to:
        period = f"по {date_to:%d.%m.%Y}"
    else:
        period = "за всё время"

    levels = [c["attention"]["level"] for c in card["components"]]
    summary = [
        ("Оборудование", f"{card['id']} — {card['name']}"),
        ("Модель", _text(card["model"])),
        ("Изготовитель", _text(card["manufacturer"])),
        ("Серийный номер", _text(card["serial_number"])),
        ("Маркировка", _text(card["marking"])),
        ("Расположение", _text(card["location"])),
        ("Ввод в эксплуатацию", _date(card["commissioned_at"])),
        ("Нормативный срок службы", _life(card["normative"])),
        ("Расчётная оценка остаточного ресурса", card["resource"]["message"]),
        ("Узлов и комплектующих", str(len(card["components"]))),
        ("Требуют внимания", str(levels.count("defect"))),
        ("Рекомендуется проверка", str(levels.count("check"))),
        ("Параметров с отклонениями", str(card["deviations_count"])),
        ("Период истории осмотров", period),
        ("Записей за период", str(len(history))),
        ("Отчёт сформирован", _date(config.now_iso())),
        ("Сформировал", f"{author['name']} ({author['role_name']})" if author else "—"),
    ]

    components = [[
        c["id"], c["name"], c["type_name"], ATTENTION_LABELS[c["attention"]["level"]],
        "; ".join(c["attention"]["reasons"]) or "—",
        _life(c["normative"]),
        _resource(c["resource"]),
        _visual(c["visual"]),
        c["attention"]["recommended_action"],
        _date(c["last_maintenance_at"]), _date(c["last_replaced_at"] or c["installed_at"]),
    ] for c in card["components"]]

    parameters = [[
        p["name"], names.get(p["component_id"], "Оборудование"), _value(p["value"], p["unit"]),
        _value(p["setpoint_min"]), _value(p["setpoint_max"]),
        PARAMETER_STATUS_LABELS[p["status"]], p["message"], _date(p["measured_at"]),
    ] for p in card["parameters"]]

    rows = [[
        _date(h["performed_at"]), names.get(h["component_id"], "Оборудование"),
        INSPECTION_TYPES[h["type"]], _text(h["comment"]), _text(h["performed_by"]),
        _visual(h["visual"]) if h["visual"] else "—", _text(h["recommendation"]),
    ] for h in history]

    return {
        "title": TITLE, "equipment_id": card["id"], "equipment_name": card["name"],
        "summary": summary,
        "components": {
            "title": "Состояние узлов и комплектующих",
            "head": ["Код", "Узел", "Тип", "Состояние", "Причины",
                     "Нормативный срок службы", "Расчётная оценка остаточного ресурса",
                     "Результат визуального анализа", "Рекомендуемое действие",
                     "Обслужен", "Установлен или заменён"],
            "rows": components,
        },
        "parameters": {
            "title": "Технические параметры и уставки",
            "head": ["Параметр", "Узел", "Значение", "Нижняя уставка", "Верхняя уставка",
                     "Статус", "Пояснение", "Время замера"],
            "rows": parameters,
        },
        "history": {
            "title": f"История осмотров и обслуживания ({period})",
            "head": ["Дата", "Узел", "Вид записи", "Комментарий", "Выполнил",
                     "Результат визуального анализа", "Рекомендация"],
            "rows": rows,
        },
        "note": PRELIMINARY,
    }


def _life(n):
    parts = []
    if n["life_years"] is not None:
        parts.append(f"{_num(n['life_years'])} лет")
    if n["life_hours"] is not None:
        parts.append(f"{_num(n['life_hours'])} ч")
    if n["life_cycles"] is not None:
        parts.append(f"{_num(n['life_cycles'])} циклов")
    if n["maintenance_interval_days"] is not None:
        parts.append(f"обслуживание раз в {_num(n['maintenance_interval_days'])} дн.")
    return ", ".join(parts) or "не задан"


def _resource(r):
    label, message = RESOURCE_STATUS_LABELS[r["status"]], r["message"]
    return message if message.lower().startswith(label.lower()) else f"{label}. {message}"


def _visual(v):
    label = VISUAL_CATEGORY_LABELS[v["category"]]
    if v["category"] == "not_analyzed":
        return label
    signs = ", ".join(v.get("signs") or [])
    when = f" ({_date(v['analyzed_at'])})" if v.get("analyzed_at") else ""
    return label + (f": {signs}" if signs else "") + when


def filename(report, fmt):
    return f"otchet-{report['equipment_id']}-{config.today():%Y-%m-%d}.{fmt}"


# ---------- Excel ----------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheets}</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

# Стили ячеек: 0 — обычный (пустые ячейки), 1 — текст с переносом, 2 — заголовок таблицы,
# 3 — название, 4 — подпись поля.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="14"/><name val="Calibri"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFDCE9EE"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FF9AA7B1"/></left><right style="thin"><color rgb="FF9AA7B1"/></right><top style="thin"><color rgb="FF9AA7B1"/></top><bottom style="thin"><color rgb="FF9AA7B1"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _col(i):
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return name


def _cell(row, col, value, style):
    # Только строки: значения уже приведены к тексту с единицами измерения.
    text = escape(str(value)).replace("\r", "")
    return (f'<c r="{_col(col)}{row}" s="{style}" t="inlineStr">'
            f'<is><t xml:space="preserve">{text}</t></is></c>')


def _sheet(rows, widths, freeze=None):
    """rows — список строк, строка — список (значение, стиль)."""
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                   for i, w in enumerate(widths, 1))
    body = "".join(
        f'<row r="{r}">' + "".join(_cell(r, c, v, s) for c, (v, s) in enumerate(row)) + "</row>"
        for r, row in enumerate(rows, 1))
    pane = (f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze}" '
            f'topLeftCell="A{freeze + 1}" activePane="bottomLeft" state="frozen"/>'
            f"</sheetView></sheetViews>") if freeze else ""
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"{pane}<cols>{cols}</cols><sheetData>{body}</sheetData></worksheet>")


def _table_sheet(section, widths):
    rows = [[(h, 2) for h in section["head"]]]
    rows += [[(v, 1) for v in row] for row in section["rows"]]
    if not section["rows"]:
        rows.append([("Записей нет", 1)])
    return _sheet(rows, widths, freeze=1)


def to_xlsx(report: dict) -> bytes:
    summary = [[(f"{report['title']}: {report['equipment_id']}", 3)], []]
    summary += [[(k, 4), (v, 1)] for k, v in report["summary"]]
    summary += [[("Примечание", 4), (report["note"], 1)]]
    sheets = [
        ("Сводка", _sheet(summary, [38, 70])),
        ("Узлы", _table_sheet(report["components"], [12, 30, 22, 20, 46, 26, 46, 36, 40, 16, 16])),
        ("Параметры", _table_sheet(report["parameters"], [34, 30, 14, 14, 14, 14, 50, 18])),
        ("История", _table_sheet(report["history"], [18, 30, 22, 50, 22, 36, 46])),
    ]
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                          for i, (name, _) in enumerate(sheets, 1))
                + "</sheets></workbook>")
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/'
                  f'2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                  for i in range(1, len(sheets) + 1))
        + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/'
          'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'
        for i in range(1, len(sheets) + 1))

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES.format(sheets=overrides))
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", _STYLES)
        for i, (_, xml) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
    return out.getvalue()


# ---------- PDF ----------

_FONT, _FONT_BOLD = "DejaVuSans", "DejaVuSans-Bold"


def _pdf_fonts():
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as e:
        raise PdfUnavailable(str(e)) from e
    if _FONT not in pdfmetrics.getRegisteredFontNames():
        fonts = config.BACKEND / "app" / "fonts"
        pdfmetrics.registerFont(TTFont(_FONT, str(fonts / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, str(fonts / "DejaVuSans-Bold.ttf")))


def to_pdf(report: dict) -> bytes:
    _pdf_fonts()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    ink, line, fill = colors.HexColor("#14323F"), colors.HexColor("#9AA7B1"), colors.HexColor("#DCE9EE")
    base = ParagraphStyle("base", fontName=_FONT, fontSize=7.5, leading=9.5, textColor=colors.black)
    bold = ParagraphStyle("bold", parent=base, fontName=_FONT_BOLD)
    title = ParagraphStyle("title", parent=bold, fontSize=15, leading=19, textColor=ink)
    heading = ParagraphStyle("heading", parent=bold, fontSize=10.5, leading=14, textColor=ink,
                             spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=base, fontSize=7, leading=9, textColor=colors.HexColor("#4A5661"))

    def p(text, style=base):
        return Paragraph(escape(str(text)), style)

    grid = [("GRID", (0, 0), (-1, -1), 0.4, line), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]

    page = landscape(A4)
    width = page[0] - 24 * mm

    def table(section, shares):
        rows = [[p(h, bold) for h in section["head"]]]
        rows += [[p(v) for v in row] for row in section["rows"]]
        if not section["rows"]:
            rows.append([p("Записей нет")] + [""] * (len(section["head"]) - 1))
        t = Table(rows, colWidths=[width * s / sum(shares) for s in shares], repeatRows=1)
        t.setStyle(TableStyle(grid + [("BACKGROUND", (0, 0), (-1, 0), fill)]))
        # Заголовок раздела не остаётся один внизу страницы.
        return [CondPageBreak(35 * mm), p(section["title"], heading), t]

    story = [p(report["title"], title),
             p(f"{report['equipment_id']} — {report['equipment_name']}", heading)]
    summary = Table([[p(k, bold), p(v)] for k, v in report["summary"]],
                    colWidths=[width * 0.3, width * 0.7])
    summary.setStyle(TableStyle(grid + [("BACKGROUND", (0, 0), (0, -1), fill)]))
    story += [summary]
    story += table(report["components"], [6, 15, 14, 12, 21, 12, 21, 17, 19, 11, 12])
    story += table(report["parameters"], [20, 16, 9, 8, 8, 9, 30, 12])
    story += table(report["history"], [11, 16, 13, 27, 12, 18, 24])
    story += [Spacer(1, 8), p(report["note"], small)]

    def footer(canvas, doc):
        canvas.setFont(_FONT, 7)
        canvas.setFillColor(colors.HexColor("#4A5661"))
        canvas.drawString(12 * mm, 7 * mm, f"{report['title']} · {report['equipment_id']}")
        canvas.drawRightString(page[0] - 12 * mm, 7 * mm, f"Страница {doc.page}")

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm,
                            title=f"{report['title']}: {report['equipment_id']}",
                            author="Деффектор")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def render(report: dict, fmt: str) -> bytes:
    return to_pdf(report) if fmt == "pdf" else to_xlsx(report)
