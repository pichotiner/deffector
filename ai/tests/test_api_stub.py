import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import rules
from app.main import ApiError, parse_classes


@pytest.fixture(scope="module")
def client():
    import os

    os.environ["AI_STUB"] = "1"
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (100, 100, 100)).save(buffer, format="JPEG")
    return {"image": ("frame.jpg", buffer.getvalue(), "image/jpeg")}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "ready": True, "stub": True, "models": {}}


def test_detect_all_and_filtered(client):
    everything = client.post("/detect", files=jpeg()).json()
    assert {d["cv_class"] for d in everything} == {"electric_motor", "pressure_gauge", "valve", "flange"}
    for detection in everything:
        assert set(detection) == {"bbox", "cv_class", "confidence"}
        assert len(detection["bbox"]) == 4 and all(0 <= v <= 1 for v in detection["bbox"])
    for classes in ("flange,valve", '["flange", "valve"]'):
        filtered = client.post("/detect", files=jpeg(), data={"classes": classes}).json()
        assert {d["cv_class"] for d in filtered} == {"flange", "valve"}
    repeated = client.post("/detect", files=jpeg(), data={"classes": ["flange", "valve"]}).json()
    assert {d["cv_class"] for d in repeated} == {"flange", "valve"}


@pytest.mark.parametrize(
    "component_type, category, quality",
    [
        ("electric_motor", "no_visible_issues", "ok"),
        ("pressure_gauge", "check_recommended", "ok"),
        ("flange", "possible_defect", "ok"),
        ("valve", "check_recommended", "poor"),
    ],
)
def test_analyze_covers_all_branches(client, component_type, category, quality):
    body = client.post(
        "/analyze", files=jpeg(), data={"component_type": component_type, "component_name": "Узел"}
    ).json()
    assert set(body) == {
        "category", "signs", "explanation", "recommendation", "assessment_confidence", "image_quality"}
    assert body["category"] == category and body["image_quality"] == quality
    assert all(sign in rules.SIGNS.values() for sign in body["signs"])
    assert not rules.has_forbidden(body["explanation"] + " " + body["recommendation"])


def test_identify(client):
    body = client.post("/identify", files=jpeg()).json()
    assert body["recognized"] is True
    assert body["candidates"][0] == {"equipment_id": "PU-001", "confidence": 0.82}


def test_errors_use_contract_format(client):
    bad = client.post("/detect", files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "bad_image"
    missing = client.post("/detect")
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "bad_request"
    assert client.get("/nope").json()["error"]["code"] == "not_found"


def test_parse_classes():
    assert parse_classes(None) is None
    assert parse_classes([""]) is None
    assert parse_classes(["valve, flange", "valve"]) == ["valve", "flange"]
    assert parse_classes(['["valve"]']) == ["valve"]
    with pytest.raises(ApiError):
        parse_classes(["[broken"])
