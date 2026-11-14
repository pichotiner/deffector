"""Вход пользователей, роли и права (ответы организаторов: «роли и авторизация», вход —
по почте и паролю; роли — инженер, мастер, администратор).

Пароли хранятся только как PBKDF2-SHA256 с солью; токен входа — случайная строка, в базе
лежит его SHA-256. Всё на стандартной библиотеке, без сети.

Права по ролям — одна таблица PERMISSIONS:
  view    — карточки, параметры, история, идентификация оборудования;
  inspect — AR-осмотр, ИИ-анализ узла, запись результатов осмотра (ТЗ 4.6);
  report  — выгрузка отчёта (PDF, Excel);
  users   — учётные записи.
"""

import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta

from . import config, db

ROLES = {"engineer": "Инженер", "master": "Мастер", "admin": "Администратор"}

PERMISSIONS = {
    "view": ("engineer", "master", "admin"),
    "inspect": ("engineer", "master"),
    "report": ("master", "admin"),
    "users": ("admin",),
}
PERMISSION_LABELS = {
    "view": "просмотр карточек оборудования",
    "inspect": "осмотр и запись его результатов",
    "report": "выгрузка отчётов",
    "users": "управление учётными записями",
}

# Демо-учётные записи: создаются, когда таблица пуста. Пароли — в backend/README.md.
DEMO_ACCOUNTS = [
    ("engineer@kst.local", "Иванов И. И.", "engineer", "Engineer-102"),
    ("master@kst.local", "Петров П. П.", "master", "Master-102"),
    ("admin@kst.local", "Сидорова А. А.", "admin", "Admin-102"),
]

MIN_PASSWORD = 8
_ITERATIONS = 200_000
_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")

# Защита от подбора пароля: после 5 неудач подряд вход по этой почте закрыт на минуту.
_MAX_FAILURES, _LOCK_SECONDS = 5, 60
_failures: dict[str, tuple[int, float]] = {}


class AuthError(Exception):
    """code — код ошибки контракта, status — код HTTP."""

    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


# ---------- пароли ----------

def hash_password(password, salt=None, iterations=_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password, stored):
    try:
        _, iterations, salt, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt, int(iterations)), stored)


def normalize_email(email):
    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        raise AuthError(422, "validation_error", "Укажите почту в виде имя@организация.домен")
    return email


def check_password(password):
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(422, "validation_error", f"Пароль — не короче {MIN_PASSWORD} символов")


# ---------- учётные записи ----------

_demo_hashes = {}


def _demo_hash(email, password):
    # Хэш демо-пароля считается один раз за запуск: сброс учётных записей не ждёт PBKDF2.
    if email not in _demo_hashes:
        _demo_hashes[email] = hash_password(password)
    return _demo_hashes[email]


