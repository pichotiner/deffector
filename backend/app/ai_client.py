"""Клиент ИИ-сервиса (внутренний контракт — README плана, раздел 5.4).

ai_mode = "stub": ответы из ai_stub.py, видеокарта и ИИ-сервис не нужны.
ai_mode = "real": запросы к ИИ-сервису по ai_url. Только локальная сеть.
"""

import json
import math
import time
import urllib.error
import urllib.request
import uuid

from . import ai_stub, config
from .enums import VISUAL_CATEGORIES_FROM_AI


class AiUnavailable(Exception):
    pass


def mode():
    return config.SETTINGS["ai_mode"]


def _multipart(fields, image):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                     f"{value}\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
                 f"filename=\"image.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode())
    parts.append(image)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# Только локальная сеть: системные прокси (в Windows — из реестра) не используем.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(path, fields=None, image=None, timeout=None):
    url = config.SETTINGS["ai_url"].rstrip("/") + path
    timeout = timeout or config.SETTINGS["ai_timeout_seconds"]
    if image is None:
        req = urllib.request.Request(url)
    else:
        body, ctype = _multipart(fields or [], image)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise AiUnavailable(str(e)) from e


def health():
    if mode() == "stub":
        return {"mode": "stub", "status": "ok"}
    try:
        _request("/health", timeout=2)
        return {"mode": "real", "status": "ok"}
    except AiUnavailable:
        return {"mode": "real", "status": "unavailable"}


def _jitter(bbox):
    """Заглушка: небольшое покачивание рамок, чтобы в приложении было видно сглаживание."""
    t = time.time()
    dx, dy = 0.01 * math.sin(t * 1.3), 0.01 * math.cos(t * 1.1)
    x, y, w, h = bbox
    return [round(min(max(x + dx, 0), 1 - w), 3), round(min(max(y + dy, 0), 1 - h), 3), w, h]


def detect(image, equipment_id, classes):
    """→ [{bbox, cv_class, confidence}]"""
    if mode() == "stub":
        return [{**d, "bbox": _jitter(d["bbox"])} for d in ai_stub.DETECT.get(equipment_id, [])]
    data = _request("/detect", [("classes", ",".join(classes))], image,
                    timeout=config.SETTINGS["ai_detect_timeout_seconds"])
    items = data.get("detections", data) if isinstance(data, dict) else data
    out = []
    for d in items:
        try:
            x, y, w, h = (min(max(float(v), 0.0), 1.0) for v in d["bbox"])
            out.append({"bbox": [x, y, min(w, 1 - x), min(h, 1 - y)], "cv_class": str(d["cv_class"]),
                        "confidence": float(d["confidence"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def analyze(image, component_type, component_name):
    """→ {category, signs, explanation, recommendation, assessment_confidence, image_quality}"""
    if mode() == "stub":
        return dict(ai_stub.ANALYZE)
    data = _request("/analyze", [("component_type", component_type),
                                 ("component_name", component_name)], image)
    category = data.get("category")
    if category not in VISUAL_CATEGORIES_FROM_AI:
        # Ответ не по контракту — осторожный вариант, «нет проблем» не выдаём никогда.
        return {"category": "check_recommended", "signs": [],
                "explanation": "Автоматический анализ не выполнен",
                "recommendation": "Осмотреть узел вручную",
                "assessment_confidence": None, "image_quality": "unknown"}
    return {
        "category": category,
        "signs": [str(s) for s in data.get("signs") or []],
        "explanation": data.get("explanation"),
        "recommendation": data.get("recommendation"),
        "assessment_confidence": data.get("assessment_confidence"),
        "image_quality": data.get("image_quality"),
    }


def identify(image):
    """→ {recognized, candidates: [{equipment_id, confidence}]}"""
    if mode() == "stub":
        return json.loads(json.dumps(ai_stub.IDENTIFY))
    data = _request("/identify", [], image)
    return {"recognized": bool(data.get("recognized")),
            "candidates": [{"equipment_id": c["equipment_id"], "confidence": float(c["confidence"])}
                           for c in data.get("candidates", [])]}
