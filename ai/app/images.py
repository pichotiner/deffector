"""Чтение изображений и проверка качества снимка кодом."""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class ImageError(ValueError):
    """Файл не является изображением, которое можно прочитать."""


def decode_image(data: bytes) -> Image.Image:
    if not data:
        raise ImageError("Пустой файл изображения")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("Изображение больше 20 МБ")
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)  # фото с телефона хранят поворот в EXIF
        return image.convert("RGB")
    except Exception as exc:  # библиотеки подменяют Image.open, тип ошибки заранее не известен
        raise ImageError("Не удалось прочитать изображение") from exc


def resize_max_side(image: Image.Image, max_side: int) -> Image.Image:
    width, height = image.size
    scale = max_side / max(width, height)
    if scale >= 1:
        return image
    return image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)


def to_jpeg(image: Image.Image, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


@dataclass(frozen=True)
class Quality:
    ok: bool
    reason: str | None  # понятная человеку причина, если снимок плохой
    brightness: float
    sharpness: float


def check_quality(image: Image.Image, min_side_px: int, min_brightness: float, min_sharpness: float) -> Quality:
    """Грубая проверка: слишком мелкий, тёмный или смазанный снимок.

    Проверка намеренно мягкая: она отсекает только явно непригодные кадры, остальное
    оценивает мультимодальная модель.
    """
    width, height = image.size
    gray = np.asarray(resize_max_side(image, 512).convert("L"), dtype=np.float32)
    brightness = float(gray.mean())
    if gray.shape[0] >= 3 and gray.shape[1] >= 3:
        laplacian = (
            gray[1:-1, :-2] + gray[1:-1, 2:] + gray[:-2, 1:-1] + gray[2:, 1:-1] - 4.0 * gray[1:-1, 1:-1]
        )
        sharpness = float(laplacian.var())
    else:
        sharpness = 0.0

    reason = None
    if min(width, height) < min_side_px:
        reason = "узел на снимке слишком мелкий"
    elif brightness < min_brightness:
        reason = "снимок слишком тёмный"
    elif sharpness < min_sharpness:
        reason = "снимок смазан"
    return Quality(ok=reason is None, reason=reason, brightness=brightness, sharpness=sharpness)
