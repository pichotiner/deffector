"""Параметры из баз значений заказчика (docs/case/Вибрация, Температура).

Пороги «предупреждение / тревога» и диагнозы — из описаний баз. Какое показание
текущее, задаёт настройка telemetry_at; база пересоздаётся reset_db.
"""

import pytest
from fastapi.testclient import TestClient

from app import config, db, seed, telemetry
from app.main import app
from app.parameters import evaluate

client = TestClient(app)


def reseed_at(monkeypatch, moment):
    monkeypatch.setitem(config.SETTINGS, "telemetry_at", moment)
    conn = db.connect()
    try:
        seed.seed(conn)
    finally:
        conn.close()
    return {p["id"]: p for p in client.get("/api/equipment/PU-001").json()["parameters"]}


def test_reading_is_taken_from_case_dataset():
    assert telemetry.value("vibration", "Ампл. 1x (мм/с)", "2026-11-13 09:00") == \
        (0.8, "2026-11-13T09:00:00+03:00")
    # Между замерами берётся последний до указанного момента
    assert telemetry.value("temperature", "Темп. обмоток ЭД (°C)", "2026-11-13 09:59")[1] == \
        "2026-11-13T09:00:00+03:00"


def test_case_diagnosis_matches_our_evaluation():
    """Наш статус совпадает с диагнозом заказчика в каждой строке базы вибрации."""
    rows = telemetry._load("vibration")
    for row in rows:
        p1x = evaluate({"value": float(row["Ампл. 1x (мм/с)"]), "unit": "мм/с",
                        "setpoint_min": None, "setpoint_max": 2.8, "alarm_max": 4.5})
        diagnosis = row["Диагноз по вибрации"]
        if "дисбаланс" in diagnosis.lower():
            assert p1x["status"] == "deviation", row


def test_alarm_moment_turns_impeller_red(monkeypatch):
    # 17.11 02:00 по данным заказчика — «Тревога: Выс. дисбаланс (РК)»
    params = reseed_at(monkeypatch, "2026-11-17 02:00")
    p = params["P-02"]
    assert p["status"] == "deviation"
    assert p["message"].startswith("Тревога: выше 4,5 мм/с на ")
    assert p["message"].endswith("высокий дисбаланс рабочего колеса")
    impeller = client.get("/api/equipment/PU-001/components/C-08").json()
    assert impeller["attention"]["level"] == "defect"
    assert impeller["attention"]["reasons"][0].startswith("Вибрация на оборотной частоте (1x): тревога")


@pytest.mark.parametrize("moment, pid, word", [
    ("2026-11-16 08:00", "P-02", "дисбаланса"),       # «Пред: Рост дисбаланса»
    ("2026-11-20 12:00", "P-04", "центровки"),        # «Пред: Ухудшение центровки»
    ("2026-11-29 12:00", "P-07", "обмоток"),          # «Пред: Рост темп. ЭД»
])
def test_warning_moments_give_case_diagnosis(monkeypatch, moment, pid, word):
    p = reseed_at(monkeypatch, moment)[pid]
    assert p["status"] == "deviation" and p["message"].startswith("Предупреждение: выше ")
    assert word in p["message"] and "(тревога — выше " in p["message"]
