"""Распознавание узлов: детектор с открытым словарём (YOLOE) и обработка рамок."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .config import ClassSpec, Settings

log = logging.getLogger("ai.detector")


@dataclass(frozen=True)
class Box:
    """Рамка в долях кадра: левый верхний угол, ширина, высота."""

    x: float
    y: float
    w: float
    h: float
    cv_class: str
    confidence: float

    @property
    def area(self) -> float:
        return self.w * self.h

    def as_dict(self) -> dict:
        return {
            "bbox": [round(self.x, 4), round(self.y, 4), round(self.w, 4), round(self.h, 4)],
            "cv_class": self.cv_class,
            "confidence": round(self.confidence, 3),
        }


def _intersection(a: Box, b: Box) -> float:
    w = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    h = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    return max(0.0, w) * max(0.0, h)


def iou(a: Box, b: Box) -> float:
    inter = _intersection(a, b)
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def suppress_duplicates(
    boxes: list[Box], iou_same: float = 0.5, contain_same: float = 0.85, iou_cross: float = 0.8
) -> list[Box]:
    """Оставляет одну рамку на узел.

    Детектор получает несколько названий одного типа («valve», «gate valve») и может
    дать на один узел несколько рамок. Рамки обходятся по убыванию уверенности, рамка
    отбрасывается, если уже принятая:
    - того же типа и сильно пересекается (IoU) либо одна почти целиком внутри другой;
    - другого типа, но почти совпадает — значит, это тот же предмет с другим названием.
    """
    kept: list[Box] = []
    for box in sorted(boxes, key=lambda b: b.confidence, reverse=True):
        duplicate = False
        for other in kept:
            overlap = iou(box, other)
            if box.cv_class == other.cv_class:
                smaller = min(box.area, other.area)
                contained = _intersection(box, other) / smaller if smaller > 0 else 0.0
                if overlap >= iou_same or contained >= contain_same:
                    duplicate = True
                    break
            elif overlap >= iou_cross:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def clip_box(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float] | None:
    x1, y1, x2, y2 = (min(1.0, max(0.0, v)) for v in (x1, y1, x2, y2))
    if x2 - x1 < 0.005 or y2 - y1 < 0.005:
        return None
    return x1, y1, x2 - x1, y2 - y1


class Detector:
    """Обёртка над YOLOE. Словарь классов задаётся один раз при загрузке."""

    def __init__(self, settings: Settings, device: str):
        self.settings = settings
        self.device = device
        self.classes: dict[str, ClassSpec] = settings.classes
        self._lock = threading.Lock()
        self._model = None
        # номер названия в словаре детектора -> cv_class
        self._prompt_to_class: list[str] = []
        self._prompts: list[str] = []
        for spec in self.classes.values():
            for prompt in spec.prompts:
                self._prompts.append(prompt)
                self._prompt_to_class.append(spec.cv_class)

    @property
    def name(self) -> str:
        return Path(self.settings.detector_weights).stem

    def load(self) -> None:
        path = self.settings.detector_path
        if not path.is_file():
            raise FileNotFoundError(f"Нет весов детектора: {path}. Запустите python ai/install.py")

        from ultralytics import YOLOE
        from ultralytics.utils import SETTINGS

        # Текстовый кодировщик детектор ищет в своей папке весов — направляем её на нашу,
        # иначе библиотека попробует скачать файл из интернета.
        SETTINGS["weights_dir"] = str(self.settings.weights_dir)
        SETTINGS["sync"] = False

        model = YOLOE(str(path))
        text_model = getattr(model.model, "text_model", "mobileclip:blt")
        encoder_file = {"mobileclip": "mobileclip_blt.ts", "mobileclip2": "mobileclip2_b.ts"}.get(
            text_model.split(":")[0]
        )
        if encoder_file and not (self.settings.weights_dir / encoder_file).is_file():
            raise FileNotFoundError(
                f"Нет текстового кодировщика детектора: {self.settings.weights_dir / encoder_file}. "
                "Запустите python ai/install.py"
            )
        model.set_classes(self._prompts, model.get_text_pe(self._prompts))
        self._model = model
        self._predict_raw(Image.new("RGB", (640, 480), (90, 90, 90)), 0.5)  # прогрев
        log.info("Детектор %s загружен на %s, названий в словаре: %d", self.name, self.device, len(self._prompts))

    def _predict_raw(self, image: Image.Image, conf: float):
        return self._model.predict(
            image,
            imgsz=self.settings.detector_imgsz,
            conf=conf,
            iou=self.settings.detector_iou,
            max_det=self.settings.detector_max_det * 3,
            device=self.device,
            half=self.device.startswith("cuda"),
            verbose=False,
        )[0]

    def detect(self, image: Image.Image, cv_classes: list[str] | None = None) -> list[Box]:
        """Находит узлы запрошенных типов. cv_classes=None — все типы словаря."""
        if self._model is None:
            raise RuntimeError("Детектор не загружен")
        wanted = [c for c in (cv_classes or list(self.classes)) if c in self.classes]
        if not wanted:
            return []
        min_conf = min(self.classes[c].threshold for c in wanted)
        with self._lock:
            result = self._predict_raw(image, min_conf)

        boxes: list[Box] = []
        coords = result.boxes.xyxyn.tolist()
        scores = result.boxes.conf.tolist()
        indices = result.boxes.cls.tolist()
        for (x1, y1, x2, y2), score, index in zip(coords, scores, indices):
            cv_class = self._prompt_to_class[int(index)]
            if cv_class not in wanted or score < self.classes[cv_class].threshold:
                continue
            clipped = clip_box(x1, y1, x2, y2)
            if clipped is None:
                continue
            boxes.append(Box(*clipped, cv_class=cv_class, confidence=float(score)))
        boxes = suppress_duplicates(boxes, iou_same=self.settings.detector_iou)
        return boxes[: self.settings.detector_max_det]
