"""Режим ai_mode = "real": бэкенд ↔ ИИ-сервис по docs/ai-contract.md.

Вместо сервиса Тимофея — поддельный HTTP-сервер с тем же контрактом.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)
JPEG = {"image": ("frame.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")}


class FakeAI(BaseHTTPRequestHandler):
    analyze_reply = None
    delay = 0.0
    last_body = b""

    def log_message(self, *args):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"status": "ok"}) if self.path == "/health" else self._send(404, {})

    def do_POST(self):
        FakeAI.last_body = self.rfile.read(int(self.headers["Content-Length"]))
        time.sleep(FakeAI.delay)
        if self.path == "/detect":
            self._send(200, [
                {"bbox": [0.40, 0.20, 0.10, 0.10], "cv_class": "pressure_gauge", "confidence": 0.9},
                {"bbox": [0.20, 0.50, 0.10, 0.20], "cv_class": "valve", "confidence": 0.8},
                {"bbox": [0.70, 0.50, 0.10, 0.20], "cv_class": "valve", "confidence": 0.8},
                {"bbox": [0.95, 0.90, 0.20, 0.30], "cv_class": "electric_motor", "confidence": 0.7},
            ])
        elif self.path == "/analyze":
            self._send(200, FakeAI.analyze_reply)
        elif self.path == "/identify":
            self._send(200, {"recognized": True, "candidates": [
                {"equipment_id": "CC-001", "confidence": 0.3},
                {"equipment_id": "PU-001", "confidence": 0.77},
                {"equipment_id": "XX-999", "confidence": 0.9}]})
        else:
            self._send(404, {})


@pytest.fixture
def fake_ai(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAI)
    server.handle_error = lambda *a: None  # бэкенд по таймауту закрыл соединение — это ожидаемо
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeAI.delay = 0.0
    FakeAI.analyze_reply = {
        "category": "possible_defect", "signs": ["течь/подтёки"],
        "explanation": "Под фланцем видны мокрые следы", "recommendation": "Проверить затяжку фланца",
        "assessment_confidence": 0.75, "image_quality": "ok"}
    monkeypatch.setitem(config.SETTINGS, "ai_mode", "real")
    monkeypatch.setitem(config.SETTINGS, "ai_url", f"http://127.0.0.1:{server.server_port}")
    yield FakeAI
    server.shutdown()


def test_health_reports_ai(fake_ai):
    assert client.get("/api/health").json()["ai"] == {"mode": "real", "status": "ok"}


def test_detect_sends_card_classes_and_matches_left_to_right(fake_ai):
    r = client.post("/api/equipment/PU-001/detect", files=JPEG).json()
    assert b'name="classes"' in fake_ai.last_body
    assert b"electric_motor,flange,pressure_gauge,valve" in fake_ai.last_body
    valves = sorted((d for d in r["detections"] if d["cv_class"] == "valve"), key=lambda d: d["bbox"][0])
    # две рамки, две задвижки: левая — C-03 (order 1), правая — C-04 (order 4)
    assert [v["component_id"] for v in valves] == ["C-03", "C-04"]
    assert all(v["match"] == "matched" for v in valves)
    motor = next(d for d in r["detections"] if d["cv_class"] == "electric_motor")
    x, y, w, h = motor["bbox"]
    assert x + w <= 1 and y + h <= 1  # рамка обрезана по краю кадра
    assert r["not_in_frame"] == ["C-05"]


def test_analyze_saves_ai_result(fake_ai):
    c = client.post("/api/equipment/PU-001/components/C-05/analyze", files=JPEG).json()
    assert c["visual"]["category"] == "possible_defect"
    assert c["visual"]["signs"] == ["течь/подтёки"]
    assert c["attention"]["level"] == "defect"
    assert b'name="component_type"' in fake_ai.last_body and b"flange" in fake_ai.last_body


@pytest.mark.parametrize("reply", [
    {"category": "all_good"},
    {"category": "исправен", "signs": []},
    {},
])
def test_analyze_bad_reply_never_says_no_issues(fake_ai, reply):
    fake_ai.analyze_reply = reply
    c = client.post("/api/equipment/PU-001/components/C-05/analyze", files=JPEG).json()
    assert c["visual"]["category"] == "check_recommended"
    assert c["visual"]["explanation"] == "Автоматический анализ не выполнен"


def test_no_visible_issues_gets_note(fake_ai):
    fake_ai.analyze_reply = {"category": "no_visible_issues", "signs": [],
                             "explanation": "Видимых проблем не обнаружено", "recommendation": None,
                             "assessment_confidence": 0.8, "image_quality": "ok"}
    v = client.post("/api/equipment/PU-001/components/C-05/analyze", files=JPEG).json()["visual"]
    assert v["note"] == "Отсутствие видимых дефектов не подтверждает исправность оборудования"


def test_identify_filters_unknown_and_sorts(fake_ai):
    r = client.post("/api/identify/image", files=JPEG).json()
    assert [c["equipment_id"] for c in r["candidates"]] == ["PU-001", "CC-001"]
    assert r["recognized"] is True


def test_identify_below_threshold(fake_ai, monkeypatch):
    monkeypatch.setitem(config.SETTINGS, "identify_threshold", 0.8)
    assert client.post("/api/identify/image", files=JPEG).json()["recognized"] is False


def test_detect_timeout_is_clear_error(fake_ai, monkeypatch):
    monkeypatch.setitem(config.SETTINGS, "ai_detect_timeout_seconds", 0.2)
    fake_ai.delay = 0.5
    r = client.post("/api/equipment/PU-001/detect", files=JPEG)
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"


def test_ai_down_is_clear_error(monkeypatch):
    monkeypatch.setitem(config.SETTINGS, "ai_mode", "real")
    monkeypatch.setitem(config.SETTINGS, "ai_url", "http://127.0.0.1:9")  # никто не слушает
    assert client.get("/api/health").json()["ai"]["status"] == "unavailable"
    for path in ("/api/equipment/PU-001/detect", "/api/identify/image",
                 "/api/equipment/PU-001/components/C-02/analyze"):
        r = client.post(path, files=JPEG)
        assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable", path
    # Неудачный анализ ничего не записал
    c = client.get("/api/equipment/PU-001/components/C-02").json()
    assert c["visual"]["explanation"].startswith("У резьбового соединения")
