"""Ответы настоящего бэкенда на отдельной временной БД для тестов Android-клиента."""
import json
import os
from pathlib import Path
import sys
import tempfile
import socket
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))


def main():
    (ROOT / ".tools").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=ROOT / ".tools") as temp:
        os.environ["DEFFECTOR_DB_PATH"] = str(Path(temp) / "test.sqlite3")
        os.environ["DEFFECTOR_TODAY"] = "2026-11-13"
        os.environ["DEFFECTOR_AI_MODE"] = "stub"
        dest = ROOT / "app/src/test/resources"
        dest.mkdir(parents=True, exist_ok=True)
        image = b'--mobile-test\r\nContent-Disposition: form-data; name="image"; filename="frame.jpg"\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8\xff\xe0fake\r\n--mobile-test--\r\n'
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                                   cwd=ROOT.parent / "backend", env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        class Client:
            token = None
            def get(self, path):
                return self.request(path)
            def post(self, path, files=None, json=None):
                import json as codec
                data = image if files else codec.dumps(json).encode()
                content_type = "multipart/form-data; boundary=mobile-test" if files else "application/json"
                return self.request(path, data, content_type)
            def request(self, path, data=None, content_type="application/json"):
                headers = {"Content-Type": content_type}
                if self.token:
                    headers["Authorization"] = "Bearer " + self.token
                request = urllib.request.Request(f"http://127.0.0.1:{port}" + path, data=data, headers=headers)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=10) as response:
                    return response.read().decode("utf-8")
        client = Client()
        try:
            for _ in range(100):
                try:
                    client.get("/api/health")
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError("Не удалось запустить тестовый бэкенд")
                    time.sleep(.1)
            else:
                raise RuntimeError("Бэкенд не запустился за 10 секунд")
            login = client.post("/api/auth/login", json={"email": "master@kst.local", "password": "Master-102"})
            client.token = json.loads(login)["token"]
            responses = {
                "login": login,
                "me": client.get("/api/auth/me"),
                "health": client.get("/api/health"),
                "equipment-list": client.get("/api/equipment"),
                "lookup": client.get("/api/equipment/lookup?qr=KST:PU-001"),
                "lookup-miss": client.get("/api/equipment/lookup?serial=SN2024-004500"),
                "card": client.get("/api/equipment/PU-001"),
                "card-second": client.get("/api/equipment/PU-002"),
                "attention": client.get("/api/equipment/PU-001/attention"),
                "detect": client.post("/api/equipment/PU-001/detect", files=image),
                "identify": client.post("/api/identify/image", files=image),
                "component": client.get("/api/equipment/PU-001/components/C-02"),
                "analyze": client.post("/api/equipment/PU-001/components/C-02/analyze", files=image),
                "inspection": client.post("/api/equipment/PU-001/inspections", json={
                    "component_id": "C-02", "type": "defect", "comment": "Тест мобильного клиента",
                    "performed_by": "Тест", "attach_last_visual": True,
                }),
                "history": client.get("/api/equipment/PU-001/history"),
            }
            for name, response in responses.items():
                (dest / f"{name}.json").write_text(json.dumps(json.loads(response), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Сохранено {len(responses)} ответов бэкенда в {dest}")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
