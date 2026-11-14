"""Вход по почте и паролю, роли и права, учётные записи, выгрузка отчёта (PDF, Excel).

    cd backend && python -m pytest tests/test_auth.py
"""

import io
import zipfile
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from app import auth, config, db
from app.main import app

from conftest import bearer

anon = TestClient(app)          # без входа
JPEG = {"image": ("frame.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")}
ENGINEER, MASTER, ADMIN = "engineer@kst.local", "master@kst.local", "admin@kst.local"


def login(email, password):
    return anon.post("/api/auth/login", json={"email": email, "password": password})


# ---------- вход ----------

def test_login_by_email_and_password():
    r = login("  Engineer@KST.local ", "Engineer-102")      # регистр и пробелы в почте не важны
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == {
        "id": body["user"]["id"], "email": ENGINEER, "name": "Иванов И. И.", "role": "engineer",
        "role_name": "Инженер", "active": True, "permissions": ["view", "inspect"]}
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert anon.get("/api/auth/me", headers=headers).json()["email"] == ENGINEER
    assert anon.get("/api/equipment", headers=headers).status_code == 200


@pytest.mark.parametrize("email, password", [
    (ENGINEER, "wrong-password"), ("nobody@kst.local", "Engineer-102"), ("", ""), (ENGINEER, "")])
def test_wrong_credentials_are_rejected_without_details(email, password):
    r = login(email, password)
    assert r.status_code == 401
    assert r.json()["error"] == {"code": "invalid_credentials", "message": "Неверная почта или пароль"}