def ensure(conn):
    """Таблицы входа есть всегда, в том числе в базе, созданной до появления входа.
    Пустая таблица учётных записей заполняется демо-записями."""
    db.create_schema(conn, db.AUTH_SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM account").fetchone()[0] == 0:
        now = config.now_iso()
        for email, name, role, password in DEMO_ACCOUNTS:
            conn.execute(
                "INSERT INTO account (email, name, role, password_hash, active, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)", (email, name, role, _demo_hash(email, password), now))


def reset(conn):
    """Вернуть демо-учётные записи и завершить все входы."""
    conn.execute("DROP TABLE IF EXISTS auth_session")
    conn.execute("DROP TABLE IF EXISTS account")
    _failures.clear()
    ensure(conn)


def public(account):
    return {
        "id": account["id"], "email": account["email"], "name": account["name"],
        "role": account["role"], "role_name": ROLES[account["role"]],
        "active": bool(account["active"]),
        "permissions": [p for p, roles in PERMISSIONS.items() if account["role"] in roles],
    }


def accounts(conn):
    return db.rows(conn.execute("SELECT * FROM account ORDER BY id"))


def account(conn, account_id):
    return db.row(conn.execute("SELECT * FROM account WHERE id = ?", (account_id,)).fetchone())


def _check_role(role):
    if role not in ROLES:
        raise AuthError(422, "validation_error", "Роль — engineer, master или admin")


def create_account(conn, email, name, role, password):
    email = normalize_email(email)
    name = (name or "").strip()
    if not name:
        raise AuthError(422, "validation_error", "Укажите имя пользователя")
    _check_role(role)
    check_password(password)
    if conn.execute("SELECT 1 FROM account WHERE email = ?", (email,)).fetchone():
        raise AuthError(409, "conflict", "Учётная запись с такой почтой уже есть")
    cur = conn.execute(
        "INSERT INTO account (email, name, role, password_hash, active, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)", (email, name, role, hash_password(password), config.now_iso()))
    return account(conn, cur.lastrowid)


def update_account(conn, account_id, acting_id, name=None, role=None, active=None, password=None):
    target = account(conn, account_id)
    if target is None:
        raise AuthError(404, "not_found", "Учётная запись не найдена")
    fields = {}
    if name is not None:
        if not name.strip():
            raise AuthError(422, "validation_error", "Укажите имя пользователя")
        fields["name"] = name.strip()
    if role is not None:
        _check_role(role)
        fields["role"] = role
    if active is not None:
        fields["active"] = int(active)
    if password is not None:
        check_password(password)
        fields["password_hash"] = hash_password(password)
    loses_admin = target["role"] == "admin" and target["active"] and (
        fields.get("role", "admin") != "admin" or fields.get("active", 1) == 0)
    if loses_admin:
        if account_id == acting_id:
            raise AuthError(422, "validation_error",
                            "Нельзя снять права администратора или отключить самого себя")
        others = conn.execute("SELECT COUNT(*) FROM account WHERE role = 'admin' AND active = 1 "
                              "AND id != ?", (account_id,)).fetchone()[0]
        if not others:
            raise AuthError(422, "validation_error", "В системе должен остаться администратор")
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE account SET {sets} WHERE id = ?", (*fields.values(), account_id))
    if "password_hash" in fields or fields.get("active") == 0:
        # Смена пароля и отключение завершают все входы этой учётной записи.
        conn.execute("DELETE FROM auth_session WHERE account_id = ?", (account_id,))
    return account(conn, account_id)


# ---------- вход ----------

def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(conn, email, password):
    """→ (токен, учётная запись, срок действия). Причина отказа не уточняется:
    по ответу нельзя узнать, существует ли почта."""
    email = (email or "").strip().lower()
    count, locked_until = _failures.get(email, (0, 0.0))
    if locked_until > time.monotonic():
        raise AuthError(429, "too_many_attempts",
                        "Слишком много неудачных попыток. Повторите через минуту")
    acc = db.row(conn.execute("SELECT * FROM account WHERE email = ?", (email,)).fetchone())
    # Для несуществующей почты проверяется хэш-пустышка: время ответа то же.
    stored = acc["password_hash"] if acc else _demo_hash("", secrets.token_hex(8))
    if not verify_password(password or "", stored) or acc is None or not acc["active"]:
        count += 1
        lock = time.monotonic() + _LOCK_SECONDS if count >= _MAX_FAILURES else 0.0
        _failures[email] = (0 if lock else count, lock)
        raise AuthError(401, "invalid_credentials", "Неверная почта или пароль")
    _failures.pop(email, None)
    token, expires_at = open_session(conn, acc["id"])
    return token, acc, expires_at


def open_session(conn, account_id):
    """Новый вход учётной записи → (токен, срок действия). Истёкшие входы удаляются."""
    now = datetime.now(config.MSK)
    expires = now + timedelta(hours=float(config.SETTINGS["auth_token_hours"]))
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM auth_session WHERE expires_at <= ?", (now.isoformat(timespec="seconds"),))
    conn.execute("INSERT INTO auth_session (token_hash, account_id, created_at, expires_at) "
                 "VALUES (?, ?, ?, ?)", (_token_hash(token), account_id,
                                         now.isoformat(timespec="seconds"),
                                         expires.isoformat(timespec="seconds")))
    return token, expires.isoformat(timespec="seconds")


def authenticate(conn, token):
    """Учётная запись по токену или None: токена нет, он истёк, запись отключена."""
    if not token:
        return None
    return db.row(conn.execute(
        "SELECT a.* FROM auth_session s JOIN account a ON a.id = s.account_id "
        "WHERE s.token_hash = ? AND s.expires_at > ? AND a.active = 1",
        (_token_hash(token), datetime.now(config.MSK).isoformat(timespec="seconds"))).fetchone())


def logout(conn, token):
    conn.execute("DELETE FROM auth_session WHERE token_hash = ?", (_token_hash(token),))


def allowed(role, permission):
    return role in PERMISSIONS[permission]
