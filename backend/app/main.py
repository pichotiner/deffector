"""Заглушка бэкенда: все 11 запросов контракта (README плана, раздел 5).

Ответы — по контракту, данные — из stub_data.py. Изменения (осмотры, анализ)
хранятся в памяти и пропадают при перезапуске. Ресурс не пересчитывается — это этап 2.
"""

import copy
import difflib
import math
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import stub_data
from .enums import (
    COMPONENT_TYPES, DETECTABLE_TYPES, DISCLAIMER, INSPECTION_TYPES,
    INSPECTION_TYPES_NEED_COMMENT, NO_ISSUES_NOTE,
)

MSK = timezone(timedelta(hours=3))
IDENTIFY_THRESHOLD = 0.5

app = FastAPI(title="Deffector backend (заглушка)", version="0.1.0")


# ---------- состояние ----------

STATE = {}


def reset_state():
    STATE.clear()
    STATE.update({
        "equipment": copy.deepcopy(stub_data.EQUIPMENT),
        "components": copy.deepcopy(stub_data.COMPONENTS),
        "parameters": copy.deepcopy(stub_data.PARAMETERS),
        "history": copy.deepcopy(stub_data.HISTORY),
    })


reset_state()


# ---------- ошибки в формате контракта ----------

class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def _error(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return _error(exc.status, exc.code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    code = "not_found" if exc.status_code == 404 else "http_error"
    return _error(exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
    return _error(422, "validation_error", f"Неверный запрос: {fields}")


# ---------- вспомогательное ----------

def _now():
    return datetime.now(MSK).isoformat(timespec="seconds")


def _today():
    return datetime.now(MSK).date()


def _equipment(eq_id):
    eq = STATE["equipment"].get(eq_id)
    if eq is None:
        raise ApiError(404, "not_found", "Оборудование не найдено")
    return eq


def _raw_component(eq_id, cid):
    _equipment(eq_id)
    for c in STATE["components"][eq_id]:
        if c["id"] == cid:
            return c
    raise ApiError(404, "not_found", "Компонент не найден в карточке оборудования")


def _component_params(eq_id, cid):
    return [p for p in STATE["parameters"][eq_id] if p["component_id"] == cid]


def _attention(eq_id, c):
    """Правило attention.level — README плана, раздел 5.1."""
    params = _component_params(eq_id, c["id"])
    res, vis = c["resource"], c["visual"]
    maint = res.get("maintenance") or {}
    deviations = [p for p in params if p["status"] == "deviation"]

    reasons = []
    if maint.get("status") == "due":
        reasons.append("Наступил срок обслуживания")
    if res["status"] == "due" and maint.get("status") != "due":
        reasons.append("Наступил срок замены")
    for p in deviations:
        reasons.append(f"{p['name']}: {p['message'][0].lower()}{p['message'][1:]}")
    if vis["category"] == "possible_defect":
        reasons.append("Обнаружены признаки возможного дефекта")
    if res["status"] == "approaching":
        reasons.append("Приближается срок обслуживания или замены")
    if vis["category"] == "check_recommended":
        reasons.append("Рекомендуется проверка по результатам визуального анализа")

    if vis["category"] == "possible_defect" or res["status"] == "due" or deviations:
        level = "defect"
    elif vis["category"] == "check_recommended" or res["status"] == "approaching":
        level = "check"
    elif (vis["category"] == "no_visible_issues" and res["status"] == "ok"
          and all(p["status"] == "normal" for p in params)):
        level = "none"
    else:
        level = "unknown"
        if vis["category"] == "not_analyzed":
            reasons.append("Визуальный анализ не проводился")
        if res["status"] == "insufficient_data":
            reasons.append("Недостаточно данных для оценки ресурса")

    action = c.get("_recommended_action") or vis.get("recommendation")
    if action is None:
        action = {
            "defect": "Провести осмотр узла",
            "check": "Проверить узел при ближайшем осмотре",
            "none": "Продолжить плановые осмотры",
            "unknown": "Провести визуальный анализ узла",
        }[level]
    return {"level": level, "reasons": reasons, "recommended_action": action}


def _component(eq_id, c):
    out = {k: v for k, v in c.items() if not k.startswith("_")}
    out["attention"] = _attention(eq_id, c)
    out["parameters"] = [p["id"] for p in _component_params(eq_id, c["id"])]
    out["previous_results"] = [h for h in STATE["history"][eq_id] if h["component_id"] == c["id"]][:5]
    return out


def _card(eq_id):
    eq = _equipment(eq_id)
    return {
        **eq,
        "parameters": STATE["parameters"][eq_id],
        "components": [_component(eq_id, c) for c in STATE["components"][eq_id]],
        "history": STATE["history"][eq_id],
    }


def _normalize(s):
    """Нормализация номера: без регистра, пробелов, дефисов; типичные ошибки OCR."""
    s = "".join(ch for ch in s.upper() if ch.isalnum())
    return s.translate(str.maketrans("OISB", "0158"))


def _short(eq):
    return {k: eq[k] for k in ("id", "name", "model", "serial_number", "marking", "location")}


# ---------- 11. health ----------

@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "stub", "time": _now()}


# ---------- 1. список для ручного выбора ----------

@app.get("/api/equipment")
def equipment_list(q: str = ""):
    ql = q.strip().lower()
    items = [
        _short(eq) for eq in STATE["equipment"].values()
        if not ql or any(ql in str(eq[f]).lower()
                         for f in ("id", "name", "model", "serial_number", "marking"))
    ]
    return {"items": items}


# ---------- 2. lookup ----------

@app.get("/api/equipment/lookup")
def equipment_lookup(qr: str | None = None, serial: str | None = None, marking: str | None = None):
    if qr is None and serial is None and marking is None:
        raise ApiError(400, "bad_request", "Укажите qr, serial или marking")

    for eq in STATE["equipment"].values():
        if qr is not None and qr.strip() == eq["qr_code"]:
            return {"found": True, "equipment_id": eq["id"], "matched_by": "qr", "match_confidence": 1.0}
        for by, value, field in (("serial", serial, "serial_number"), ("marking", marking, "marking")):
            if value is not None and _normalize(value) == _normalize(eq[field]):
                exact = value.strip().upper() == eq[field].upper()
                return {"found": True, "equipment_id": eq["id"], "matched_by": by,
                        "match_confidence": 1.0 if exact else 0.93}

    query = _normalize(qr or serial or marking)
    suggestions = []
    for eq in STATE["equipment"].values():
        score = max(difflib.SequenceMatcher(None, query, _normalize(eq[f])).ratio()
                    for f in ("qr_code", "serial_number", "marking"))
        if score >= 0.4:
            suggestions.append({"equipment_id": eq["id"], "name": eq["name"], "score": round(score, 2)})
    suggestions.sort(key=lambda s: -s["score"])
    return {"found": False, "suggestions": suggestions}


# ---------- 3. идентификация по изображению ----------

@app.post("/api/identify/image")
async def identify_image(image: UploadFile = File(...)):
    await image.read()
    candidates = [
        {"equipment_id": c["equipment_id"], "name": STATE["equipment"][c["equipment_id"]]["name"],
         "confidence": c["confidence"]}
        for c in stub_data.IDENTIFY["candidates"]
    ]
    recognized = bool(candidates) and candidates[0]["confidence"] >= IDENTIFY_THRESHOLD
    return {"recognized": recognized, "candidates": candidates}


# ---------- 4. цифровая карточка ----------

@app.get("/api/equipment/{eq_id}")
def equipment_card(eq_id: str):
    return _card(eq_id)


# ---------- 5. узлы, требующие проверки ----------

@app.get("/api/equipment/{eq_id}/attention")
def equipment_attention(eq_id: str):
    _equipment(eq_id)
    order = {"defect": 0, "check": 1}
    items = []
    for c in STATE["components"][eq_id]:
        a = _attention(eq_id, c)
        if a["level"] in order:
            items.append({
                "component_id": c["id"], "name": c["name"], "level": a["level"],
                "reasons": a["reasons"],
                "hint": f"Наведите камеру на {c['name'][0].lower()}{c['name'][1:]}",
            })
    items.sort(key=lambda i: order[i["level"]])
    return {"items": items}


# ---------- 6. detect ----------

def _match(eq_id, raw):
    """Сопоставление рамок ИИ с узлами карточки (правило из плана Андрея, этап 2)."""
    comps = STATE["components"][eq_id]
    by_type = {}
    for c in comps:
        by_type.setdefault(c["type"], []).append(c)

    detections, seen = [], set()
    by_class = {}
    for d in raw:
        by_class.setdefault(d["cv_class"], []).append(d)

    for cv_class, dets in by_class.items():
        cands = sorted(by_type.get(cv_class, []), key=lambda c: (c["order"] is None, c["order"]))
        dets = sorted(dets, key=lambda d: d["bbox"][0])  # слева направо
        if not cands:
            pairs = [(d, None, "not_in_card") for d in dets]
        elif len(cands) == 1 and len(dets) == 1:
            pairs = [(dets[0], cands[0], "matched")]
        elif len(cands) == len(dets):
            pairs = [(d, c, "matched") for d, c in zip(dets, cands)]
        else:
            pairs = [(d, None, "ambiguous") for d in dets]

        for d, c, match in pairs:
            item = {"bbox": d["bbox"], "cv_class": cv_class,
                    "detection_confidence": d["confidence"], "match": match}
            if match == "matched":
                seen.add(c["id"])
                a = _attention(eq_id, c)
                item.update({
                    "component_id": c["id"], "label": c["type_name"],
                    "attention_level": a["level"], "resource_status": c["resource"]["status"],
                    "visual_category": c["visual"]["category"],
                    "reason": a["reasons"][0] if a["reasons"] else None,
                    "recommended_action": a["recommended_action"],
                })
            elif match == "ambiguous":
                seen.update(x["id"] for x in cands)
                item.update({
                    "component_id": None, "candidates": [x["id"] for x in cands],
                    "label": COMPONENT_TYPES[cv_class]["name"], "attention_level": "unknown",
                    "resource_status": None, "visual_category": None,
                    "reason": "Подходит несколько узлов карточки — выберите нужный",
                    "recommended_action": None,
                })
            else:
                name = COMPONENT_TYPES.get(cv_class, {}).get("name", cv_class)
                item.update({
                    "component_id": None, "label": name, "attention_level": "unknown",
                    "resource_status": None, "visual_category": None,
                    "reason": "Узел не найден в карточке оборудования",
                    "recommended_action": None,
                })
            detections.append(item)

    not_in_frame = [c["id"] for c in comps
                    if c["type"] in DETECTABLE_TYPES and c["id"] not in seen]
    return {"detections": detections, "not_in_frame": not_in_frame}


def _jitter(bbox):
    """Небольшое покачивание рамок, чтобы в приложении было видно сглаживание."""
    t = time.time()
    dx, dy = 0.01 * math.sin(t * 1.3), 0.01 * math.cos(t * 1.1)
    x, y, w, h = bbox
    return [round(min(max(x + dx, 0), 1 - w), 3), round(min(max(y + dy, 0), 1 - h), 3), w, h]


@app.post("/api/equipment/{eq_id}/detect")
async def equipment_detect(eq_id: str, image: UploadFile = File(...)):
    _equipment(eq_id)
    await image.read()
    raw = [{**d, "bbox": _jitter(d["bbox"])} for d in stub_data.DETECT.get(eq_id, [])]
    return _match(eq_id, raw)


# ---------- 7. analyze ----------

@app.post("/api/equipment/{eq_id}/components/{cid}/analyze")
async def component_analyze(eq_id: str, cid: str, image: UploadFile = File(...)):
    c = _raw_component(eq_id, cid)
    await image.read()
    a = stub_data.ANALYZE
    visual = {
        "category": a["category"], "signs": a["signs"], "explanation": a["explanation"],
        "recommendation": a["recommendation"],
        "detection_confidence": c["visual"].get("detection_confidence"),
        "assessment_confidence": a["assessment_confidence"],
        "analyzed_at": _now(), "disclaimer": DISCLAIMER,
    }
    if visual["category"] == "no_visible_issues":
        visual["note"] = NO_ISSUES_NOTE
    c["visual"] = visual
    return _component(eq_id, c)


# ---------- 8. карточка узла ----------

@app.get("/api/equipment/{eq_id}/components/{cid}")
def component_card(eq_id: str, cid: str):
    return _component(eq_id, _raw_component(eq_id, cid))


# ---------- 9. запись осмотра ----------

class InspectionIn(BaseModel):
    component_id: str | None = None
    type: str
    comment: str | None = None
    performed_by: str | None = None
    attach_last_visual: bool = False


@app.post("/api/equipment/{eq_id}/inspections", status_code=201)
def create_inspection(eq_id: str, body: InspectionIn):
    _equipment(eq_id)
    if body.type not in INSPECTION_TYPES:
        raise ApiError(422, "validation_error",
                       "Тип записи: " + ", ".join(INSPECTION_TYPES))
    comment = (body.comment or "").strip()
    if body.type in INSPECTION_TYPES_NEED_COMMENT and not comment:
        raise ApiError(422, "comment_required",
                       f"Для записи «{INSPECTION_TYPES[body.type]}» нужен комментарий")

    c = _raw_component(eq_id, body.component_id) if body.component_id else None
    if c is None and body.type in ("maintenance", "replacement"):
        raise ApiError(422, "validation_error", "Для обслуживания и замены укажите компонент")

    visual = None
    if c and body.attach_last_visual and c["visual"]["category"] != "not_analyzed":
        visual = copy.deepcopy(c["visual"])

    today = _today()
    if c and body.type == "maintenance":
        c["last_maintenance_at"] = today.isoformat()
        interval = c["normative"].get("maintenance_interval_days")
        if interval:
            nxt = today + timedelta(days=interval)
            c["resource"]["maintenance"] = {"next_due_date": nxt.isoformat(), "status": "ok",
                                            "days_left": interval}
    if c and body.type == "replacement":
        # В заглушке — упрощённо; настоящий пересчёт ресурса — этап 2.
        c["last_replaced_at"] = today.isoformat()
        c["usage"] = {k: (0 if v is not None else None) for k, v in c["usage"].items()}
        c["visual"] = stub_data._visual("not_analyzed")
        c.pop("_recommended_action", None)
        c["resource"].update({"status": "ok", "used_percent": 0,
                              "basis": "Оценка по календарному сроку от даты последней замены",
                              "message": "Ресурс в норме"})

    all_ids = [h["id"] for hs in STATE["history"].values() for h in hs]
    entry = {
        "id": max(all_ids, default=0) + 1,
        "component_id": body.component_id,
        "type": body.type,
        "comment": comment or None,
        "performed_by": body.performed_by,
        "performed_at": _now(),
        "visual": visual,
        "recommendation": visual["recommendation"] if visual else None,
    }
    STATE["history"][eq_id].insert(0, entry)
    return {"inspection": entry, "component": _component(eq_id, c) if c else None}


# ---------- 10. история ----------

@app.get("/api/equipment/{eq_id}/history")
def equipment_history(eq_id: str):
    _equipment(eq_id)
    return {"items": STATE["history"][eq_id]}
