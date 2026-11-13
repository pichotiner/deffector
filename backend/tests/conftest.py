"""Тесты работают на отдельной временной базе, с датой 13.11.2026 и ИИ в режиме заглушки."""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="deffector-test-"))
os.environ["DEFFECTOR_DB_PATH"] = str(_TMP / "test.sqlite3")
os.environ["DEFFECTOR_TODAY"] = "2026-11-13"
os.environ["DEFFECTOR_AI_MODE"] = "stub"

import pytest  # noqa: E402

from app import db, seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    conn = db.connect()
    try:
        seed.seed(conn)
    finally:
        conn.close()
