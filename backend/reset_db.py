"""Сброс базы к исходным демо-данным — перед каждым показом.

    python backend/reset_db.py            # оборудование, параметры, история — к демо-данным
    python backend/reset_db.py --users    # то же и учётные записи: три демо-записи, все входы завершены

Учётные записи и входы обычный сброс не трогает: телефон остаётся вошедшим.
Бэкенд при этом лучше остановить; если он запущен — перезапустите его после сброса.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import auth, db, seed  # noqa: E402

if __name__ == "__main__":
    seed.main([])
    with db.session() as conn:
        if "--users" in sys.argv[1:]:
            auth.reset(conn)
            print("Учётные записи возвращены к демо-записям, все входы завершены")
        else:
            auth.ensure(conn)
