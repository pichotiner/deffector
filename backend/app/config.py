"""Настройки бэкенда — backend/settings.json.

ai_mode: "stub" — ответы ИИ берутся из заглушки, "real" — запросы к ИИ-сервису по ai_url.
today: null — текущая дата по Москве; "2026-11-13" — зафиксировать дату (для отладки).
telemetry_at: какое показание из баз вибрации и температуры заказчика считать текущим
(app/telemetry.py); действует после python backend/reset_db.py.
auth_required: true — все запросы, кроме /api/health и входа, требуют входа пользователя;
false — запросы без токена принимаются (запасной режим стенда для сборки приложения без входа).
auth_token_hours: сколько часов действует вход.
Любой ключ можно переопределить переменной окружения DEFFECTOR_<КЛЮЧ>.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
MSK = timezone(timedelta(hours=3))

_DEFAULTS = {
    "db_path": "data/deffector.sqlite3",
    "ai_mode": "stub",
    "ai_url": "http://127.0.0.1:8001",
    "ai_timeout_seconds": 20,
    "ai_detect_timeout_seconds": 3,
    "resource_approaching_percent": 80,
    "maintenance_warning_days": 30,
    "identify_threshold": 0.5,
    "not_inspected_days": 180,
    "today": None,
    "telemetry_at": "2026-11-13 09:00",
    "auth_required": True,
    "auth_token_hours": 24,
}


def _load():
    s = dict(_DEFAULTS)
    path = BACKEND / "settings.json"
    if path.exists():
        s.update(json.loads(path.read_text(encoding="utf-8")))
    for key, default in _DEFAULTS.items():
        env = os.environ.get(f"DEFFECTOR_{key.upper()}")
        if env is not None:
            if isinstance(default, bool):
                s[key] = env.strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(default, (int, float)):
                s[key] = type(default)(env)
            else:
                s[key] = env
    return s


SETTINGS = _load()


def db_path() -> Path:
    p = Path(SETTINGS["db_path"])
    return p if p.is_absolute() else BACKEND / p


def today() -> date:
    if SETTINGS["today"]:
        return date.fromisoformat(SETTINGS["today"])
    return datetime.now(MSK).date()


def now_iso(timespec="seconds") -> str:
    return datetime.now(MSK).isoformat(timespec=timespec)
