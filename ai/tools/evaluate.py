"""Прогон тестового набора через запущенный ИИ-сервис и таблица для ai/README.md.

    python ai/run.py                         (в другом окне)
    ai/.venv/Scripts/python ai/tools/evaluate.py --draw eval_out

Набор — demo/photos/labels.json. Узлы считаются по количеству каждого типа на фото
(положение рамок смотрим глазами на картинках из --draw).
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
SIGN_TEXT = {"corrosion": "коррозия", "leak": "течь/подтёки", "mechanical_damage": "механическое повреждение", "overheating": "следы перегрева"}
COLORS = {"electric_motor": "#e6194b", "pressure_gauge": "#3cb44b", "valve": "#4363d8", "flange": "#f58231"}


def draw(image_path: Path, detections: list[dict], target: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    canvas = ImageDraw.Draw(image)
    width, height = image.size
    for d in detections:
        x, y, w, h = d["bbox"]
        color = COLORS.get(d["cv_class"], "#ffffff")
        canvas.rectangle([x * width, y * height, (x + w) * width, (y + h) * height], outline=color, width=4)
        canvas.text((x * width + 6, y * height + 6), f'{d["cv_class"]} {d["confidence"]:.2f}', fill=color)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, quality=85)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--photos", type=Path, default=REPO / "demo" / "photos")
    parser.add_argument("--draw", type=Path, help="папка для фото с нарисованными рамками")
    parser.add_argument("--skip-analyze", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--report", type=Path, help="сохранить подробный отчёт в JSON")
    args = parser.parse_args()

    labels = json.loads((args.photos / "labels.json").read_text(encoding="utf-8"))["photos"]
    client = httpx.Client(base_url=args.url, timeout=args.timeout, trust_env=False)
    health = client.get("/health").json()
    while health.get("status") == "loading":  # модели ещё загружаются
        time.sleep(2)
        health = client.get("/health").json()
    print("Сервис:", json.dumps(health, ensure_ascii=False))
    classes = health.get("classes") or list(COLORS)

    labeled, found, false_boxes = Counter(), Counter(), 0
    detect_ms, analyze_ms = [], []
    sign_total, sign_ok = Counter(), Counter()
    clean_total = clean_as_defect = clean_ok = 0
    defect_total = defect_missed = 0
    report = {}

    for name, label in labels.items():
        data = (args.photos / name).read_bytes()
        files = {"image": (Path(name).name, data, "image/jpeg")}
        started = time.perf_counter()
        detections = client.post("/detect", files=files).json()
        detect_ms.append((time.perf_counter() - started) * 1000)
        counts = Counter(d["cv_class"] for d in detections)
        for cv_class in classes:
            if cv_class in label.get("skip", []):
                continue
            want, got = label["nodes"].get(cv_class, 0), counts.get(cv_class, 0)
            labeled[cv_class] += want
            found[cv_class] += min(want, got)
            false_boxes += max(0, got - want)
        entry = {"detections": detections}
        line = f"{Path(name).name}: рамки {dict(counts)} (ожидалось {label['nodes']})"
        if args.draw:
            flat = name.replace("../", "").replace("/", "__")  # фото заказчика лежат вне папки набора
            draw(args.photos / name, detections, args.draw / Path(flat).with_suffix(".jpg"))

        task = label.get("analyze")
        if task and not args.skip_analyze:
            started = time.perf_counter()
            result = client.post(
                "/analyze",
                files=files,
                data={"component_type": task["component_type"], "component_name": task["component_name"]},
            ).json()
            analyze_ms.append((time.perf_counter() - started) * 1000)
            entry["analysis"] = result
            category, signs = result.get("category"), result.get("signs", [])
            expected = [SIGN_TEXT[s] for s in task["signs"]]
            if expected:
                defect_total += 1
                defect_missed += category == "no_visible_issues"
                hit = [s for s in expected if s in signs]
                ok = category != "no_visible_issues" and (bool(hit) if task.get("any_sign") else len(hit) == len(expected))
                for sign in (hit[:1] or expected[:1]) if task.get("any_sign") else expected:
                    sign_total[sign] += 1
                    sign_ok[sign] += ok and sign in signs
            else:
                clean_total += 1
                clean_ok += category == "no_visible_issues"
                clean_as_defect += category == "possible_defect"
            line += f"\n    анализ: {category} {signs} — {result.get('explanation')}"
        report[name] = entry
        print(line, flush=True)

    def ms(values: list[float]) -> str:
        if not values:
            return "—"
        return f"медиана {statistics.median(values):.0f} мс, максимум {max(values):.0f} мс"

    photos = len(labels)
    print("\n| Что считаем | Результат |\n|---|---|")
    per_class = ", ".join(f"{c}: {found[c]} из {labeled[c]}" for c in classes)
    print(f"| Узлов найдено из размеченных, по каждому типу | {per_class} |")
    print(f"| Ложных рамок на кадр | {false_boxes / photos:.2f} ({false_boxes} на {photos} фото) |")
    per_sign = ", ".join(f"{s}: {sign_ok[s]} из {sign_total[s]}" for s in SIGN_TEXT.values() if sign_total[s]) or "—"
    print(f"| Категория совпала с ожидаемой, по каждому признаку | {per_sign}; без признаков: {clean_ok} из {clean_total} |")
    print(f"| Чистые кадры, ошибочно получившие «возможный дефект» | {clean_as_defect} из {clean_total} |")
    print(f"| Кадры с дефектом, получившие «видимых проблем не обнаружено» | {defect_missed} из {defect_total} |")
    print(f"| Время ответа `/detect` и `/analyze` | detect: {ms(detect_ms)}; analyze: {ms(analyze_ms)} |")
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
