"""Расчёт ресурса (ТЗ 4.3): по одному тесту на каждый демо-случай и граничные значения."""

from datetime import date

import pytest

from app import seed
from app.resource import calculate

TODAY = date(2026, 11, 13)


def comp(cid):
    return next(dict(zip(seed._C, c)) for c in seed.COMPONENTS if c[0] == cid)


def calc(item, today=TODAY):
    return calculate(item, today, approaching_percent=80, warn_days=30)


# ---------- демо-случаи ----------

def test_overdue_maintenance():
    r = calc(comp("C-02"))
    assert r["status"] == "due"
    assert r["maintenance"] == {"next_due_date": "2026-11-02", "status": "due", "overdue_days": 11}
    assert r["message"] == "Срок обслуживания наступил 11 дней назад"


def test_expired_life_by_hours():
    # Подшипники двигателя Wilo: ресурс 20 000 ч, наработка 20 600 ч
    r = calc(comp("C-07"))
    assert r["status"] == "due" and r["used_percent"] == 103
    assert r["message"].startswith("Наступил срок замены")
    assert r["estimated_end_date"] < TODAY.isoformat()  # ресурс исчерпан в прошлом


def test_approaching_by_cycles():
    r = calc(comp("C-03"))
    assert r["status"] == "approaching" and r["used_percent"] == 89
    assert r["remaining"]["cycles"] == 220
    assert "числу циклов" in r["basis"]


def test_approaching_by_hours():
    # Торцевое уплотнение Wilo: замена при ревизии 15 000 ч, после замены 13 300 ч
    r = calc(comp("C-06"))
    assert r["status"] == "approaching" and r["used_percent"] == 89
    assert r["remaining"]["hours"] == 1700
    assert "от даты последней замены" in r["basis"]


def test_approaching_by_maintenance():
    # ТО-1 каждые 4000 ч ≈ 167 суток от 04.06.2026
    r = calc(comp("N-01"))
    assert r["status"] == "approaching" and r["maintenance"]["days_left"] == 5


def test_large_reserve_is_ok():
    r = calc(comp("C-04"))
    assert r["status"] == "ok" and r["used_percent"] < 50


def test_insufficient_data_is_explicit():
    r = calc(comp("C-05"))
    assert r["status"] == "insufficient_data" and r["used_percent"] is None
    assert "installed_at" in r["missing_data"]
    assert r["message"] == "Недостаточно данных для оценки ресурса"


def test_replacement_history_moves_reference_point():
    r = calc(comp("C-02"))
    assert "от даты последней замены" in r["basis"]
    # 2024-11-05 → 2026-11-13 при сроке 8 лет ≈ 25 %
    assert r["used_percent"] == 25


def test_no_normative_by_condition_is_explicit():
    # Рабочее колесо Wilo и статор AMS меняются «по состоянию» — норматива нет
    for cid in ("C-08", "C-11"):
        r = calc(comp(cid))
        assert r["status"] == "insufficient_data" and r["missing_data"] == ["normative"]


def test_passport_normatives_of_screw_pump():
    eq = next(e for e in seed.EQUIPMENT if e["id"] == "PU-002")
    r = calc(eq)
    # Паспорт: ресурс до списания 11 000 ч, наработка 6 800 ч; ТО — раз в 3 месяца
    assert r["used_percent"] == 62 and r["remaining"]["hours"] == 4200
    assert r["status"] == "approaching" and r["maintenance"]["days_left"] == 17


def test_partial_data_is_reported():
    item = {"installed_at": "2020-01-01", "life_years": 10, "life_hours": 50000,
            "operating_hours": None}
    r = calc(item)
    assert r["status"] == "ok" and r["missing_data"] == ["operating_hours"]
    assert "не предоставлено: наработка" in r["basis"]


def test_max_fraction_wins():
    item = {"installed_at": "2025-11-13", "life_years": 10, "life_cycles": 100, "cycles": 95}
    r = calc(item)
    assert r["used_percent"] == 95 and r["status"] == "approaching"


# ---------- границы ----------

@pytest.mark.parametrize("cycles, status", [(799, "ok"), (800, "approaching"),
                                            (999, "approaching"), (1000, "due")])
def test_thresholds_80_and_100(cycles, status):
    item = {"installed_at": "2026-01-01", "life_cycles": 1000, "cycles": cycles}
    assert calc(item)["status"] == status


@pytest.mark.parametrize("last, status, field, value", [
    ("2026-10-14", "due", "overdue_days", 0),        # срок обслуживания — сегодня
    ("2026-10-13", "due", "overdue_days", 1),
    ("2026-11-12", "approaching", "days_left", 29),
])
def test_maintenance_today(last, status, field, value):
    item = {"installed_at": "2026-01-01", "life_years": 10,
            "last_maintenance_at": last, "maintenance_interval_days": 30}
    r = calc(item)
    assert r["maintenance"]["status"] == status and r["maintenance"][field] == value


def test_maintenance_due_today_message():
    item = {"installed_at": "2026-01-01", "life_years": 10,
            "last_maintenance_at": "2026-10-14", "maintenance_interval_days": 30}
    assert calc(item)["message"] == "Срок обслуживания наступил сегодня"


@pytest.mark.parametrize("days_left, status", [(30, "approaching"), (31, "ok")])
def test_maintenance_warning_window(days_left, status):
    last = date.fromordinal(TODAY.toordinal() + days_left - 100).isoformat()
    item = {"installed_at": "2026-01-01", "life_years": 10,
            "last_maintenance_at": last, "maintenance_interval_days": 100}
    assert calc(item)["status"] == status


def test_replacement_today_resets():
    item = {**comp("C-06"), "last_replaced_at": TODAY.isoformat(), "operating_hours": 0}
    r = calc(item)
    assert r["status"] == "ok" and r["used_percent"] == 0


# ---------- запас дат до защиты (план, раздел 6.1, п. 3) ----------

def _all_items():
    yield from seed.EQUIPMENT
    for c in seed.COMPONENTS:
        yield dict(zip(seed._C, c))


@pytest.mark.parametrize("item", list(_all_items()), ids=lambda i: i["id"])
def test_status_stable_until_defence(item):
    statuses = {calc(item, date(2026, 11, d))["status"] for d in (13, 14, 15, 16)}
    maint = {(calc(item, date(2026, 11, d))["maintenance"] or {}).get("status") for d in (13, 14, 15, 16)}
    assert len(statuses) == 1 and len(maint) == 1
