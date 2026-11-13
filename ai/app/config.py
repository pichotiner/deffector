"""Настройки ИИ-сервиса. Всё задаётся переменными окружения с префиксом AI_."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = AI_DIR.parent


def apply_offline_env() -> None:
    """Запрещает библиотекам ходить в интернет. Вызывается до импорта torch и transformers."""
    offline = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "DO_NOT_TRACK": "1",
    }
    for key, value in offline.items():
        os.environ[key] = value


def _env(name: str, default: str) -> str:
    return os.environ.get(f"AI_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(f"AI_{name}")
    return Path(value).expanduser().resolve() if value else default


@dataclass(frozen=True)
class ClassSpec:
    cv_class: str
    name: str
    prompts: tuple[str, ...]
    threshold: float


@dataclass(frozen=True)
class Settings:
    stub: bool = False
    host: str = "127.0.0.1"
    port: int = 8001
    device: str = "auto"  # auto | cpu | cuda | cuda:0

    weights_dir: Path = AI_DIR / "weights"
    classes_file: Path = AI_DIR / "classes.json"
    reference_dir: Path = REPO_DIR / "demo" / "reference"

    # Детектор узлов
    detector_dir: str = "owlv2"
    detector_max_area: float = 0.85
    detector_iou: float = 0.5
    detector_max_det: int = 30

    # Мультимодальная модель (Ollama)
    ollama_url: str = "http://127.0.0.1:11434"
    vlm_model: str = "qwen2.5vl:7b"
    analyze_timeout_s: float = 15.0
    vlm_image_side: int = 896
    vlm_num_ctx: int = 4096
    warmup: bool = True

    # Идентификация по изображению
    clip_dir: str = "clip"
    identify_threshold: float = 0.66
    identify_top_k: int = 1
    identify_temperature: float = 0.03

    # Проверка качества снимка кодом
    min_side_px: int = 64
    min_brightness: float = 30.0
    min_sharpness: float = 15.0

    classes: dict[str, ClassSpec] = field(default_factory=dict)

    @property
    def detector_path(self) -> Path:
        return self.weights_dir / self.detector_dir

    @property
    def clip_path(self) -> Path:
        return self.weights_dir / self.clip_dir


def load_classes(path: Path) -> dict[str, ClassSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, ClassSpec] = {}
    for cv_class, spec in data["classes"].items():
        prompts = tuple(p.strip() for p in spec["prompts"] if p.strip())
        if not prompts:
            raise ValueError(f"{path}: у класса {cv_class} нет ни одного названия для детектора")
        result[cv_class] = ClassSpec(
            cv_class=cv_class,
            name=spec.get("name", cv_class),
            prompts=prompts,
            threshold=float(spec.get("threshold", 0.25)),
        )
    return result


def _num(kind, name: str, default: str, low=None):
    """Число из переменной AI_<name>; мусор — понятная ошибка, а не трасса."""
    raw = _env(name, default)
    try:
        value = kind(str(raw).replace(",", "."))
    except ValueError:
        raise SystemExit(f"ОШИБКА: переменная AI_{name}={raw!r} — нужно число (например {default})") from None
    return max(low, value) if low is not None else value


def load_settings() -> Settings:
    classes_file = _env_path("CLASSES_FILE", AI_DIR / "classes.json")
    return Settings(
        stub=_env_bool("STUB", False),
        host=_env("HOST", "127.0.0.1"),
        port=_num(int, "PORT", "8001"),
        device=_env("DEVICE", "auto"),
        weights_dir=_env_path("WEIGHTS_DIR", AI_DIR / "weights"),
        classes_file=classes_file,
        reference_dir=_env_path("REFERENCE_DIR", REPO_DIR / "demo" / "reference"),
        detector_dir=_env("DETECTOR_DIR", "owlv2"),
        detector_max_area=_num(float, "DETECTOR_MAX_AREA", "0.85"),
        detector_iou=_num(float, "DETECTOR_IOU", "0.5"),
        detector_max_det=_num(int, "DETECTOR_MAX_DET", "30", low=1),
        ollama_url=_env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        vlm_model=_env("VLM_MODEL", "qwen2.5vl:7b"),
        analyze_timeout_s=_num(float, "ANALYZE_TIMEOUT_S", "15", low=1),
        vlm_image_side=_num(int, "VLM_IMAGE_SIDE", "896", low=64),
        vlm_num_ctx=_num(int, "VLM_NUM_CTX", "4096", low=1024),
        warmup=_env_bool("WARMUP", True),
        clip_dir=_env("CLIP_DIR", "clip"),
        identify_threshold=_num(float, "IDENTIFY_THRESHOLD", "0.66"),
        identify_top_k=_num(int, "IDENTIFY_TOP_K", "1", low=1),
        identify_temperature=_num(float, "IDENTIFY_TEMPERATURE", "0.03", low=1e-3),
        min_side_px=_num(int, "MIN_SIDE_PX", "64"),
        min_brightness=_num(float, "MIN_BRIGHTNESS", "30"),
        min_sharpness=_num(float, "MIN_SHARPNESS", "15"),
        classes=load_classes(classes_file),
    )
