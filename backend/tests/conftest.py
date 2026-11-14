"""Тесты работают на отдельной временной базе, с датой 13.11.2026 и ИИ в режиме заглушки.

Перед каждым тестом база и учётные записи возвращаются к демо-данным. Общий клиент модуля
(`client`) получает вход инженера: тесты контракта идут от его имени. Входы других ролей —
фикстура `login` (tests/test_auth.py).
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="deffector-test-"))
os.environ["DEFFECTOR_DB_PATH"] = str(_TMP / "test.sqlite3")
os.environ["DEFFECTOR_TODAY"] = "2026-11-13"
os.environ["DEFFECTOR_AI_MODE"] = "stub"

import pytest  # noqa: E402

from app import auth, db, seed  # noqa: E402


def token_for(email):
    """Вход без проверки пароля — чтобы тесты не ждали PBKDF2."""
    with db.session() as conn:
        account = conn.execute("SELECT id FROM account WHERE email = ?", (email,)).fetchone()
        return auth.open_session(conn, account["id"])[0]


def bearer(email):
    return {"Authorization": f"Bearer {token_for(email)}"}


@pytest.fixture(autouse=True)
def fresh_db(request):
    conn = db.connect()
    try:
        seed.seed(conn)
        auth.reset(conn)
        conn.commit()
    finally:
        conn.close()
    client = getattr(request.module, "client", None)
    if client is not None:
        client.headers.update(bearer("engineer@kst.local"))
