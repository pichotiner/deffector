"""Распознавание узлов: детектор с открытым словарём (OWLv2) и обработка рамок."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

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
    """Обёртка над OWLv2. Классы задаются текстом из classes.json, обучение не нужно."""

    def __init__(self, settings: Settings, device: str):
        self.settings = settings
        self.device = device
        self.classes: dict[str, ClassSpec] = settings.classes
        self._lock = threading.Lock()
        self._model = None
        self._processor = None
        self._text_inputs = None
        # номер названия в словаре детектора -> cv_class
        self._prompt_to_class: list[str] = []
        self._prompts: list[str] = []
        for spec in self.classes.values():
            for prompt in spec.prompts:
                self._prompts.append(prompt)
                self._prompt_to_class.append(spec.cv_class)

    @property
    def name(self) -> str:
        return self.settings.detector_dir

    def load(self) -> None:
        path = self.settings.detector_path
        if not (path / "config.json").is_file():
            raise FileNotFoundError(f"Нет весов детектора: {path}. Запустите python ai/install.py")

        import torch
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        self._processor = Owlv2Processor.from_pretrained(str(path), local_files_only=True)
        model = Owlv2ForObjectDetection.from_pretrained(str(path), local_files_only=True)
        if self.device.startswith("cuda"):
            model = model.half()
        self._model = model.to(self.device).eval()
        # названия классов не меняются — переводим их в числа один раз
        text = self._processor(text=[self._prompts], return_tensors="pt")
        self._text_inputs = {k: v.to(self.device) for k, v in text.items()}
        self._torch = torch
        self._predict_raw(Image.new("RGB", (640, 480), (90, 90, 90)), 0.5)  # прогрев
        log.info("Детектор %s загружен на %s, названий в словаре: %d", self.name, self.device, len(self._prompts))

    def _predict_raw(self, image: Image.Image, conf: float) -> list[tuple[float, float, float, float, float, int]]:
        """Возвращает рамки (x1, y1, x2, y2 в долях кадра), уверенность и номер названия."""
        torch = self._torch
        width, height = image.size
        side = max(width, height)  # модель дополняет кадр до квадрата снизу и справа
        pixels = self._processor(images=image, return_tensors="pt")["pixel_values"]
        pixels = pixels.to(self.device, dtype=next(self._model.parameters()).dtype)
        with torch.inference_mode():
            outputs = self._model(pixel_values=pixels, **self._text_inputs)
            scores, labels = torch.max(torch.sigmoid(outputs.logits[0].float()), dim=-1)
            keep = scores >= conf
            scores, labels = scores[keep], labels[keep]
            cx, cy, w, h = outputs.pred_boxes[0].float()[keep].unbind(-1)
        result = []
        for s, l, bx, by, bw, bh in zip(
            scores.tolist(), labels.tolist(), cx.tolist(), cy.tolist(), w.tolist(), h.tolist()
        ):
            x1, x2 = (bx - bw / 2) * side / width, (bx + bw / 2) * side / width
            y1, y2 = (by - bh / 2) * side / height, (by + bh / 2) * side / height
            result.append((x1, y1, x2, y2, s, l))
        return result

    def detect(self, image: Image.Image, cv_classes: list[str] | None = None) -> list[Box]:
        """Находит узлы запрошенных типов. cv_classes=None — все типы словаря."""
        if self._model is None:
            raise RuntimeError("Детектор не загружен")
        wanted = [c for c in (cv_classes or list(self.classes)) if c in self.classes]
        if not wanted:
            return []
        min_conf = min(self.classes[c].threshold for c in wanted)
        with self._lock:
            raw = self._predict_raw(image, min_conf)

        boxes: list[Box] = []
        for x1, y1, x2, y2, score, index in raw:
            cv_class = self._prompt_to_class[int(index)]
            if cv_class not in wanted or score < self.classes[cv_class].threshold:
                continue
            clipped = clip_box(x1, y1, x2, y2)
            if clipped is None or clipped[2] * clipped[3] > self.settings.detector_max_area:
                continue  # рамка на весь кадр — не узел
            boxes.append(Box(*clipped, cv_class=cv_class, confidence=float(score)))
        boxes = suppress_duplicates(boxes, iou_same=self.settings.detector_iou)
        return boxes[: self.settings.detector_max_det]
