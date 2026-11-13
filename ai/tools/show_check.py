"""Прогон листов show.pdf через /detect запущенного ИИ-сервиса — то, что видит телефон в AR.

    python ai/run.py                                        (в другом окне)
    ai/.venv/Scripts/python ai/tools/show_check.py --draw runs/show_base
    ai/.venv/Scripts/python ai/tools/show_check.py --images runs/phone      (свои снимки листов)

Берёт фото листов 1–9 и Э из demo/photos/show/make_show.py, отправляет каждое в /detect
с типами узлов карточки PU-001 и печатает по листу: что найдено, с какой уверенностью и
что лишнее. Ожидаемое — из разметки demo/photos/labels.json (листы Э в ней не размечены).
--min поднимает порог для всех рамок при просмотре (сервис при этом не меняется) —
чтобы прикинуть новый threshold в ai/classes.json до перезапуска.
"""
from __future__ import annotations

import argparse
import ast
import json
import time
from collections import Counter
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
SHOW = REPO / "demo" / "photos" / "show" / "make_show.py"
CLASSES = "electric_motor,pressure_gauge,valve,flange"  # типы узлов в карточке PU-001
SHORT = {"electric_motor": "двигатель", "pressure_gauge": "манометр", "valve": "арматура", "flange": "фланец"}
COLORS = {"electric_motor": "#e6194b", "pressure_gauge": "#3cb44b", "valve": "#4363d8", "flange": "#f58231"}

LABELS = REPO / "demo" / "photos" / "labels.json"


def expected() -> dict[Path, dict[str, int]]:
    """Сколько узлов каждого типа на фото — из разметки тестового набора (labels.json)."""
    photos = json.loads(LABELS.read_text(encoding="utf-8"))["photos"]
    base = LABELS.parent
    return {(base / name).resolve(): spec.get("nodes", {}) for name, spec in photos.items()}


def sheets() -> list[tuple[str, Path, str]]:
    """(номер, путь, подпись) из списков NODES и REFERENCES в make_show.py, без его импорта."""
    tree = ast.parse(SHOW.read_text(encoding="utf-8"))
    lists: dict[str, list] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"NODES", "REFERENCES"} and isinstance(node.value, ast.List):
                lists[name] = [
                    [e.value if isinstance(e, ast.Constant) else None for e in item.elts]
                    for item in node.value.elts
                ]
    result = [(str(i), REPO / row[0], row[1]) for i, row in enumerate(lists["NODES"], 1)]
    result += [(f"Э{i}", REPO / row[0], row[1]) for i, row in enumerate(lists["REFERENCES"], 1)]
    return result


def draw(path: Path, boxes: list[dict], target: Path) -> None:
    image = Image.open(path).convert("RGB")
    canvas = ImageDraw.Draw(image)
    w, h = image.size
    for b in boxes:
        x, y, bw, bh = b["bbox"]
        color = COLORS.get(b["cv_class"], "#ffffff")
        canvas.rectangle([x * w, y * h, (x + bw) * w, (y + bh) * h], outline=color, width=4)
        canvas.text((x * w + 6, y * h + 6), f'{b["cv_class"]} {b["confidence"]:.2f}', fill=color)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, quality=85)


def main() -> None:
    ap = argparse.ArgumentParser(description="Листы show.pdf через /detect")
    ap.add_argument("--url", default="http://127.0.0.1:8001")
    ap.add_argument("--min", type=float, default=0.0, help="показывать только рамки не ниже этого порога")
    ap.add_argument("--draw", type=Path, help="папка для фото с нарисованными рамками")
    ap.add_argument("--report", type=Path, help="сохранить ответы в JSON")
    ap.add_argument("--images", type=Path,
                    help="вместо листов — все .jpg/.png из папки (например, снимки листов телефоном)")
    args = ap.parse_args()

    report = []
    times = []
    expect = expected()
    with httpx.Client(base_url=args.url, timeout=60) as client:
        items = sheets()
        if args.images:
            files = sorted(p for p in args.images.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
            items = [(str(i), p, p.name) for i, p in enumerate(files, 1)]
        for number, path, title in items:
            if not path.exists():
                print(f"{number:>3}  нет файла {path}")
                continue
            start = time.perf_counter()
            r = client.post("/detect", files={"image": (path.name, path.read_bytes(), "image/jpeg")},
                            data={"classes": CLASSES})
            times.append((time.perf_counter() - start) * 1000)
            r.raise_for_status()
            body = r.json()
            boxes = body if isinstance(body, list) else body.get("detections", [])
            boxes = [b for b in boxes if b["confidence"] >= args.min]
            found = Counter(b["cv_class"] for b in boxes)
            got = ", ".join(f'{SHORT.get(b["cv_class"], b["cv_class"])} {b["confidence"]:.2f}'
                            for b in sorted(boxes, key=lambda b: -b["confidence"])) or "ничего"
            verdict = ""
            if path.resolve() in expect:
                want = Counter(expect[path.resolve()])
                missing = want - found
                extra = found - want
                parts = []
                if missing:
                    parts.append("нет: " + ", ".join(f"{SHORT[k]}×{v}" for k, v in missing.items()))
                if extra:
                    parts.append("лишние: " + ", ".join(f"{SHORT.get(k, k)}×{v}" for k, v in extra.items()))
                verdict = "ок" if not parts else "; ".join(parts)
            print(f"{number:>3}  {title[:38]:<38}  {got}" + (f"  → {verdict}" if verdict else ""))
            report.append({"sheet": number, "file": str(path), "boxes": boxes, "verdict": verdict})
            if args.draw:
                draw(path, boxes, args.draw / f"{number}_{path.stem}.jpg")
    if times:
        times.sort()
        print(f"\n/detect: медиана {times[len(times) // 2]:.0f} мс, листов {len(times)}"
              + (f", порог просмотра {args.min}" if args.min else ""))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
