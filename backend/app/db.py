"""SQLite: схема и подключение. База — один локальный файл (настройка db_path)."""

import json
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT,
    manufacturer TEXT,
    serial_number TEXT,
    marking TEXT,
    qr_code TEXT,
    location TEXT,
    commissioned_at TEXT,            -- дата ввода в эксплуатацию
    characteristics TEXT NOT NULL DEFAULT '[]',   -- JSON [{name, value, unit}]
    life_years REAL,                 -- нормативный срок службы
    life_hours REAL,
    life_cycles REAL,
    maintenance_interval_days INTEGER,
    operating_hours REAL,            -- наработка с даты ввода
    cycles REAL,
    last_maintenance_at TEXT
);

CREATE TABLE IF NOT EXISTS component (
    id TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL REFERENCES equipment(id),
    parent_id TEXT REFERENCES component(id),
    kind TEXT NOT NULL CHECK (kind IN ('node', 'part')),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    sort_order INTEGER,              -- порядок слева направо на общем виде
    characteristics TEXT NOT NULL DEFAULT '[]',
    installed_at TEXT,
    last_replaced_at TEXT,
    last_maintenance_at TEXT,
    life_years REAL,
    life_hours REAL,
    life_cycles REAL,
    maintenance_interval_days INTEGER,
    operating_hours REAL,            -- наработка от последней замены (или установки)
    cycles REAL,
    maintenance_action TEXT,         -- что делать при наступлении срока обслуживания
    visual_reset_at TEXT             -- визуальные результаты до этого момента не учитываются
);

CREATE TABLE IF NOT EXISTS parameter (
    id TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL REFERENCES equipment(id),
    component_id TEXT REFERENCES component(id),
    name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    setpoint_min REAL,
    setpoint_max REAL,
    measured_at TEXT,
    warn_text TEXT,   -- диагноз при выходе за уставку предупреждения (материалы заказчика)
    alarm_max REAL,   -- уровень тревоги
    alarm_text TEXT   -- диагноз при тревоге
);

CREATE TABLE IF NOT EXISTS inspection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL REFERENCES equipment(id),
    component_id TEXT REFERENCES component(id),
    type TEXT NOT NULL,
    comment TEXT,
    performed_by TEXT,
    performed_at TEXT NOT NULL,
    visual TEXT,                     -- JSON приложенного результата визуального анализа
    recommendation TEXT
);

CREATE TABLE IF NOT EXISTS visual_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL REFERENCES equipment(id),
    component_id TEXT NOT NULL REFERENCES component(id),
    category TEXT NOT NULL,
    signs TEXT NOT NULL DEFAULT '[]',
    explanation TEXT,
    recommendation TEXT,
    detection_confidence REAL,
    assessment_confidence REAL,
    image_quality TEXT,
    analyzed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_component_eq ON component(equipment_id);
CREATE INDEX IF NOT EXISTS ix_parameter_eq ON parameter(equipment_id);
CREATE INDEX IF NOT EXISTS ix_inspection_eq ON inspection(equipment_id, performed_at);
CREATE INDEX IF NOT EXISTS ix_visual_comp ON visual_result(component_id, analyzed_at);
"""

JSON_COLUMNS = {"characteristics", "signs", "visual"}


def connect(path=None) -> sqlite3.Connection:
    path = path or config.db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_schema(conn):
    conn.executescript(SCHEMA)


def row(r):
    """sqlite3.Row → dict с разобранными JSON-полями."""
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLUMNS & d.keys():
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


def rows(rs):
    return [row(r) for r in rs]
