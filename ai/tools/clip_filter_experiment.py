"""Изолированный опыт CLIP изображение↔изображение; рабочий сервис не меняется.

Порядок: capture → review → features --phase tune → fit → features --phase holdout
→ features --phase regression → evaluate → benchmark → summarize. Результаты в отдельной runs/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "ai"))
from app.config import apply_offline_env
apply_offline_env()
from app.images import decode_image
from tools.evaluate_boxes import CLASSES, draw_frame, iou, metrics, score_frame, validate_box
from tools.quality_check import jpeg

DEFAULT_PLAN = REPO / "demo/photos/quality/clip-experiment.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crop(image: Image.Image, box: list[float], padding: float) -> Image.Image:
    validate_box(box)
    x, y, w, h = box
    left = max(0, math.floor((x - padding * w) * image.width + 1e-7))
    top = max(0, math.floor((y - padding * h) * image.height + 1e-7))
    right = min(image.width, math.ceil((x + w + padding * w) * image.width - 1e-7))
    bottom = min(image.height, math.ceil((y + h + padding * h) * image.height - 1e-7))
    return image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))


def load_plan(path: Path) -> tuple[dict, dict, dict]:
    plan = read(path)
    assignments = {}
    for group in plan["groups"]:
        if group["phase"] not in {"bank", "tune", "holdout", "regression"}:
            raise ValueError("Неизвестная группа")
        for source in group["files"]:
            if source in assignments:
                raise ValueError(f"Повторная группа исходника: {source}")
            assignments[source] = dict(group=group["id"], phase=group["phase"])
    if {row["cv_class"] for row in plan["bank"]} != set(CLASSES) | {"negative"}:
        raise ValueError("Нужны положительные примеры всех четырёх типов и отрицательные")
    bank_hashes = set()
    for row in plan["bank"]:
        validate_box(row["bbox"])
        if assignments.get(row["file"], {}).get("phase") != "bank":
            raise ValueError("Исходник банка пересекается с проверкой")
        bank_hashes.add(digest(REPO / row["file"]))
    for source, group in assignments.items():
        if group["phase"] != "bank" and digest(REPO / source) in bank_hashes:
            raise ValueError("Копия исходника банка в проверочной группе")
    labels = {row["file"]: dict(row) for row in read(REPO / plan["quality_labels"])["frames"].values()}
    for row in plan["additional_frames"].values():
        if row["file"] in labels:
            raise ValueError("Нельзя молча заменить прежнюю разметку")
        score_frame(row, [])
        labels[row["file"]] = row
    return plan, assignments, labels


def load_service():
    from app.main import Service
    service = Service()
    if service.settings.stub:
        raise RuntimeError("Нужны настоящие модели")
    service.load_models()
    if not all(state.ready for state in service.states.values()) or service.device != "cuda:0":
        raise RuntimeError(f"Модели не готовы на GPU: {service.health()}")
    return service


def capture(plan_path: Path, root: Path) -> None:
    target = root / "capture.json"
    if target.exists():
        raise SystemExit("Ответы уже заморожены; выберите новую папку, не перезаписывайте их")
    plan, assignments, labels = load_plan(plan_path)
    legacy = read(REPO / plan["legacy_labels"])["photos"]
    sources = {(REPO / "demo/photos" / name).resolve().relative_to(REPO).as_posix(): spec
               for name, spec in legacy.items()}
    for source in list(labels) + list(assignments):
        sources.setdefault(source, None)
    service = load_service()
    report = dict(plan_sha256=digest(plan_path), labels_sha256=digest(REPO / plan["quality_labels"]),
                  head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
                  health=service.health(), frames={})
    for source, old in sources.items():
        group = assignments.get(source, dict(group=source, phase="regression"))
        data = (REPO / source).read_bytes()
        # Ищем также неуказанные в assignments точные копии банка.
        bank_sources = [row["file"] for row in plan["bank"]]
        if group["phase"] != "bank" and any(hashlib.sha256(data).hexdigest() == digest(REPO / p) for p in bank_sources):
            raise ValueError(f"Утечка банка: {source}")
        image = decode_image(data)
        sid = hashlib.sha256(source.encode()).hexdigest()[:12]
        for mode in ("original", "app640"):
            if mode == "app640":
                resized = image.resize((640, max(1, math.floor(image.height * 640 / image.width + .5))), Image.Resampling.BILINEAR)
                payload = jpeg(resized)
                input_path = root / "inputs" / f"{sid}.jpg"
                input_path.parent.mkdir(parents=True, exist_ok=True)
                input_path.write_bytes(payload)
                picture = decode_image(payload)
            else:
                input_path, payload, picture = REPO / source, data, image
            started = time.perf_counter()
            detections = [row.as_dict() for row in service.detector.detect(picture, None)]
            report["frames"][f"{sid}_{mode}"] = dict(
                source=source, input_file=input_path.resolve().relative_to(REPO).as_posix(),
                input_sha256=hashlib.sha256(payload).hexdigest(), source_sha256=hashlib.sha256(data).hexdigest(),
                mode=mode, **group, detections=detections, label=labels.get(source), legacy=old,
                detect_seconds=time.perf_counter() - started)
        write(target, report)
    print(f"Заморожено {len(sources)} исходников × 2 режима; CLIP-фильтр ещё не запускался")


def verified_capture(root: Path, plan_path: Path) -> dict:
    data = read(root / "capture.json")
    plan = read(plan_path)
    if data["plan_sha256"] != digest(plan_path) or data["labels_sha256"] != digest(REPO / plan["quality_labels"]):
        raise ValueError("После заморозки изменены план или разметка")
    return data


def bank_vectors(plan: dict, identifier) -> np.ndarray:
    images = [decode_image(jpeg(crop(decode_image((REPO / row["file"]).read_bytes()), row["bbox"], 0)))
              for row in plan["bank"]]
    return identifier.embed(images)


def similarities(vectors: np.ndarray, bank: list[dict], queries: np.ndarray, kind: str) -> dict:
    values = vectors @ queries
    scores = {label: float(max(v for v, row in zip(values, bank) if row["cv_class"] == label))
              for label in (*CLASSES, "negative")}
    competitor = max((label for label in scores if label != kind), key=lambda label: scores[label])
    return dict(positive=scores[kind], competitor=scores[competitor], competitor_class=competitor,
                margin=scores[competitor] - scores[kind], similarities=scores,
                nearest_example=bank[int(np.argmax(values))]["id"])


def features(plan_path: Path, root: Path, phase: str) -> None:
    target = root / f"features_{phase}.json"
    if target.exists():
        raise SystemExit("Векторы этой группы уже сохранены; повторный контроль не выполняется")
    plan, _, _ = load_plan(plan_path)
    data = verified_capture(root, plan_path)
    if phase != "tune" and not (root / "frozen.json").is_file():
        raise SystemExit("Сначала выберите и заморозьте правило на tune")
    service = load_service()
    bank = bank_vectors(plan, service.identifier)
    output = dict(capture_sha256=digest(root / "capture.json"), plan_sha256=digest(plan_path), phase=phase, frames={})
    for name, frame in data["frames"].items():
        if frame["phase"] != phase:
            continue
        path = REPO / frame["input_file"]
        if digest(path) != frame["input_sha256"]:
            raise ValueError(f"Изменён замороженный кадр: {path}")
        image = decode_image(path.read_bytes())
        entries = {}
        for padding in plan["rules"]["padding"]:
            crops = [decode_image(jpeg(crop(image, row["bbox"], padding))) for row in frame["detections"]]
            started = time.perf_counter()
            vectors = np.concatenate([service.identifier.embed(crops[i:i + 16]) for i in range(0, len(crops), 16)]) if crops else []
            entries[str(padding)] = [similarities(bank, plan["bank"], vector, row["cv_class"])
                                     for vector, row in zip(vectors, frame["detections"])]
            entries[f"seconds_{padding}"] = time.perf_counter() - started
        output["frames"][name] = entries
    write(target, output)
    print(f"CLIP: {phase}, кадров {len(output['frames'])}; результаты контроля не выводятся до evaluate")


def keep_box(score: dict, rule: dict) -> bool:
    """Неуверенность — оставить OWLv2; сходство не заменяет его confidence."""
    return not (score["competitor"] >= rule["min_competitor"] and score["margin"] >= rule["margin"])


def compare(frame: dict, scores: list[dict], rule: dict) -> dict:
    original = frame["detections"]
    if len(original) != len(scores):
        raise ValueError("Ответы CLIP и OWLv2 имеют разную длину")
    indices = [i for i, value in enumerate(scores) if keep_box(value, rule)]
    filtered = [original[i] for i in indices]
    label = frame.get("label")
    before = score_frame(label, original) if label else None
    after = score_frame(label, filtered) if label else None
    decisions = {row["prediction"]: row for row in before["decisions"]} if before else {}
    removed = []
    for i, row in enumerate(original):
        if i in indices:
            continue
        possible = bool(label) and any(obj["cv_class"] == row["cv_class"] and iou(obj["bbox"], row["bbox"]) >= .1
                                       for obj in label["objects"])
        removed.append(dict(index=i, detection=row, clip=scores[i], status=decisions.get(i, {}).get("status", "unscored"),
                            possible_true=possible))
    return dict(before=before["metrics"] if before else None, after=after["metrics"] if after else None,
                detections=filtered, kept_indices=indices, removed=removed)


def checked_features(root: Path, phase: str) -> dict:
    data = read(root / f"features_{phase}.json")
    if data["capture_sha256"] != digest(root / "capture.json"):
        raise ValueError("Ответы детектора изменились после вычисления CLIP")
    return data["frames"]


def fit(plan_path: Path, root: Path) -> None:
    target = root / "frozen.json"
    if target.exists():
        raise SystemExit("Правило уже заморожено. Не подстраивать его после контроля")
    plan = read(plan_path)
    frames = verified_capture(root, plan_path)["frames"]
    vectors = checked_features(root, "tune")
    trials = []
    for padding in plan["rules"]["padding"]:
        for margin in plan["rules"]["margin"]:
            rule = dict(padding=padding, margin=margin, min_competitor=plan["rules"]["min_competitor"])
            removed_tp = removed_fp = possible_true = 0
            for name, frame in frames.items():
                if frame["phase"] != "tune":
                    continue
                result = compare(frame, vectors[name][str(padding)], rule)
                removed_tp += sum(row["status"] == "tp" for row in result["removed"])
                removed_fp += sum(row["status"] == "fp" for row in result["removed"])
                possible_true += sum(row["possible_true"] for row in result["removed"])
            trials.append(dict(rule=rule, removed_tp=removed_tp, removed_fp=removed_fp, possible_true=possible_true))
    valid = [trial for trial in trials if trial["removed_tp"] == 0 and trial["possible_true"] == 0]
    chosen = max(valid, key=lambda t: (t["removed_fp"], t["rule"]["margin"], -t["rule"]["padding"])) if valid else None
    write(target, dict(plan_sha256=digest(plan_path), capture_sha256=digest(root / "capture.json"),
                       tune_features_sha256=digest(root / "features_tune.json"), selected=chosen, trials=trials))
    print(json.dumps(dict(selected=chosen, trials=trials), ensure_ascii=False, indent=2))


def evaluate(plan_path: Path, root: Path) -> None:
    target = root / "evaluation.json"
    if target.exists():
        raise SystemExit("Контроль уже выполнен. Повторный подбор запрещён планом")
    data = verified_capture(root, plan_path)
    frozen = read(root / "frozen.json")
    if frozen["plan_sha256"] != digest(plan_path) or frozen["capture_sha256"] != digest(root / "capture.json"):
        raise ValueError("Замороженное правило не соответствует данным")
    if not frozen["selected"]:
        write(target, dict(decision="rejected_on_tune", frozen_sha256=digest(root / "frozen.json")))
        print("Нет безопасного правила на настройке; контроль не используется для нового подбора")
        return
    rule = frozen["selected"]["rule"]
    vectors = {phase: checked_features(root, phase) for phase in ("tune", "holdout", "regression")}
    output = dict(rule=rule, frozen_sha256=digest(root / "frozen.json"), frames={}, totals={})
    counts = {}
    for name, frame in data["frames"].items():
        if frame["phase"] == "bank":
            continue
        result = compare(frame, vectors[frame["phase"]][name][str(rule["padding"])], rule)
        output["frames"][name] = dict(source=frame["source"], mode=frame["mode"], phase=frame["phase"], **result)
        key = f"{frame['phase']}_{frame['mode']}"
        group = counts.setdefault(key, {side: {kind: [0, 0, 0] for kind in CLASSES} for side in ("before", "after")})
        if result["before"]:
            for side in ("before", "after"):
                for kind, values in result[side].items():
                    for i, field in enumerate(("tp", "fp", "fn")):
                        group[side][kind][i] += values[field]
    output["totals"] = {key: {side: {kind: metrics(*v) for kind, v in classes.items()} for side, classes in sides.items()}
                        for key, sides in counts.items()}
    holdout_removed = [row for frame in output["frames"].values() if frame["phase"] == "holdout" for row in frame["removed"]]
    output["holdout_removed_fp"] = sum(row["status"] == "fp" for row in holdout_removed)
    output["holdout_removed_tp"] = sum(row["status"] == "tp" for row in holdout_removed)
    output["holdout_removed_possible_true"] = sum(row["possible_true"] for row in holdout_removed)
    output["preliminary_pass"] = (output["holdout_removed_fp"] > 0 and output["holdout_removed_tp"] == 0
                                  and output["holdout_removed_possible_true"] == 0)
    write(target, output)
    print(json.dumps({key: value for key, value in output.items() if key != "frames"}, ensure_ascii=False, indent=2))


def contact(items: list[tuple[str, Image.Image]], path: Path, columns=4, width=350, height=290) -> None:
    canvas = Image.new("RGB", (columns * width, math.ceil(len(items) / columns) * height), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (title, image) in enumerate(items):
        image = image.copy()
        image.thumbnail((width - 6, height - 35))
        x, y = i % columns * width, i // columns * height
        canvas.paste(image, (x + 3, y + 30))
        draw.text((x + 3, y + 3), title, fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, quality=83)


def review(plan_path: Path, root: Path) -> None:
    plan = read(plan_path)
    data = verified_capture(root, plan_path)
    quality = read(REPO / plan["quality_labels"])["frames"]
    wanted = {v["file"]: name for name, v in quality.items()}
    wanted["docs/case/Запорная арматура/1396430378_7447321.jpg"] = "wrong_gauge"
    full, crops = [], []
    for name, frame in data["frames"].items():
        if frame["mode"] != "original" or frame["source"] not in wanted:
            continue
        title = wanted[frame["source"]]
        label = frame["label"]
        score = score_frame(label, frame["detections"])
        marked = root / "review_full" / f"{title}.jpg"
        draw_frame(dict(label, file=frame["source"]), frame["detections"], score, marked)
        full.append((f"{title} / {frame['phase']}", Image.open(marked).convert("RGB")))
        image = decode_image((REPO / frame["input_file"]).read_bytes())
        for i, row in enumerate(frame["detections"]):
            crops.append((f"{title} #{i} {row['cv_class']} {row['confidence']:.2f}", crop(image, row["bbox"], 0)))
    out = REPO / "demo/photos/quality/review"
    contact(full, out / "stage2-frames.jpg")
    for page in range(0, len(crops), 16):
        contact(crops[page:page + 16], out / f"stage2-crops-{page // 16 + 1}.jpg", width=300, height=250)
    bank = [(f"{row['id']} / {row['cv_class']}", crop(decode_image((REPO / row["file"]).read_bytes()), row["bbox"], 0))
            for row in plan["bank"]]
    contact(bank, out / "stage2-bank.jpg", columns=5, width=280, height=250)
    print(f"Контактные листы: {out}")


def live_filter(image: Image.Image, detections: list[dict], rule: dict, bank: np.ndarray,
                examples: list[dict], identifier) -> list[dict]:
    if not detections:
        return []
    pictures = [decode_image(jpeg(crop(image, row["bbox"], rule["padding"]))) for row in detections]
    queries = np.concatenate([identifier.embed(pictures[i:i + 16]) for i in range(0, len(pictures), 16)])
    return [row for row, vector in zip(detections, queries)
            if keep_box(similarities(bank, examples, vector, row["cv_class"]), rule)]


def distribution(values: list[float]) -> dict:
    return dict(samples=len(values), median_ms=statistics.median(values) * 1000,
                p95_ms=float(np.percentile(values, 95, method="linear")) * 1000,
                max_ms=max(values) * 1000)


def benchmark(plan_path: Path, root: Path, repeats: int) -> None:
    target = root / "benchmark.json"
    if target.exists():
        raise SystemExit("Замер уже сохранён; не перезаписывать первый результат")
    if repeats < 1:
        raise ValueError("Нужны положительные повторы")
    data = verified_capture(root, plan_path)
    plan = read(plan_path)
    frozen = read(root / "frozen.json")
    if not frozen["selected"]:
        raise SystemExit("Нет выбранного алгоритма для замера")
    rule = frozen["selected"]["rule"]
    service = load_service()
    bank = bank_vectors(plan, service.identifier)
    wanted = {"demo/photos/pump_unit_01.jpg", "demo/photos/pump_unit_drawing_01.jpg",
              "demo/reference/PU-001/case_pump_01.jpg", "demo/photos/motor_corrosion_01.jpg",
              "demo/photos/flange_corrosion_02.jpg", "docs/case/Запорная арматура/1396430378_7447321.jpg"}
    inputs = []
    for name, frame in data["frames"].items():
        if frame["mode"] == "app640" and frame["source"] in wanted:
            path = REPO / frame["input_file"]
            if digest(path) != frame["input_sha256"]:
                raise ValueError("Изменён вход замера")
            inputs.append((name, frame, decode_image(path.read_bytes())))
    if len(inputs) != len(wanted):
        raise ValueError("Неполный набор для задержки")
    import torch
    from app.main import _read_nvidia_smi
    def detect(image):
        return [row.as_dict() for row in service.detector.detect(image, None)]
    for _, frame, image in inputs:
        for _ in range(3):
            live_filter(image, detect(image), rule, bank, plan["bank"], service.identifier)
    torch.cuda.reset_peak_memory_stats()
    memory_before = _read_nvidia_smi()
    rows = []
    for repeat in range(repeats):
        for name, frame, image in inputs:
            times = {}
            # Чередуем порядок измерения, чтобы второй путь не получал постоянный прогрев.
            modes = ("detect_only", "detect_plus_filter", "filter_only") if repeat % 2 == 0 else (
                "filter_only", "detect_plus_filter", "detect_only")
            for mode in modes:
                torch.cuda.synchronize()
                started = time.perf_counter()
                if mode == "filter_only":
                    live_filter(image, frame["detections"], rule, bank, plan["bank"], service.identifier)
                else:
                    boxes = detect(image)
                    if mode == "detect_plus_filter":
                        live_filter(image, boxes, rule, bank, plan["bank"], service.identifier)
                torch.cuda.synchronize()
                times[mode] = time.perf_counter() - started
            rows.append(dict(frame=name, source=frame["source"], repeat=repeat, seconds=times))
    stats = {mode: distribution([row["seconds"][mode] for row in rows])
             for mode in ("detect_only", "detect_plus_filter", "filter_only")}
    output = dict(rule=rule, repeats=repeats, warmup_per_frame=3, frames=len(inputs), stats=stats,
                  health=service.health(), memory_smi_before=memory_before, memory_smi_after=_read_nvidia_smi(),
                  torch_peak_allocated_mb=torch.cuda.max_memory_allocated() / 2**20,
                  torch_peak_reserved_mb=torch.cuda.max_memory_reserved() / 2**20, measurements=rows,
                  note="Внутрипроцессный замер на ПК Тимофея; не HTTP/телефон/звонок. Новые detect только для времени, не для повторной оценки контроля.")
    write(target, output)
    print(json.dumps({key: value for key, value in output.items() if key != "measurements"}, ensure_ascii=False, indent=2))


def removal_review(plan_path: Path, root: Path) -> None:
    capture = verified_capture(root, plan_path)["frames"]
    report = read(root / "evaluation.json")
    pictures = []
    for name, result in report.get("frames", {}).items():
        frame = capture[name]
        image = decode_image((REPO / frame["input_file"]).read_bytes())
        for removed in result["removed"]:
            row = removed["detection"]
            title = f'{name[:6]} {frame["mode"]} {row["cv_class"]} {removed["status"]}'
            pictures.append((title, crop(image, row["bbox"], 0)))
    for page in range(0, len(pictures), 16):
        contact(pictures[page:page + 16], REPO / f"demo/photos/quality/review/stage2-removed-{page // 16 + 1}.jpg",
                width=300, height=250)
    print(f"Удалённых рамок для просмотра: {len(pictures)}")


def summarize(plan_path: Path, root: Path) -> None:
    from collections import Counter
    data = verified_capture(root, plan_path)
    result = read(root / "evaluation.json")
    timing = read(root / "benchmark.json")
    frozen = read(root / "frozen.json")
    if result["frozen_sha256"] != digest(root / "frozen.json"):
        raise ValueError("Правило изменено после контроля")
    removed, legacy_counts, protected, trace = [], {}, {}, {}
    vectors = {phase: checked_features(root, phase) for phase in ("tune", "holdout", "regression")}
    protect = {"demo/photos/pump_unit_drawing_01.jpg", "demo/photos/pump_unit_01.jpg",
               "demo/reference/PU-001/case_pump_01.jpg"}
    for name, evaluated in result["frames"].items():
        frame = data["frames"][name]
        scores = vectors[frame["phase"]][name][str(result["rule"]["padding"])]
        if len(scores) != len(frame["detections"]):
            raise ValueError("Неполный список сходств для трассировки")
        trace[name] = dict(source=frame["source"], mode=frame["mode"], phase=frame["phase"], predictions=[
            dict(index=i, detection=detection, clip=scores[i], keep=i in evaluated["kept_indices"],
                 reason="insufficient_contradiction" if i in evaluated["kept_indices"] else "clear_contradiction")
            for i, detection in enumerate(frame["detections"])])
        for row in evaluated["removed"]:
            removed.append(dict(frame=name, source=frame["source"], phase=frame["phase"], mode=frame["mode"],
                                index=row["index"], bbox=row["detection"]["bbox"], cv_class=row["detection"]["cv_class"],
                                confidence=row["detection"]["confidence"], status=row["status"], possible_true=row["possible_true"],
                                clip_positive=row["clip"]["positive"], clip_competitor=row["clip"]["competitor"],
                                clip_margin=row["clip"]["margin"], nearest_example=row["clip"]["nearest_example"]))
        if frame["source"] in protect:
            protected[name] = dict(source=frame["source"], mode=frame["mode"],
                                   before=dict(Counter(row["cv_class"] for row in frame["detections"])),
                                   after=dict(Counter(row["cv_class"] for row in evaluated["detections"])))
        if frame["legacy"] is None:
            continue
        mode = frame["mode"]
        counter = legacy_counts.setdefault(mode, dict(photos=0, before={c: [0, 0, 0] for c in CLASSES},
                                                     after={c: [0, 0, 0] for c in CLASSES}))
        counter["photos"] += 1
        for side, boxes in (("before", frame["detections"]), ("after", evaluated["detections"])):
            counts = Counter(row["cv_class"] for row in boxes)
            for kind in CLASSES:
                if kind in frame["legacy"].get("skip", []):
                    continue
                want, got = frame["legacy"]["nodes"].get(kind, 0), counts[kind]
                counter[side][kind][0] += min(want, got)
                counter[side][kind][1] += max(0, got - want)
                counter[side][kind][2] += max(0, want - got)
    for mode in legacy_counts.values():
        for side in ("before", "after"):
            mode[side] = {kind: dict(found_by_count=v[0], excess_by_count=v[1], missing_by_count=v[2])
                          for kind, v in mode[side].items()}
    lost_tp = sum(row["status"] == "tp" for row in removed)
    possible_true = sum(row["possible_true"] for row in removed)
    decision = "rejected" if not result["preliminary_pass"] or lost_tp or possible_true else "preliminary_only"
    # Трассировка соединяет уже сохранённые ответы, без повторной оценки контроля или моделей.
    write(root / "decisions.json", dict(rule=result["rule"], frames=trace))
    summary = dict(decision=decision, baseline_head=data["head"],
                   plan_sha256=data["plan_sha256"], labels_sha256=data["labels_sha256"],
                   capture_sha256=digest(root / "capture.json"), frozen_sha256=result["frozen_sha256"],
                   evaluation_sha256=digest(root / "evaluation.json"), tuning=frozen,
                   decisions_sha256=digest(root / "decisions.json"),
                   source_phases=dict(Counter(row["phase"] for row in data["frames"].values() if row["mode"] == "original")),
                   metrics=result["totals"], holdout_removed_fp=result["holdout_removed_fp"],
                   holdout_removed_tp=result["holdout_removed_tp"], holdout_removed_possible_true=result["holdout_removed_possible_true"],
                   protected=protected, removed=removed, legacy_count_only=legacy_counts,
                   timing={key: value for key, value in timing.items() if key != "measurements"},
                   limitations=read(plan_path)["limitations"])
    if (root / "tests.xml").is_file():
        import xml.etree.ElementTree as ET
        suites = ET.parse(root / "tests.xml").getroot().iter("testsuite")
        counts = {field: 0 for field in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for field in counts:
                counts[field] += int(suite.get(field, 0))
        counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        summary["tests"] = counts
    write(root / "summary.json", summary)
    print(f"Итог: {summary['decision']}; FP контроля удалено {summary['holdout_removed_fp']}, TP потеряно {summary['holdout_removed_tp']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["capture", "features", "fit", "evaluate", "review", "removal-review", "benchmark", "summarize"])
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--root", type=Path, default=REPO / "runs/stage2")
    parser.add_argument("--phase", choices=["tune", "holdout", "regression"])
    parser.add_argument("--repeats", type=int, default=20, help="число повторов каждого входа при benchmark")
    args = parser.parse_args()
    if args.action == "features":
        if not args.phase:
            parser.error("features требует --phase")
        features(args.plan, args.root, args.phase)
    elif args.action == "benchmark":
        benchmark(args.plan, args.root, args.repeats)
    else:
        {"capture": capture, "fit": fit, "evaluate": evaluate, "review": review,
         "removal-review": removal_review, "summarize": summarize}[args.action](args.plan, args.root)


if __name__ == "__main__":
    main()
