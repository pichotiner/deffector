"""Чтение и запись в базу. Только SQL, без бизнес-правил."""

import json

from .db import row, rows


def equipment_all(conn):
    return rows(conn.execute("SELECT * FROM equipment ORDER BY id"))


def equipment(conn, eq_id):
    return row(conn.execute("SELECT * FROM equipment WHERE id = ?", (eq_id,)).fetchone())


def components(conn, eq_id):
    return rows(conn.execute(
        "SELECT * FROM component WHERE equipment_id = ? "
        "ORDER BY parent_id IS NOT NULL, COALESCE(sort_order, 999), id", (eq_id,)))


def component(conn, eq_id, cid):
    return row(conn.execute(
        "SELECT * FROM component WHERE equipment_id = ? AND id = ?", (eq_id, cid)).fetchone())


def parameters(conn, eq_id):
    return rows(conn.execute("SELECT * FROM parameter WHERE equipment_id = ? ORDER BY id", (eq_id,)))


def history(conn, eq_id, component_id=None, limit=None):
    sql = "SELECT * FROM inspection WHERE equipment_id = ?"
    args = [eq_id]
    if component_id is not None:
        sql += " AND component_id = ?"
        args.append(component_id)
    sql += " ORDER BY performed_at DESC, id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return rows(conn.execute(sql, args))


def latest_visuals(conn, eq_id):
    """Последний визуальный результат по каждому компоненту — с учётом сброса после замены."""
    out = {}
    for r in rows(conn.execute(
            "SELECT v.* FROM visual_result v JOIN component c ON c.id = v.component_id "
            "WHERE v.equipment_id = ? AND (c.visual_reset_at IS NULL OR v.analyzed_at > c.visual_reset_at) "
            "ORDER BY v.analyzed_at, v.id", (eq_id,))):
        out[r["component_id"]] = r
    return out


def last_inspection_dates(conn, eq_id):
    return {r["component_id"]: r["last"] for r in conn.execute(
        "SELECT component_id, MAX(performed_at) AS last FROM inspection "
        "WHERE equipment_id = ? AND component_id IS NOT NULL GROUP BY component_id", (eq_id,))}


def add_visual(conn, eq_id, cid, v):
    conn.execute(
        "INSERT INTO visual_result (equipment_id, component_id, category, signs, explanation, "
        "recommendation, detection_confidence, assessment_confidence, image_quality, analyzed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (eq_id, cid, v["category"], json.dumps(v["signs"], ensure_ascii=False), v["explanation"],
         v["recommendation"], v["detection_confidence"], v["assessment_confidence"],
         v.get("image_quality"), v["analyzed_at"]))


def add_inspection(conn, e):
    cur = conn.execute(
        "INSERT INTO inspection (equipment_id, component_id, type, comment, performed_by, "
        "performed_at, visual, recommendation) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (e["equipment_id"], e["component_id"], e["type"], e["comment"], e["performed_by"],
         e["performed_at"],
         json.dumps(e["visual"], ensure_ascii=False) if e["visual"] is not None else None,
         e["recommendation"]))
    return cur.lastrowid


def inspection(conn, iid):
    return row(conn.execute("SELECT * FROM inspection WHERE id = ?", (iid,)).fetchone())


def update_component(conn, cid, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE component SET {sets} WHERE id = ?", (*fields.values(), cid))


def update_equipment(conn, eq_id, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE equipment SET {sets} WHERE id = ?", (*fields.values(), eq_id))
