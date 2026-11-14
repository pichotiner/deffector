"""Идентификация образца оборудования по изображению: сравнение с эталонными фото."""
from __future__ import annotations

import logging
import math
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from .config import Settings
from .images import ImageError, decode_image

log = logging.getLogger("ai.identifier")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _floor3(value: float) -> float:
    """Округление вниз до тысячных: 0.4999 не должно стать 0.5 (порог «распознано» у бэкенда)."""
    return math.floor(round(value * 1000, 6)) / 1000


def rank_candidates(
    similarities: dict[str, list[float]], threshold: float, top_k: int, temperature: float
) -> tuple[bool, list[dict]]:
    """Превращает сходства кадра с эталонами в список кандидатов.

    similarities: equipment_id -> косинусные сходства кадра с каждым эталонным фото образца.
    Оценка образца — среднее по top_k самых похожих эталонов. Образец считается распознанным,
    если лучшая оценка не ниже порога. Уверенность — доля образца среди кандидатов (softmax),
    умноженная на близость к эталонам, поэтому у постороннего предмета она низкая у всех.
    """
    scores = {}
    for equipment_id, values in similarities.items():
        if values:
            best = sorted(values, reverse=True)[:top_k]
            scores[equipment_id] = sum(best) / len(best)
    if not scores:
        return False, []
    top = max(scores.values())
    weights = {k: math.exp((v - top) / temperature) for k, v in scores.items()}
    total = sum(weights.values())
    # близость: 0 при оценке на 0.15 ниже порога, 0.5 ровно на пороге, 1 на 0.15 выше порога.
    # Ниже порога уверенность всегда < 0.5 — бэкенд считает «распознано» по уверенности >= 0.5
    # (backend/app/config.py, identify_threshold), и оба решения не расходятся в опасную сторону.
    closeness = min(1.0, max(0.0, (top - (threshold - 0.15)) / 0.30))
    candidates = [
        {"equipment_id": k, "confidence": _floor3(weights[k] / total * closeness)}
        for k in sorted(scores, key=lambda k: scores[k], reverse=True)
    ]
    return top >= threshold, candidates


class Identifier:
    """Векторные представления CLIP. Эталоны: demo/reference/<equipment_id>/*.jpg."""

    def __init__(self, settings: Settings, device: str):
        self.settings = settings
        self.device = device
        self._lock = threading.Lock()
        self._model = None
        self._processor = None
        self._index: dict[str, np.ndarray] = {}

    @property
    def name(self) -> str:
        return self.settings.clip_dir

    @property
    def reference_counts(self) -> dict[str, int]:
        return {k: int(v.shape[0]) for k, v in self._index.items()}

    def load(self) -> None:
        path = self.settings.clip_path
        if not (path / "config.json").is_file():
            raise FileNotFoundError(f"Нет модели идентификации: {path}. Запустите python ai/install.py")
        from transformers import CLIPImageProcessor, CLIPModel

        self._processor = CLIPImageProcessor.from_pretrained(str(path), local_files_only=True)
        self._model = CLIPModel.from_pretrained(str(path), local_files_only=True).to(self.device).eval()
        self.build_index()

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        import torch

        with self._lock, torch.inference_mode():
            inputs = self._processor(images=images, return_tensors="pt").to(self.device)
            features = self._model.get_image_features(**inputs)
            if not isinstance(features, torch.Tensor):  # новые версии возвращают объект с полем
                features = features.pooler_output
            features = torch.nn.functional.normalize(features.float(), dim=-1)
        return features.cpu().numpy()

    def build_index(self) -> None:
        index: dict[str, np.ndarray] = {}
        root: Path = self.settings.reference_dir
        if root.is_dir():
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                images = []
                for file in sorted(folder.iterdir()):
                    if file.suffix.lower() not in IMAGE_SUFFIXES:
                        continue
                    try:
                        images.append(decode_image(file.read_bytes()))
                    except ImageError:
                        log.warning("Эталонное фото не читается: %s", file)
                if images:
                    index[folder.name] = self.embed(images)
        self._index = index
        if index:
            log.info("Эталоны для идентификации: %s", self.reference_counts)
        else:
            log.warning("Эталонных фото нет в %s — /identify будет отвечать «не распознано»", root)

    def identify(self, image: Image.Image) -> dict:
        if self._model is None:
            raise RuntimeError("Модель идентификации не загружена")
        if not self._index:
            return {"recognized": False, "candidates": []}
        query = self.embed([image])[0]
        similarities = {k: (v @ query).tolist() for k, v in self._index.items()}
        recognized, candidates = rank_candidates(
            similarities,
            threshold=self.settings.identify_threshold,
            top_k=self.settings.identify_top_k,
            temperature=self.settings.identify_temperature,
        )
        return {"recognized": recognized, "candidates": candidates}
