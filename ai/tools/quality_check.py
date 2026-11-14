"""Замороженные входы анализа: полный кадр и detect → crop (+15 %) → JPEG 85.

prepare сохраняет входы один раз, run повторяет их без нового detect, чтобы сравнение
инструкций не зависело от изменения рамок. Это имитация цепочки, не кадры телефона.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import statistics
import time
from pathlib import Path

import httpx
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
NAMES = {"electric_motor": "Электродвигатель", "pressure_gauge": "Манометр",
         "valve": "Запорная арматура", "flange": "Фланцевое соединение"}

# Группы зафиксированы до эксперимента; все варианты исходника — в одной группе.
SOURCES = [
    ("demo/photos/gauge_corrosion_01.jpg", "pressure_gauge", "tune", ["electric_motor"]),
    ("demo/photos/motor_corrosion_01.jpg", "electric_motor", "tune", []),
    ("demo/photos/valve_leak_01.jpg", "valve", "tune", ["electric_motor"]),
    ("demo/photos/gauge_clean_02.jpg", "pressure_gauge", "control", ["electric_motor"]),
    ("demo/photos/flange_corrosion_02.jpg", "flange", "control", ["electric_motor"]),
    ("demo/photos/pump_unit_01.jpg", "electric_motor", "control", []),
    ("docs/case/Запорная арматура/cca9d029-459e-5007-8f88-181843ed8665.jpg", "valve", "control", ["electric_motor"]),
    ("demo/photos/other/room_01.jpg", None, "control", ["electric_motor"]),
    ("demo/photos/other/car_01.jpg", None, "control", ["pressure_gauge"]),
]
CHAIN_SOURCES = [
    ("docs/case/Запорная арматура/86.PNG", "valve", "control", []),
    ("docs/case/Запорная арматура/1396430378_7447321.jpg", "valve", "control", []),
]


def jpeg(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=85)
    return stream.getvalue()


def crop_pixels(b: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    """Порт Geometry.kt: нормализация, поля по 15 %, floor/ceil, ограничение кадром."""
    x, y, w, h = b
    left, top = max(0, min(1, x)), max(0, min(1, y))
    right, bottom = max(left, min(1, x + w)), max(top, min(1, y + h))
    px, py = (right - left) * .15, (bottom - top) * .15
    l = max(0, min(width - 1, math.floor((left - px) * width + 1e-7)))
    t = max(0, min(height - 1, math.floor((top - py) * height + 1e-7)))
    r = max(l + 1, min(width, math.ceil((right + px) * width - 1e-7)))
    d = max(t + 1, min(height, math.ceil((bottom + py) * height - 1e-7)))
    return l, t, r, d


def prepare(root: Path, client: httpx.Client, simulations: Path | None = None, chain: bool = False) -> None:
    if (root / "manifest.json").exists():
        raise SystemExit("Набор уже заморожен; используйте новую папку, не перезаписывайте входы.")
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    sources = SOURCES if simulations is None else [
        (str(p.resolve()), "pressure_gauge", "tune", ["electric_motor"])
        for p in sorted(simulations.glob("*/04.jpg"))
    ]
    if chain:
        sources = CHAIN_SOURCES
    if not sources:
        raise SystemExit("Нет исходников для подготовки набора.")
    for number, (source, actual, split, wrong) in enumerate(sources):
        image = Image.open(REPO / source).convert("RGB")
        tasks = [(actual, True)] if actual else []
        tasks += [(kind, False) for kind in wrong]
        if chain:
            tasks = []
        for kind, matches in tasks:
            name = f"{number:02d}_full_{kind}"
            (root / f"{name}.jpg").write_bytes(jpeg(image))
            cases.append(dict(id=name, source=source, split=split, mode="full",
                              component_type=kind, expected_match=matches))
        # AppState.kt уменьшает ширину до 640 для detect, но режет исходный bitmap.
        resized = image.resize((640, max(1, math.floor(image.height * 640 / image.width + .5))))
        response = client.post("/detect", files={"image": ("frame.jpg", jpeg(resized), "image/jpeg")},
                               data={"classes": ",".join(NAMES)})
        response.raise_for_status()
        detections = response.json()
        for index, detection in enumerate(detections):
            kind = detection["cv_class"]
            # Для этих крупных планов известен один тип. Остальные случаи требуют просмотра.
            matches = kind == actual if simulations or number in {0, 1, 3, 7, 8} else None
            if chain:
                matches = False if kind == "pressure_gauge" else None
            name = f"{number:02d}_crop{index}_{kind}"
            cropped = image.crop(crop_pixels(detection["bbox"], *image.size))
            (root / f"{name}.jpg").write_bytes(jpeg(cropped))
            cases.append(dict(id=name, source=source, split=split, mode="detect_crop",
                              component_type=kind, expected_match=matches, detection=detection))
    for case in cases:
        case["sha256"] = hashlib.sha256((root / f"{case['id']}.jpg").read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Заморожено входов: {len(cases)}")


def run(root: Path, report: Path, client: httpx.Client, repeats: int) -> None:
    cases = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not cases:
        raise SystemExit("Набор входов пуст.")
    results = []
    for case in cases:
        data = (root / f"{case['id']}.jpg").read_bytes()
        if hashlib.sha256(data).hexdigest() != case["sha256"]:
            raise SystemExit(f"Вход изменён: {case['id']}")
        for repeat in range(repeats):
            started = time.perf_counter()
            response = client.post("/analyze", files={"image": ("crop.jpg", data, "image/jpeg")},
                                   data={"component_type": case["component_type"],
                                         "component_name": NAMES[case["component_type"]]})
            response.raise_for_status()
            result = response.json()
            results.append(dict(case=case, repeat=repeat, seconds=time.perf_counter() - started, result=result))
            print(case["id"], repeat, result["category"], result["signs"], result["explanation"], flush=True)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    times = [r["seconds"] for r in results]
    print(f"Запросов: {len(times)}, медиана {statistics.median(times):.3f} с, максимум {max(times):.3f} с")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--simulations", type=Path, help="prepare: папка имитаций */04.jpg манометра")
    parser.add_argument("--chain", action="store_true", help="prepare: ошибочные рамки манометра на арматуре")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    if args.chain and args.simulations:
        parser.error("--chain и --simulations — отдельные наборы")
    if args.action == "run" and (not args.report or args.repeats < 1):
        parser.error("для run нужны --report и положительное --repeats")
    with httpx.Client(base_url=args.url, trust_env=False, timeout=60) as client:
        health = client.get("/health")
        health.raise_for_status()
        if health.json().get("status") != "ok" or health.json().get("stub"):
            raise SystemExit("Нужен полностью готовый настоящий сервис")
        if args.action == "prepare":
            prepare(args.inputs, client, args.simulations, args.chain)
        else:
            run(args.inputs, args.report, client, args.repeats)


if __name__ == "__main__":
    main()
