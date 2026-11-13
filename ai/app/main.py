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
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_GPU_CACHE: dict = {"at": -1e9, "value": None, "busy": False}
_GPU_LOCK = threading.Lock()


def _read_nvidia_smi() -> tuple[int, int] | None:
    import os
    import shutil
    import subprocess

    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        out = subprocess.run(
            [exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, **kwargs,
        ).stdout
        used, total = (int(v) for v in out.strip().splitlines()[0].split(","))
        return used, total
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def _refresh_gpu() -> None:
    try:
        value = _read_nvidia_smi()
    finally:
        with _GPU_LOCK:
            _GPU_CACHE.update(at=time.monotonic(), value=value if "value" in locals() else None, busy=False)


def gpu_memory_mb() -> tuple[int, int] | None:
    """Занятая и полная видеопамять карты по nvidia-smi: (used, total) в МБ.

    torch.cuda.mem_get_info в Windows (драйвер WDDM) не учитывает память других
    процессов — например, Ollama, — поэтому общий расход берём у драйвера.
    nvidia-smi вызывается в фоновом потоке не чаще раза в 5 секунд, а /health сразу
    отдаёт последнее известное значение: бэкенд и стенд ждут /health не дольше 2 секунд.
    """
    with _GPU_LOCK:
        stale = time.monotonic() - _GPU_CACHE["at"] >= 5.0
        if stale and not _GPU_CACHE["busy"]:
            _GPU_CACHE["busy"] = True
            threading.Thread(target=_refresh_gpu, name="nvidia-smi", daemon=True).start()
        return _GPU_CACHE["value"]


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
            self._load_models()
        except Exception as exc:  # нет torch, сломанная сборка CUDA и т. п.: причина — в /health
            log.exception("Модели не загружены")
            for state in self.states.values():
                if not state.ready and not state.error:
                    state.error = f"{type(exc).__name__}: {exc} — выполните python ai/install.py"
        finally:
            self.loading = False

    def _load_models(self) -> None:
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

    def health(self) -> dict:
        if self.settings.stub:
            return {"status": "ok", "ready": True, "stub": True, "models": {}}
        ready = all(s.ready for s in self.states.values())
        if self.loading:
            status = "loading"
        elif ready:
            status = "ok"
        elif any(s.ready for s in self.states.values()):
            status = "degraded"  # часть моделей работает: сервис отвечает, неготовые запросы — 503
        else:
            status = "failed"  # ни одной модели: «готов» сказать нельзя, причина — в models.*.error
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
            import sys

            # torch берём, только если поток загрузки его уже импортировал: импорт идёт секунды,
            # а /health должен отвечать сразу
            torch = sys.modules.get("torch")
            if torch is not None and not self.loading and torch.cuda.is_available():
                smi = gpu_memory_mb()
                if smi is not None:
                    used_mb, total_mb = smi  # вся занятая память карты, включая Ollama
                else:
                    free, total = torch.cuda.mem_get_info()
                    used_mb, total_mb = (total - free) // 2**20, total // 2**20
                info["gpu"] = {
                    "name": torch.cuda.get_device_name(0),
                    "memory_total_mb": total_mb,
                    "memory_used_mb": used_mb,
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
    from starlette.concurrency import run_in_threadpool

    data = await upload.read()
    try:
        # декодирование большого снимка — до сотен мс: не в цикле событий, чтобы не держать /health
        return await run_in_threadpool(decode_image, data)
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
        # пока модели загружаются или не загрузилась ни одна — 503: бэкенд и стенд считают
        # сервис готовым по коду 200
        code = 503 if info["status"] in ("loading", "failed") else 200
        return JSONResponse(status_code=code, content=info)

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
        from starlette.concurrency import run_in_threadpool

        # require("vlm") может спросить Ollama по сети (до 5 с) — не в цикле событий
        await run_in_threadpool(service.require, "vlm")
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
