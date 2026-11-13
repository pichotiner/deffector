"""Проверка заглушки: все 11 запросов контракта отвечают в нужном формате.

    cd backend && python -m pytest
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, reset_state

client = TestClient(app)
JPEG = {"image": ("frame.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")}


@pytest.fixture(autouse=True)
def _fresh_state():
    reset_state()


def test_11_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_1_list_and_search():
    assert {i["id"] for i in client.get("/api/equipment").json()["items"]} == {"PU-001", "CC-001"}
    assert [i["id"] for i in client.get("/api/equipment?q=насос").json()["items"]] == ["PU-001"]


@pytest.mark.parametrize("query, by", [
    ("qr=KST:PU-001", "qr"),
    ("serial=SN2021-004587", "serial"),
    ("serial=sn 2021 OO4587", "serial"),  # регистр, пробелы, O вместо 0
    ("marking=PU001", "marking"),
])
def test_2_lookup_found(query, by):
    r = client.get(f"/api/equipment/lookup?{query}").json()
    assert r["found"] and r["equipment_id"] == "PU-001" and r["matched_by"] == by


def test_2_lookup_not_found_gives_suggestions():
    r = client.get("/api/equipment/lookup?serial=SN2021-004500").json()
    assert r["found"] is False and r["suggestions"][0]["equipment_id"] == "PU-001"


def test_2_lookup_without_params_is_error():
    r = client.get("/api/equipment/lookup")
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_3_identify():
    r = client.post("/api/identify/image", files=JPEG).json()
    assert r["recognized"] and r["candidates"][0]["name"] == "Насосный агрегат"


def test_4_card_has_three_separate_blocks():
    card = client.get("/api/equipment/PU-001").json()
    assert card["parameters"] and card["components"] and card["history"]
    for c in card["components"]:
        assert {"normative", "resource", "visual", "attention"} <= c.keys()
    assert {c["attention"]["level"] for c in card["components"]} == {"defect", "check", "none", "unknown"}


def test_4_unknown_equipment():
    r = client.get("/api/equipment/XX-999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_5_attention_sorted():
    items = client.get("/api/equipment/PU-001/attention").json()["items"]
    levels = [i["level"] for i in items]
    assert levels == sorted(levels, key=["defect", "check"].index)
    assert all(i["hint"].startswith("Наведите камеру на ") for i in items)


def test_6_detect_match_kinds():
    r = client.post("/api/equipment/PU-001/detect", files=JPEG).json()
    matches = {d["cv_class"]: d["match"] for d in r["detections"]}
    assert matches["pressure_gauge"] == "matched"
    assert matches["valve"] == "ambiguous"  # одна рамка, две задвижки в карточке
    assert "C-05" in r["not_in_frame"]
    r = client.post("/api/equipment/CC-001/detect", files=JPEG).json()
    assert {d["match"] for d in r["detections"]} == {"matched", "not_in_card"}


def test_6_detect_requires_image():
    assert client.post("/api/equipment/PU-001/detect").status_code == 422


def test_7_analyze_saves_visual():
    c = client.post("/api/equipment/PU-001/components/C-05/analyze", files=JPEG).json()
    assert c["visual"]["category"] == "check_recommended" and c["visual"]["disclaimer"]
    again = client.get("/api/equipment/PU-001/components/C-05").json()
    assert again["visual"]["category"] == "check_recommended"


def test_8_component():
    c = client.get("/api/equipment/PU-001/components/C-02").json()
    assert c["attention"]["level"] == "defect" and c["parameters"] == ["P-01"]
    assert client.get("/api/equipment/PU-001/components/NOPE").status_code == 404


def test_9_defect_requires_comment():
    r = client.post("/api/equipment/PU-001/inspections",
                    json={"component_id": "C-02", "type": "defect", "comment": " "})
    assert r.status_code == 422 and r.json()["error"]["code"] == "comment_required"


def test_9_and_10_inspection_goes_to_history():
    r = client.post("/api/equipment/PU-001/inspections", json={
        "component_id": "C-02", "type": "defect", "comment": "Стекло треснуло",
        "performed_by": "Инженер Иванов", "attach_last_visual": True})
    assert r.status_code == 201
    entry = r.json()["inspection"]
    assert entry["visual"]["category"] == "check_recommended"
    history = client.get("/api/equipment/PU-001/history").json()["items"]
    assert history[0]["id"] == entry["id"]


def test_9_replacement_resets_component():
    r = client.post("/api/equipment/PU-001/inspections",
                    json={"component_id": "N-02", "type": "replacement", "comment": "Новый двигатель"})
    c = r.json()["component"]
    assert c["visual"]["category"] == "not_analyzed"
    assert c["usage"]["operating_hours"] == 0 and c["resource"]["status"] == "ok"
