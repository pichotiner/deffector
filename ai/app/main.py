"""ИИ-сервис: распознавание узлов, оценка видимых дефектов, идентификация по изображению.

Внутренний контракт — plan/README.md, раздел 5.4.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import asynccontextmanager

from .config import apply_offline_env, load_settings

apply_offline_env()  # до импорта библиотек с моделями

from fastapi import FastAPI, File, Form, Request, UploadFile  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from . import stub  # noqa: E402
from .images import ImageError, decode_image  # noqa: E402

log = logging.getLogger("ai")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


class ModelState:
    """Состояние одной модели для /health."""

    def __init__(self, name: str):
        self.name = name
        self.ready = False
        self.error: str | None = None
        self.load_seconds: float | None = None

    def as_dict(self) -> dict:
        return {"name": self.name, "ready": self.ready, "error": self.error, "load_seconds": self.load_seconds}


class Service:
    def __init__(self):
        self.settings = load_settings()
        self.device = "cpu"
        self.detector = None
        self.analyzer = None
        self.identifier = None
        self.states = {
            "detector": ModelState(self.settings.detector_dir),
            "vlm": ModelState(self.settings.vlm_model),
            "identifier": ModelState(self.settings.clip_dir),
        }
        self.loading = False

    def _load_one(self, key: str, loader) -> None:
        state = self.states[key]
        started = time.monotonic()
        try:
            loader()
            state.ready, state.error = True, None
        except Exception as exc:  # одна неготовая модель не должна ронять остальные запросы
            state.ready, state.error = False, str(exc)
            log.exception("Модель %s не загружена", key)
        state.load_seconds = round(time.monotonic() - started, 1)

    def load_models(self) -> None:
        self.loading = True
        try:
            import torch

            from .analyzer import Analyzer
            from .detector import Detector
            from .identifier import Identifier

            device = self.settings.device
            if device == "auto":
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
            elif device == "cuda":
                device = "cuda:0"
            self.device = device

            self.detector = Detector(self.settings, device)
            self._load_one("detector", self.detector.load)
            self.identifier = Identifier(self.settings, device)
            self._load_one("identifier", self.identifier.load)
            self.analyzer = Analyzer(self.settings)

            def load_vlm():
                self.analyzer.check_ready()
                if self.settings.warmup:
                    self.analyzer.warmup()

            self._load_one("vlm", load_vlm)
        finally:
            self.loading = False

    def health(self) -> dict:
        if self.settings.stub:
            return {"status": "ok", "ready": True, "stub": True, "models": {}}
        ready = all(s.ready for s in self.states.values())
        status = "loading" if self.loading else ("ok" if ready else "degraded")
        info = {
            "status": status,
            "ready": ready,
            "stub": False,
            "device": self.device,
            "models": {k: s.as_dict() for k, s in self.states.items()},
            "classes": list(self.settings.classes),
        }
        if self.identifier is not None:
            info["reference_photos"] = self.identifier.reference_counts
        try:
            import torch

            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                info["gpu"] = {
                    "name": torch.cuda.get_device_name(0),
                    "memory_total_mb": total // 2**20,
                    "memory_used_mb": (total - free) // 2**20,  # вся занятая память карты, включая Ollama
                }
        except Exception:
            pass
        return info

    def require(self, key: str) -> None:
        state = self.states[key]
        if state.ready:
            return
        if key == "vlm" and not self.loading and self.analyzer is not None:
            # Ollama могли запустить позже сервиса — проверяем ещё раз, без прогрева
            try:
                self.analyzer.check_ready()
                state.ready, state.error = True, None
                return
            except RuntimeError as exc:
                state.error = str(exc)
        if self.loading:
            raise ApiError(503, "model_loading", "Модели ещё загружаются, повторите запрос позже")
        raise ApiError(503, "model_unavailable", f"Модель не готова: {state.error or 'не загружена'}")


def parse_classes(values: list[str] | None) -> list[str] | None:
    """Поле classes: повторяющиеся поля формы, строка через запятую или JSON-список."""
    if not values:
        return None
    result: list[str] = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        if value.startswith("["):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ApiError(422, "bad_request", "Поле classes: неверный JSON") from exc
            if not isinstance(parsed, list):
                raise ApiError(422, "bad_request", "Поле classes должно быть списком")
            result.extend(str(item).strip() for item in parsed)
        else:
            result.extend(part.strip() for part in value.split(","))
    result = list(dict.fromkeys(item for item in result if item))
    return result or None


async def read_image(upload: UploadFile):
    try:
        return decode_image(await upload.read())
    except ImageError as exc:
        raise ApiError(422, "bad_image", str(exc)) from exc


def create_app() -> FastAPI:
    service = Service()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not service.settings.stub:
            # Модели грузятся в фоне: /health отвечает сразу и показывает ход загрузки.
            service.loading = True
            threading.Thread(target=service.load_models, name="load-models", daemon=True).start()
        else:
            log.warning("Режим заглушки: модели не загружаются, ответы — примеры из контракта")
        yield
        if service.analyzer is not None:
            service.analyzer.close()

    # docs_url=None: встроенная страница документации тянет скрипты из интернета
    app = FastAPI(title="ИИ-сервис deffector", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.service = service

    def error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        fields = ", ".join(str(e["loc"][-1]) for e in exc.errors())
        return error(422, "bad_request", f"Неверный запрос, проверьте поля: {fields}")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else "http_error"
        return error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception):
        log.exception("Необработанная ошибка")
        return error(500, "internal_error", "Внутренняя ошибка ИИ-сервиса")

    @app.get("/health")
    def health():
        info = service.health()
        # пока модели загружаются — 503: бэкенд и стенд считают сервис готовым по коду 200
        return JSONResponse(status_code=503 if info["status"] == "loading" else 200, content=info)

    @app.post("/detect")
    async def detect(image: UploadFile = File(...), classes: list[str] | None = Form(None)):
        wanted = parse_classes(classes)
        picture = await read_image(image)
        if service.settings.stub:
            return stub.detect(wanted)
        service.require("detector")
        from starlette.concurrency import run_in_threadpool

        boxes = await run_in_threadpool(service.detector.detect, picture, wanted)
        return [box.as_dict() for box in boxes]

    @app.post("/analyze")
    async def analyze(
        image: UploadFile = File(...), component_type: str = Form(""), component_name: str = Form("")
    ):
        picture = await read_image(image)
        if service.settings.stub:
            return stub.analyze(component_type, component_name)
        service.require("vlm")
        from starlette.concurrency import run_in_threadpool

        result = await run_in_threadpool(service.analyzer.analyze, picture, component_type, component_name)
        return result.as_dict()

    @app.post("/identify")
    async def identify(image: UploadFile = File(...)):
        picture = await read_image(image)
        if service.settings.stub:
            return stub.identify()
        service.require("identifier")
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(service.identifier.identify, picture)

    return app


app = create_app()
