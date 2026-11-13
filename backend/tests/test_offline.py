"""Бэкенд не обращается во внешнюю сеть (план, раздел 4.1).

Весь сценарий — все 11 запросов, в режиме заглушки и с ИИ-сервисом (поддельным, на этом
же ПК) — проходит, пока любое сетевое соединение не с локальным адресом запрещено.
"""

import ipaddress
import socket

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_ai_real import fake_ai  # noqa: F401 — фикстура поддельного ИИ-сервиса

client = TestClient(app)
JPEG = {"image": ("frame.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")}


@pytest.fixture
def no_internet(monkeypatch):
    attempts = []
    real_connect = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        try:
            local = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if not local:
            attempts.append(address)
            raise OSError(f"обращение во внешнюю сеть: {address}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield attempts
    assert attempts == [], f"бэкенд пытался выйти в сеть: {attempts}"


def scenario():
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/equipment?q=агрегат").status_code == 200
    assert client.get("/api/equipment/lookup?qr=KST:PU-001").json()["found"]
    assert client.post("/api/identify/image", files=JPEG).status_code == 200
    assert client.get("/api/equipment/PU-001").status_code == 200
    assert client.get("/api/equipment/PU-001/attention").status_code == 200
    assert client.post("/api/equipment/PU-001/detect", files=JPEG).status_code == 200
    assert client.post("/api/equipment/PU-001/components/C-02/analyze", files=JPEG).status_code == 200
    assert client.get("/api/equipment/PU-001/components/C-02").status_code == 200
    r = client.post("/api/equipment/PU-001/inspections",
                    json={"component_id": "C-02", "type": "checked", "attach_last_visual": True})
    assert r.status_code == 201
    assert client.get("/api/equipment/PU-001/history").json()["items"][0]["type"] == "checked"


def test_scenario_without_internet_stub_ai(no_internet):
    scenario()


def test_scenario_without_internet_real_ai(no_internet, fake_ai):  # noqa: F811
    assert client.get("/api/health").json()["ai"]["status"] == "ok"
    scenario()


def test_guard_really_blocks(no_internet):
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 443), timeout=1)
    no_internet.clear()