def test_every_request_needs_login_except_health_and_login():
    assert anon.get("/api/health").status_code == 200
    for method, path in [
            ("GET", "/api/equipment"), ("GET", "/api/equipment/lookup?qr=PU-001"),
            ("GET", "/api/equipment/PU-001"), ("GET", "/api/equipment/PU-001/attention"),
            ("GET", "/api/equipment/PU-001/components/C-02"), ("GET", "/api/equipment/PU-001/history"),
            ("GET", "/api/equipment/PU-001/report"), ("GET", "/api/users"), ("GET", "/api/auth/me"),
            ("POST", "/api/identify/image"), ("POST", "/api/equipment/PU-001/detect"),
            ("POST", "/api/equipment/PU-001/components/C-02/analyze"),
            ("POST", "/api/equipment/PU-001/inspections"), ("POST", "/api/users")]:
        r = anon.request(method, path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthorized", path


def test_unknown_and_expired_tokens_are_rejected(monkeypatch):
    assert anon.get("/api/equipment", headers={"Authorization": "Bearer nope"}).status_code == 401
    monkeypatch.setitem(config.SETTINGS, "auth_token_hours", -1)     # вход уже истёк
    assert anon.get("/api/equipment", headers=bearer(ENGINEER)).status_code == 401


def test_logout_ends_the_session():
    headers = bearer(ENGINEER)
    assert anon.post("/api/auth/logout", headers=headers).status_code == 204
    assert anon.get("/api/auth/me", headers=headers).status_code == 401


def test_password_guessing_is_locked_for_a_minute():
    for _ in range(5):
        assert login(MASTER, "bad").status_code == 401
    r = login(MASTER, "Master-102")                         # верный пароль во время блокировки
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"
    assert login(ENGINEER, "Engineer-102").status_code == 200   # другие учётные записи не задеты


def test_passwords_are_stored_only_as_salted_hashes():
    with db.session() as conn:
        stored = [a["password_hash"] for a in auth.accounts(conn)]
    assert all(h.startswith("pbkdf2_sha256$") for h in stored)
    assert not any(password in h for h in stored for _, _, _, password in auth.DEMO_ACCOUNTS)
    assert len(set(h.split("$")[2] for h in stored)) == len(stored)      # соль у каждого своя
    token = login(ENGINEER, "Engineer-102").json()["token"]
    with db.session() as conn:
        tokens = [r[0] for r in conn.execute("SELECT token_hash FROM auth_session")]
    assert token not in tokens                                           # в базе только SHA-256


# ---------- роли и права ----------

# право → запрос, которым оно проверяется
REQUESTS = {
    "view": ("GET", "/api/equipment/PU-001", {}),
    "inspect": ("POST", "/api/equipment/PU-001/inspections",
                {"json": {"component_id": "C-02", "type": "checked"}}),
    "report": ("GET", "/api/equipment/PU-001/report?format=xlsx", {}),
    "users": ("GET", "/api/users", {}),
}


@pytest.mark.parametrize("email, role, granted", [
    (ENGINEER, "Инженер", {"view", "inspect"}),
    (MASTER, "Мастер", {"view", "inspect", "report"}),
    (ADMIN, "Администратор", {"view", "report", "users"}),
])
def test_role_permissions_are_checked_on_the_server(email, role, granted):
    headers = bearer(email)
    assert set(anon.get("/api/auth/me", headers=headers).json()["permissions"]) == granted
    for permission, (method, path, kwargs) in REQUESTS.items():
        r = anon.request(method, path, headers=headers, **kwargs)
        if permission in granted:
            assert r.status_code in (200, 201), (role, permission, r.text)
        else:
            assert r.status_code == 403, (role, permission)
            error = r.json()["error"]
            assert error["code"] == "forbidden" and role in error["message"]


def test_admin_cannot_run_ar_inspection():
    headers = bearer(ADMIN)
    assert anon.post("/api/equipment/PU-001/detect", files=JPEG, headers=headers).status_code == 403
    assert anon.post("/api/equipment/PU-001/components/C-02/analyze", files=JPEG,
                     headers=headers).status_code == 403
    assert anon.post("/api/identify/image", files=JPEG, headers=headers).status_code == 200


def test_inspection_is_signed_by_the_logged_in_user():
    """Автор записи — учётная запись, а не текст из запроса."""
    r = anon.post("/api/equipment/PU-001/inspections", headers=bearer(MASTER), json={
        "component_id": "C-02", "type": "remark", "comment": "Проверка автора",
        "performed_by": "Кто-то другой"})
    assert r.status_code == 201
    assert r.json()["inspection"]["performed_by"] == "Петров П. П."
    history = anon.get("/api/equipment/PU-001/history", headers=bearer(ENGINEER)).json()["items"]
    assert history[0]["performed_by"] == "Петров П. П."


def test_fallback_mode_without_login(monkeypatch):
    """auth_required: false — запасной режим стенда для сборки приложения без входа."""
    monkeypatch.setitem(config.SETTINGS, "auth_required", False)
    assert anon.get("/api/equipment/PU-001").status_code == 200
    r = anon.post("/api/equipment/PU-001/inspections", json={
        "component_id": "C-02", "type": "checked", "performed_by": "Инженер из приложения"})
    assert r.status_code == 201 and r.json()["inspection"]["performed_by"] == "Инженер из приложения"
    assert anon.get("/api/equipment/PU-001/report").status_code == 403      # отчёты и учётные
    assert anon.get("/api/users").status_code == 403                        # записи — только со входом
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/equipment", headers={"Authorization": "Bearer nope"}).status_code == 401


# ---------- учётные записи ----------

def test_admin_manages_accounts():
    admin = bearer(ADMIN)
    users = anon.get("/api/users", headers=admin).json()["items"]
    assert [(u["email"], u["role"]) for u in users] == [
        (ENGINEER, "engineer"), (MASTER, "master"), (ADMIN, "admin")]

    new = anon.post("/api/users", headers=admin, json={
        "email": "New.Engineer@kst.local", "name": "Смирнов С. С.", "role": "engineer",
        "password": "Smirnov-2026"})
    assert new.status_code == 201 and new.json()["email"] == "new.engineer@kst.local"
    uid = new.json()["id"]
    token = login("new.engineer@kst.local", "Smirnov-2026").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert anon.get("/api/equipment/PU-001/report", headers=headers).status_code == 403

    # роль меняется — права меняются сразу, без нового входа
    assert anon.patch(f"/api/users/{uid}", headers=admin, json={"role": "master"}).json()["role"] == "master"
    assert anon.get("/api/equipment/PU-001/report?format=xlsx", headers=headers).status_code == 200

    # смена пароля завершает прежние входы
    assert anon.patch(f"/api/users/{uid}", headers=admin, json={"password": "Another-2026"}).status_code == 200
    assert anon.get("/api/auth/me", headers=headers).status_code == 401
    assert login("new.engineer@kst.local", "Smirnov-2026").status_code == 401
    assert login("new.engineer@kst.local", "Another-2026").status_code == 200

    # отключённая учётная запись войти не может
    assert anon.patch(f"/api/users/{uid}", headers=admin, json={"active": False}).json()["active"] is False
    assert login("new.engineer@kst.local", "Another-2026").status_code == 401


@pytest.mark.parametrize("body, status, code", [
    ({"email": "engineer@kst.local", "name": "Дубль", "role": "engineer", "password": "Password-1"}, 409, "conflict"),
    ({"email": "не почта", "name": "Имя", "role": "engineer", "password": "Password-1"}, 422, "validation_error"),
    ({"email": "a@kst.local", "name": "Имя", "role": "engineer", "password": "short"}, 422, "validation_error"),
    ({"email": "a@kst.local", "name": " ", "role": "engineer", "password": "Password-1"}, 422, "validation_error"),
    ({"email": "a@kst.local", "name": "Имя", "role": "director", "password": "Password-1"}, 422, "validation_error"),
])
def test_account_validation(body, status, code):
    r = anon.post("/api/users", headers=bearer(ADMIN), json=body)
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_last_admin_cannot_be_removed():
    admin = bearer(ADMIN)
    me = anon.get("/api/auth/me", headers=admin).json()["id"]
    for change in ({"role": "engineer"}, {"active": False}):
        r = anon.patch(f"/api/users/{me}", headers=admin, json=change)
        assert r.status_code == 422, change
    assert anon.patch("/api/users/999", headers=admin, json={"name": "Нет такого"}).status_code == 404


def test_accounts_and_sessions_survive_demo_reset():
    """Сброс демо-данных перед показом не разлогинивает телефон."""
    from app import seed
    headers = bearer(ENGINEER)
    conn = db.connect()
    try:
        seed.seed(conn)
    finally:
        conn.close()
    assert anon.get("/api/auth/me", headers=headers).status_code == 200


def test_database_created_before_login_gets_accounts():
    with db.session() as conn:
        conn.execute("DROP TABLE auth_session")
        conn.execute("DROP TABLE account")
        auth.ensure(conn)
    assert login(ADMIN, "Admin-102").status_code == 200


# ---------- выгрузка отчёта ----------

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def xlsx_sheets(data):
    """{название листа: [[ячейки строки]]} — разбор стандартной библиотекой."""
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.testzip() is None
    book = ElementTree.fromstring(z.read("xl/workbook.xml"))
    out = {}
    for i, sheet in enumerate(book.iter("{%s}sheet" % NS["m"]), 1):
        root = ElementTree.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
        out[sheet.get("name")] = [
            ["".join(t.text or "" for t in c.iter("{%s}t" % NS["m"])) for c in row.findall("m:c", NS)]
            for row in root.iter("{%s}row" % NS["m"])]
    return out


def test_report_xlsx_has_card_components_parameters_and_history():
    r = anon.get("/api/equipment/PU-001/report?format=xlsx", headers=bearer(MASTER))
    assert r.status_code == 200
    assert r.headers["content-type"] == \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert 'filename="otchet-PU-001-2026-11-13.xlsx"' in r.headers["content-disposition"]
    sheets = xlsx_sheets(r.content)
    assert list(sheets) == ["Сводка", "Узлы", "Параметры", "История"]

    summary = dict(row for row in sheets["Сводка"] if len(row) == 2)
    assert summary["Оборудование"].startswith("PU-001")
    assert summary["Серийный номер"] == "SN2024-004587"
    assert summary["Сформировал"] == "Петров П. П. (Мастер)"
    assert summary["Период истории осмотров"] == "за всё время"

    card = anon.get("/api/equipment/PU-001", headers=bearer(MASTER)).json()
    components = sheets["Узлы"]
    assert components[0][:4] == ["Код", "Узел", "Тип", "Состояние"]
    assert [row[0] for row in components[1:]] == [c["id"] for c in card["components"]]
    c02 = next(row for row in components if row[0] == "C-02")
    assert c02[3] == "Требует внимания" and "Рекомендуется проверка" in c02[7]
    assert len(sheets["Параметры"]) == len(card["parameters"]) + 1
    assert any(row[5] == "Отклонение" for row in sheets["Параметры"])
    assert len(sheets["История"]) == len(card["history"]) + 1
    assert int(summary["Записей за период"]) == len(card["history"])


def test_report_period_limits_history():
    headers = bearer(MASTER)
    anon.post("/api/equipment/PU-001/inspections", headers=headers, json={
        "component_id": "C-02", "type": "defect", "comment": "Стекло треснуло"})
    r = anon.get("/api/equipment/PU-001/report?format=xlsx&date_from=2026-11-14", headers=headers)
    history = xlsx_sheets(r.content)["История"]
    today = config.now_iso()[:10]
    if today >= "2026-11-14":                 # запись сделана «сейчас» — попадает в период
        assert [row[3] for row in history[1:]] == ["Стекло треснуло"]
        assert history[1][4] == "Петров П. П." and history[1][2] == "Обнаружен дефект"
    r = anon.get("/api/equipment/PU-001/report?format=xlsx&date_to=2000-01-01", headers=headers)
    assert xlsx_sheets(r.content)["История"][1:] == [["Записей нет"]]


def test_report_pdf():
    r = anon.get("/api/equipment/PU-002/report", headers=bearer(ADMIN))       # pdf — по умолчанию
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and r.content.rstrip().endswith(b"%%EOF")
    assert 'filename="otchet-PU-002-2026-11-13.pdf"' in r.headers["content-disposition"]
    assert b"DejaVuSans" in r.content                                         # шрифт с кириллицей вложен


def test_report_pdf_splits_a_long_inspection_across_pages():
    headers = bearer(MASTER)
    r = anon.post("/api/equipment/PU-001/inspections", headers=headers, json={
        "component_id": "C-02", "type": "remark", "comment": "Строка осмотра\n" * 180})
    assert r.status_code == 201
    r = anon.get("/api/equipment/PU-001/report?format=pdf", headers=headers)
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-") and r.content.rstrip().endswith(b"%%EOF")


def test_report_xlsx_removes_invalid_xml_controls_without_changing_history():
    headers = bearer(MASTER)
    comment = "Течь\x00и\x0bвибрация\x1f\tосмотр\nзавершён"
    r = anon.post("/api/equipment/PU-001/inspections", headers=headers, json={
        "component_id": "C-02", "type": "remark", "comment": comment})
    assert r.status_code == 201 and r.json()["inspection"]["comment"] == comment
    r = anon.get("/api/equipment/PU-001/report?format=xlsx", headers=headers)
    assert r.status_code == 200
    sheets = xlsx_sheets(r.content)  # ElementTree отклоняет запрещённые XML 1.0 символы.
    assert sheets["История"][1][3] == "Течьивибрация\tосмотр\nзавершён"


@pytest.mark.parametrize("query, status", [
    ("format=docx", 422), ("date_from=13.11.2026", 422),
    ("date_from=2026-11-13&date_to=2026-11-01", 422)])
def test_report_validation(query, status):
    r = anon.get(f"/api/equipment/PU-001/report?{query}", headers=bearer(MASTER))
    assert r.status_code == status and r.json()["error"]["code"] == "validation_error"
    assert anon.get("/api/equipment/PU-404/report", headers=bearer(MASTER)).status_code == 404


def test_report_pdf_without_library_says_what_to_do(monkeypatch):
    from app import reports

    def missing(_):
        raise reports.PdfUnavailable("no reportlab")
    monkeypatch.setattr(reports, "to_pdf", missing)
    r = anon.get("/api/equipment/PU-001/report?format=pdf", headers=bearer(MASTER))
    assert r.status_code == 503 and r.json()["error"]["code"] == "report_unavailable"
    assert anon.get("/api/equipment/PU-001/report?format=xlsx", headers=bearer(MASTER)).status_code == 200
