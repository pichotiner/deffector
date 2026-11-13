"""Все 11 запросов контракта. Формат ответа проверяет сам FastAPI по моделям из
app/schemas.py — расхождение с контрактом даёт ошибку 500, и тест падает.

    cd backend && python -m pytest
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
JPEG = {"image": ("frame.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")}


def comp(card, cid):
    return next(c for c in card["components"] if c["id"] == cid)


def test_11_health():
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["ai"] == {"mode": "stub", "status": "ok"}


def test_1_list_and_search():
    assert {i["id"] for i in client.get("/api/equipment").json()["items"]} == {"PU-001", "PU-002"}
    assert [i["id"] for i in client.get("/api/equipment?q=wilo").json()["items"]] == ["PU-001"]
    assert [i["id"] for i in client.get("/api/equipment?q=винтовой").json()["items"]] == ["PU-002"]
    assert [i["id"] for i in client.get("/api/equipment?q=21031004").json()["items"]] == ["PU-002"]


@pytest.mark.parametrize("query, by, conf", [
    ("qr=KST:PU-001", "qr", 1.0),
    ("qr=PU-001", "qr", 1.0),                       # в QR записана просто маркировка
    ("serial=SN2024-004587", "serial", 1.0),
    ("serial=sn 2024 OO4587", "serial", 0.93),      # регистр, пробелы, O вместо 0
    ("serial=5N2O24-OO4S87", "serial", 0.93),       # S/5, O/0
    ("marking=PU001", "marking", 0.93),
])
def test_2_lookup_found(query, by, conf):
    r = client.get(f"/api/equipment/lookup?{query}").json()
    assert r == {"found": True, "equipment_id": "PU-001", "matched_by": by, "match_confidence": conf}


def test_2_lookup_by_passport_serial_number():
    # Заводской номер агрегата AMS из паспорта, с ошибками распознавания I/1 и O/0
    for serial in ("21031004-1", "2IO31OO4-1"):
        r = client.get(f"/api/equipment/lookup?serial={serial}").json()
        assert r["found"] and r["equipment_id"] == "PU-002"


def test_2_lookup_not_found_gives_suggestions():
    r = client.get("/api/equipment/lookup?serial=SN2024-004500").json()
    assert r["found"] is False and r["suggestions"][0]["equipment_id"] == "PU-001"


def test_2_lookup_without_params_is_error():
    r = client.get("/api/equipment/lookup")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_3_identify():
    r = client.post("/api/identify/image", files=JPEG).json()
    assert r["recognized"] and r["candidates"][0]["name"] == "Насосный агрегат"


def test_4_card_contents():
    card = client.get("/api/equipment/PU-001").json()
    assert card["model"] == "Wilo CronoLine-IL 65/160-5,5/2" and card["characteristics"]
    # Срок службы агрегата в документации Wilo не указан — так и показываем
    assert card["normative"]["life_years"] is None
    assert "normative" in card["resource"]["missing_data"]
    assert card["deviations_count"] == 1
    kinds = {c["kind"] for c in card["components"]}
    assert kinds == {"node", "part"}
    assert len(card["history"]) == 9
    # Все уровни внимания есть в демо-данных
    assert {c["attention"]["level"] for c in card["components"]} == {"defect", "check", "none", "unknown"}


def test_4_parameters_against_setpoints():
    params = {p["id"]: p for p in client.get("/api/equipment/PU-001").json()["parameters"]}
    assert params["P-01"]["status"] == "deviation"
    assert params["P-01"]["message"] == "Выше верхней уставки на 0,4 бар"
    assert params["P-09"]["status"] == "no_data"
    # Вибрация и температура — из баз значений заказчика, замер 13.11 09:00
    assert params["P-02"]["status"] == "normal" and params["P-02"]["value"] == 0.8
    assert params["P-02"]["setpoint_max"] == 2.8
    assert params["P-07"]["value"] == 65.0
    assert params["P-07"]["measured_at"] == "2026-11-13T09:00:00+03:00"


def test_4_both_samples_have_cards():
    for eq in ("PU-001", "PU-002"):
        card = client.get(f"/api/equipment/{eq}").json()
        nodes = [c for c in card["components"] if c["kind"] == "node"]
        parts = [c for c in card["components"] if c["kind"] == "part"]
        assert 2 <= len(nodes) <= 3 and 5 <= len(parts) <= 8


def test_4_unknown_equipment():
    r = client.get("/api/equipment/XX-999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_4_no_visible_issues_has_note():
    v = comp(client.get("/api/equipment/PU-001").json(), "C-04")["visual"]
    assert v["category"] == "no_visible_issues"
    assert v["note"] == "Отсутствие видимых дефектов не подтверждает исправность оборудования"
    assert v["disclaimer"]


def test_5_attention_sorted_with_hints():
    items = client.get("/api/equipment/PU-001/attention").json()["items"]
    levels = [i["level"] for i in items]
    order = ["defect", "check", "unknown", "none"]
    assert levels == sorted(levels, key=order.index)
    assert {"C-02", "N-02", "C-06", "C-03", "N-01"} <= {i["component_id"] for i in items}
    assert all(i["hint"].startswith("Наведите камеру на ") for i in items)


def test_6_detect_match_kinds():
    r = client.post("/api/equipment/PU-001/detect", files=JPEG).json()
    by_class = {d["cv_class"]: d for d in r["detections"]}
    assert by_class["pressure_gauge"]["match"] == "matched"
    assert by_class["pressure_gauge"]["component_id"] == "C-02"
    assert by_class["pressure_gauge"]["attention_level"] == "defect"
    assert by_class["valve"]["match"] == "ambiguous"
    assert by_class["valve"]["candidates"] == ["C-03", "C-04"]
    assert "C-05" in r["not_in_frame"]
    r = client.post("/api/equipment/PU-002/detect", files=JPEG).json()
    assert {d["match"] for d in r["detections"]} == {"matched", "not_in_card"}


def test_6_detect_requires_image():
    r = client.post("/api/equipment/PU-001/detect")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_7_analyze_saves_visual():
    c = client.post("/api/equipment/PU-001/components/C-05/analyze", files=JPEG,
                    data={"detection_confidence": "0.8"}).json()
    assert c["visual"]["category"] == "check_recommended"
    assert c["visual"]["disclaimer"] and c["visual"]["detection_confidence"] == 0.8
    assert c["attention"]["level"] == "check"
    again = client.get("/api/equipment/PU-001/components/C-05").json()
    assert again["visual"]["category"] == "check_recommended"


def test_8_component():
    c = client.get("/api/equipment/PU-001/components/C-02").json()
    assert c["attention"]["level"] == "defect" and c["parameters"] == ["P-01"]
    assert c["attention"]["recommended_action"] == "Провести поверку манометра"
    assert c["previous_results"][0]["type"] == "maintenance"
    assert client.get("/api/equipment/PU-001/components/NOPE").status_code == 404


@pytest.mark.parametrize("kind", ["defect", "remark"])
def test_9_comment_required(kind):
    r = client.post("/api/equipment/PU-001/inspections",
                    json={"component_id": "C-02", "type": kind, "comment": " "})
    assert r.status_code == 422 and r.json()["error"]["code"] == "comment_required"


def test_9_unknown_type_rejected():
    r = client.post("/api/equipment/PU-001/inspections", json={"type": "repair"})
    assert r.status_code == 422


def test_9_and_10_inspection_goes_to_history():
    r = client.post("/api/equipment/PU-001/inspections", json={
        "component_id": "C-02", "type": "defect", "comment": "Стекло треснуло",
        "performed_by": "Инженер Иванов", "attach_last_visual": True})
    assert r.status_code == 201
    entry = r.json()["inspection"]
    assert entry["visual"]["category"] == "check_recommended"
    history = client.get("/api/equipment/PU-001/history").json()["items"]
    assert history[0]["id"] == entry["id"]


def test_9_checked_whole_equipment():
    r = client.post("/api/equipment/PU-001/inspections",
                    json={"component_id": None, "type": "checked", "performed_by": "Инженер"})
    assert r.status_code == 201 and r.json()["component"] is None


def test_9_maintenance_recalculates():
    r = client.post("/api/equipment/PU-001/inspections",
                    json={"component_id": "C-02", "type": "maintenance", "comment": "Поверка"})
    c = r.json()["component"]
    assert c["last_maintenance_at"] == "2026-11-13"
    assert c["resource"]["maintenance"]["status"] == "ok"
    assert r.json()["inspection"]["recommendation"] == "Следующее обслуживание — 13.11.2027"


def test_9_replacement_resets_component():
    r = client.post("/api/equipment/PU-001/inspections",
                    json={"component_id": "C-07", "type": "replacement", "comment": "Новые подшипники"})
    c = r.json()["component"]
    assert c["last_replaced_at"] == "2026-11-13"
    assert c["usage"]["operating_hours"] == 0
    assert c["visual"]["category"] == "not_analyzed"
    assert c["resource"]["status"] == "ok" and c["resource"]["used_percent"] == 0


def test_9_replacement_needs_component():
    r = client.post("/api/equipment/PU-001/inspections", json={"type": "replacement"})
    assert r.status_code == 422


def test_openapi_json_is_up_to_date():
    path = Path(__file__).resolve().parent.parent / "openapi.json"
    assert json.loads(path.read_text(encoding="utf-8")) == app.openapi(), \
        "Обновите схему: python -m app.export_openapi"


def test_9_recorded_defect_turns_component_red_until_fixed():
    def level():
        return client.get("/api/equipment/PU-001/components/C-04").json()["attention"]
    assert level()["level"] == "none"
    client.post("/api/equipment/PU-001/inspections",
                json={"component_id": "C-04", "type": "defect", "comment": "Течь по сальнику"})
    a = level()
    assert a["level"] == "defect" and a["reasons"][0] == "Зафиксирован дефект: Течь по сальнику"
    client.post("/api/equipment/PU-001/inspections",
                json={"component_id": "C-04", "type": "maintenance", "comment": "Подтянут сальник"})
    assert level()["level"] == "none"


@pytest.mark.parametrize("eq", ["PU-001", "PU-002"])
def test_4_5_every_component_complete_or_gap_named(eq):
    """Матрица 4.5: у каждого компонента есть характеристики, норматив и дата установки —
    а если чего-то нет, это явно названо в missing_data (ТЗ 4.3)."""
    for c in client.get(f"/api/equipment/{eq}").json()["components"]:
        n, missing = c["normative"], c["resource"]["missing_data"]
        assert c["characteristics"], c["id"]
        assert any(n[k] for k in ("life_years", "life_hours", "life_cycles")) or "normative" in missing, c["id"]
        assert c["installed_at"] or "installed_at" in missing, c["id"]
        assert "last_replaced_at" in c and c["previous_results"] is not None, c["id"]
