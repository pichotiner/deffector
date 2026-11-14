"""Оценка координат рамок (IoU), независимо от старого подсчёта количества.

python ai/tools/evaluate_boxes.py --report runs/boxes.json --draw runs/boxes
python ai/tools/evaluate_boxes.py --predictions runs/eval_before.json --report runs/boxes_saved.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
CLASSES = ("electric_motor", "pressure_gauge", "valve", "flange")


def validate_box(box: list[float]) -> None:
    if not isinstance(box, list) or len(box) != 4 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box
    ):
        raise ValueError(f"Некорректная рамка: {box!r}")
    x, y, w, h = box
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError(f"Рамка вне кадра или пустая: {box!r}")


def intersection(a: list[float], b: list[float]) -> float:
    return max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(
        0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))


def iou(a: list[float], b: list[float]) -> float:
    overlap = intersection(a, b)
    return overlap / (a[2] * a[3] + b[2] * b[3] - overlap)


def metrics(tp: int, fp: int, fn: int) -> dict:
    return dict(tp=tp, fp=fp, fn=fn, precision=tp / (tp + fp) if tp + fp else None,
                recall=tp / (tp + fn) if tp + fn else None)


def score_frame(frame: dict, predictions: list[dict], threshold: float = .5) -> dict:
    """Confidence ↓, затем исходный индекс; равный IoU → меньший индекс эталона.

    Сначала сопоставляем GT. Только несопоставленная рамка может быть исключена:
    класс не размечен целиком либо ≥50 % площади рамки лежит в ignore_region
    этого класса. Область игнорирования не подтверждает обнаружение.
    """
    if not 0 < threshold <= 1:
        raise ValueError("Порог IoU должен быть в (0, 1]")
    scope = frame["evaluated_classes"]
    if not set(scope) <= set(CLASSES):
        raise ValueError("Неизвестный класс в evaluated_classes")
    truth = frame["objects"]
    ignored = frame.get("ignore_regions", [])
    for obj in truth + ignored:
        validate_box(obj["bbox"])
        if obj["cv_class"] not in scope:
            raise ValueError("Эталон/исключение вне размеченных классов")
    for pred in predictions:
        validate_box(pred["bbox"])
        confidence = pred.get("confidence")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("Некорректная уверенность")
        if pred["cv_class"] not in CLASSES:
            raise ValueError("Неизвестный класс предсказания")
    matched, decisions = set(), []
    counts = {c: [0, 0, 0] for c in CLASSES}
    for index in sorted(range(len(predictions)), key=lambda i: (-predictions[i]["confidence"], i)):
        pred = predictions[index]
        kind = pred["cv_class"]
        if kind not in scope:
            decisions.append(dict(prediction=index, status="unscored_class"))
            continue
        choices = [(iou(pred["bbox"], obj["bbox"]), -j, j) for j, obj in enumerate(truth)
                   if obj["cv_class"] == kind and j not in matched]
        best, _, j = max(choices, default=(0, 0, -1))
        if j >= 0 and best >= threshold:
            matched.add(j)
            counts[kind][0] += 1
            decisions.append(dict(prediction=index, status="tp", target=j, iou=best))
        elif any(region["cv_class"] == kind and
                 intersection(pred["bbox"], region["bbox"]) / (pred["bbox"][2] * pred["bbox"][3]) >= .5
                 for region in ignored):
            decisions.append(dict(prediction=index, status="ignored_region"))
        else:
            counts[kind][1] += 1
            decisions.append(dict(prediction=index, status="fp", best_unmatched_iou=best))
    missing = [j for j in range(len(truth)) if j not in matched]
    for j in missing:
        counts[truth[j]["cv_class"]][2] += 1
    return dict(metrics={c: metrics(*counts[c]) for c in CLASSES}, decisions=decisions, missing=missing)


def draw_frame(frame: dict, predictions: list[dict], scored: dict, target: Path) -> None:
    image = Image.open(REPO / frame["file"]).convert("RGB")
    image.thumbnail((1280, 1280))
    canvas = ImageDraw.Draw(image)
    def box(obj, text, color, inset=0):
        x, y, w, h = obj["bbox"]
        left, top = x * image.width, y * image.height
        canvas.rectangle((left, top, (x + w) * image.width, (y + h) * image.height), outline=color, width=3)
        canvas.text((left + 3, top + 3 + inset), text, fill=color, stroke_width=1, stroke_fill="black")
    for j, obj in enumerate(frame["objects"]):
        box(obj, f'GT{j} {obj["cv_class"]}', "#00ff80")
    for obj in frame.get("ignore_regions", []):
        box(obj, f'IGNORE {obj["cv_class"]}', "#aaaaaa")
    for decision in scored["decisions"]:
        pred = predictions[decision["prediction"]]
        box(pred, f'{decision["status"]} {pred["cv_class"]} {pred["confidence"]:.2f}',
            "#ffff00" if decision["status"] == "tp" else "#ff4080", 16)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)


def saved_predictions(path: Path, root: Path) -> dict[Path, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):  # show_check.py
        return {Path(row["file"]).resolve(): row["boxes"] for row in data}
    if "frames" in data:  # собственный отчёт, пути от корня репозитория
        return {(REPO / row["file"]).resolve(): row["detections"] for row in data["frames"].values()}
    # evaluate.py: ключи относительно demo/photos
    return {(root / name).resolve(): row["detections"] for name, row in data.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=REPO / "demo/photos/quality/labels.json")
    parser.add_argument("--predictions", type=Path, help="сохранённые ответы evaluate.py, show_check.py или этого инструмента")
    parser.add_argument("--prediction-root", type=Path, default=REPO / "demo/photos")
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--draw", type=Path)
    parser.add_argument("--iou", type=float, default=.5)
    args = parser.parse_args()
    if not 0 < args.iou <= 1:
        parser.error("--iou должен быть в (0, 1]")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    totals = {c: [0, 0, 0] for c in CLASSES}
    splits = {s: {c: [0, 0, 0] for c in CLASSES} for s in ("tune", "control")}
    report = dict(iou_threshold=args.iou, ignore_prediction_area_fraction=.5,
                  labels_sha256=hashlib.sha256(args.labels.read_bytes()).hexdigest(), frames={})
    saved = saved_predictions(args.predictions, args.prediction_root) if args.predictions else None
    with httpx.Client(base_url=args.url, trust_env=False, timeout=60) as client:
        if saved is None:
            response = client.get("/health")
            response.raise_for_status()
            report["health"] = response.json()
            if report["health"].get("status") != "ok" or report["health"].get("stub"):
                raise SystemExit("Нужен готовый настоящий сервис")
        for name, frame in labels["frames"].items():
            path = (REPO / frame["file"]).resolve()
            started = time.perf_counter()
            if saved is not None:
                if path not in saved:
                    raise SystemExit(f"Нет сохранённого ответа для {frame['file']}")
                predictions = saved[path]
            else:
                response = client.post("/detect", files={"image": (path.name, path.read_bytes(), "image/jpeg")},
                                       data={"classes": ",".join(CLASSES)})
                response.raise_for_status()
                predictions = response.json()
            scored = score_frame(frame, predictions, args.iou)
            report["frames"][name] = dict(file=frame["file"], split=frame["split"], detections=predictions, **scored)
            if saved is None:
                report["frames"][name]["seconds"] = time.perf_counter() - started
            for kind, counts in scored["metrics"].items():
                for i, key in enumerate(("tp", "fp", "fn")):
                    totals[kind][i] += counts[key]
                    splits[frame["split"]][kind][i] += counts[key]
            if args.draw:
                draw_frame(frame, predictions, scored, args.draw / f"{name}.jpg")
    report["metrics"] = {c: metrics(*v) for c, v in totals.items()}
    report["splits"] = {s: {c: metrics(*v) for c, v in counts.items()} for s, counts in splits.items()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for kind, values in report["metrics"].items():
        print(kind, values)


if __name__ == "__main__":
    main()
