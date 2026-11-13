"""Сброс базы к исходным демо-данным — перед каждым показом.

    python backend/reset_db.py

Бэкенд при этом лучше остановить; если он запущен — перезапустите его после сброса.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import seed  # noqa: E402

if __name__ == "__main__":
    seed.main([])
