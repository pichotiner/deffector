"""Бэкенд Deffector: 11 запросов контракта (README плана, раздел 5).

Данные — SQLite (настройка db_path), ИИ — через ai_client (заглушка или настоящий сервис).
"""

from datetime import timedelta

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import ai_client, cards, config, db, lookup, matching, repo, seed
from . import schemas as s
from .enums import INSPECTION_TYPES, INSPECTION_TYPES_NEED_COMMENT

# Первый запуск: базы нет — создаём и наполняем демо-данными.
seed.main(["--if-missing"])

app = FastAPI(
    title="Deffector backend", version="1.0.0",
    description="Контракт API телефон ↔ бэкенд. Ошибки: {\"error\": {\"code\", \"message\"}}.",
    responses={404: {"model": s.Error}, 422: {"model": s.Error}, 503: {"model": s.Error}},
)


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


@app.exception_handler(ai_client.AiUnavailable)
async def _ai_error(_: Request, exc: ai_client.AiUnavailable):
    return _error(503, "ai_unavailable",
                  "ИИ-сервис не отвечает или вернул ошибку. Проверьте, что он запущен, и повторите")


@app.exception_handler(ai_client.AiBadImage)
async def _ai_bad_image(_: Request, exc: ai_client.AiBadImage):
    return _error(422, "validation_error", "Снимок не читается. Сделайте кадр ещё раз")


# ---------- вспомогательное ----------

def _card(conn, eq_id) -> cards.Card:
    card = cards.Card(conn, eq_id)
    if not card.exists:
        raise ApiError(404, "not_found", "Оборудование не найдено")
    return card


def _raw_component(card, cid):
    c = card.raw(cid)
    if c is None:
        raise ApiError(404, "not_found", "Компонент не найден в карточке оборудования")
    return c


async def _image_bytes(image: UploadFile):
    data = await image.read()
    if not data:
        raise ApiError(422, "validation_error", "Пустое изображение")
    return data


async def _ai(call, *args):
    """Вызов ИИ-сервиса — в отдельном потоке: анализ узла идёт секунды, а рамки
    и остальные запросы в это время должны отвечать."""
    return await run_in_threadpool(call, *args)


# ---------- 11. health ----------

@app.get("/api/health", response_model=s.Health)
def health():
    return {"status": "ok", "mode": "real", "ai": ai_client.health(), "time": config.now_iso()}


# ---------- 1. список для ручного выбора ----------

@app.get("/api/equipment", response_model=s.EquipmentList)
def equipment_list(q: str = ""):
    with db.session() as conn:
        return {"items": lookup.search(repo.equipment_all(conn), q)}


# ---------- 2. lookup ----------

@app.get("/api/equipment/lookup", response_model=s.LookupResult, response_model_exclude_none=True)
def equipment_lookup(qr: str | None = None, serial: str | None = None, marking: str | None = None):
    if qr is None and serial is None and marking is None:
        raise ApiError(400, "bad_request", "Укажите qr, serial или marking")
    with db.session() as conn:
        return lookup.find(repo.equipment_all(conn), qr=qr, serial=serial, marking=marking)


# ---------- 3. идентификация по изображению ----------

@app.post("/api/identify/image", response_model=s.IdentifyResult)
async def identify_image(image: UploadFile = File(...)):
    data = await _image_bytes(image)
    result = await _ai(ai_client.identify, data)
    with db.session() as conn:
        names = {e["id"]: e["name"] for e in repo.equipment_all(conn)}
    candidates = sorted(
        ({"equipment_id": c["equipment_id"], "name": names[c["equipment_id"]],
          "confidence": round(c["confidence"], 3)}
         for c in result["candidates"] if c["equipment_id"] in names),
        key=lambda c: -c["confidence"])
    threshold = config.SETTINGS["identify_threshold"]
    recognized = bool(candidates) and candidates[0]["confidence"] >= threshold
    return {"recognized": recognized, "candidates": candidates}


# ---------- 4. цифровая карточка ----------

@app.get("/api/equipment/{eq_id}", response_model=s.EquipmentCard)
def equipment_card(eq_id: str):
    with db.session() as conn:
        return _card(conn, eq_id).full()


# ---------- 5. узлы, требующие проверки ----------

@app.get("/api/equipment/{eq_id}/attention", response_model=s.AttentionList)
def equipment_attention(eq_id: str):
    with db.session() as conn:
        return {"items": _card(conn, eq_id).attention_items()}


