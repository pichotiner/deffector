"""Показания насосного агрегата из баз значений заказчика (материалы кейса).

Исходные файлы — docs/case/Вибрация и docs/case/Температура (xlsx + описание).
Здесь они же в CSV: 500 строк с шагом 1 час, с 10.11.2026 08:00 по 01.12.2026 03:00.

Какое показание считается текущим, задаёт настройка telemetry_at (по умолчанию
13.11.2026 09:00 — все величины в норме). На другой момент база переключается так:

    DEFFECTOR_TELEMETRY_AT="2026-11-17 02:00" python backend/reset_db.py

— например, 17.11 02:00 по данным заказчика «Тревога: высокий дисбаланс рабочего колеса».
"""

import csv
from datetime import datetime
from pathlib import Path

from . import config

DATA = Path(__file__).resolve().parent / "case_data"
FILES = {"vibration": "vibration.csv", "temperature": "temperature.csv"}
TIME_COLUMN = "Дата и время"


def _load(name):
    with open(DATA / FILES[name], encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def reading(name, at=None):
    """Последняя строка базы name не позже момента at (строка 'ГГГГ-ММ-ДД ЧЧ:ММ')."""
    at = at or config.SETTINGS["telemetry_at"]
    moment = datetime.strptime(at, "%Y-%m-%d %H:%M")
    rows = _load(name)
    chosen = None
    for row in rows:
        if datetime.strptime(row[TIME_COLUMN], "%Y-%m-%d %H:%M") <= moment:
            chosen = row
        else:
            break
    return chosen or rows[0]


def value(name, column, at=None):
    """(значение, время замера в ISO 8601 по Москве) из базы name."""
    row = reading(name, at)
    measured = datetime.strptime(row[TIME_COLUMN], "%Y-%m-%d %H:%M").replace(tzinfo=config.MSK)
    raw = row[column]
    return (float(raw) if raw not in ("", None) else None), measured.isoformat(timespec="seconds")