# ---------- 6. detect ----------

@app.post("/api/equipment/{eq_id}/detect", response_model=s.DetectResult)
async def equipment_detect(eq_id: str, image: UploadFile = File(...)):
    data = await _image_bytes(image)
    with db.session() as conn:
        card = _card(conn, eq_id)
    raw = await _ai(ai_client.detect, data, eq_id, matching.classes_for(card))
    return matching.match(card, raw)


# ---------- 7. analyze ----------

@app.post("/api/equipment/{eq_id}/components/{cid}/analyze", response_model=s.Component)
async def component_analyze(eq_id: str, cid: str, image: UploadFile = File(...),
                            detection_confidence: float | None = Form(None)):
    data = await _image_bytes(image)
    with db.session() as conn:
        card = _card(conn, eq_id)
        c = _raw_component(card, cid)
    result = await _ai(ai_client.analyze, data, c["type"], c["name"])  # вне транзакции: идёт секунды
    with db.session() as conn:
        repo.add_visual(conn, eq_id, cid, {
            **result, "detection_confidence": detection_confidence, "analyzed_at": config.now_iso(),
        })
    with db.session() as conn:
        card = _card(conn, eq_id)
        return card.component(card.raw(cid))


# ---------- 8. карточка узла ----------

@app.get("/api/equipment/{eq_id}/components/{cid}", response_model=s.Component)
def component_card(eq_id: str, cid: str):
    with db.session() as conn:
        card = _card(conn, eq_id)
        return card.component(_raw_component(card, cid))


# ---------- 9. запись осмотра ----------

@app.post("/api/equipment/{eq_id}/inspections", response_model=s.InspectionResult, status_code=201)
def create_inspection(eq_id: str, body: s.InspectionIn):
    comment = (body.comment or "").strip() or None
    if body.type in INSPECTION_TYPES_NEED_COMMENT and not comment:
        raise ApiError(422, "comment_required",
                       f"Для записи «{INSPECTION_TYPES[body.type]}» нужен комментарий")
    with db.session() as conn:
        card = _card(conn, eq_id)
        c = _raw_component(card, body.component_id) if body.component_id else None
        if c is None and body.type == "replacement":
            raise ApiError(422, "validation_error", "Для замены укажите компонент")

        visual = None
        if c is not None and body.attach_last_visual:
            _, vis, _ = card.evaluated(c)
            if vis["category"] != "not_analyzed":
                visual = vis

        today, now = config.today(), config.now_iso()
        recommendation = visual["recommendation"] if visual else None

        if body.type == "maintenance":
            target = c or card.eq
            interval = target.get("maintenance_interval_days")
            if interval:
                recommendation = ("Следующее обслуживание — "
                                  f"{(today + timedelta(days=interval)).strftime('%d.%m.%Y')}")
            if c is not None:
                repo.update_component(conn, c["id"], last_maintenance_at=today.isoformat())
            else:
                repo.update_equipment(conn, eq_id, last_maintenance_at=today.isoformat())
        elif body.type == "replacement":
            # Новая точка отсчёта: наработка и циклы обнуляются, прежний визуальный результат
            # больше не относится к узлу.
            repo.update_component(
                conn, c["id"], last_replaced_at=today.isoformat(),
                operating_hours=0 if (c["life_hours"] or c["operating_hours"] is not None) else None,
                cycles=0 if (c["life_cycles"] or c["cycles"] is not None) else None,
                visual_reset_at=now)

        iid = repo.add_inspection(conn, {
            "equipment_id": eq_id, "component_id": body.component_id, "type": body.type,
            "comment": comment, "performed_by": body.performed_by, "performed_at": now,
            "visual": visual, "recommendation": recommendation,
        })
    with db.session() as conn:
        card = _card(conn, eq_id)
        entry = cards.history_item(repo.inspection(conn, iid))
        comp = card.component(card.raw(body.component_id)) if body.component_id else None
        return {"inspection": entry, "component": comp}


# ---------- 10. история ----------

@app.get("/api/equipment/{eq_id}/history", response_model=s.History)
def equipment_history(eq_id: str):
    with db.session() as conn:
        _card(conn, eq_id)
        return {"items": [cards.history_item(h) for h in repo.history(conn, eq_id)]}
