import copy
import json

import numpy as np
import pytest
from PIL import Image

from tools import clip_filter_experiment as experiment


RULE = {"padding": 0.0, "margin": .06, "min_competitor": .65}


def box(kind="electric_motor", confidence=.31):
    return {"bbox": [.1, .1, .2, .2], "cv_class": kind, "confidence": confidence}


def score(positive=.7, competitor=.8):
    return {"positive": positive, "competitor": competitor, "margin": competitor - positive}


@pytest.mark.parametrize("positive,competitor,kept", [(.7, .8, False), (.7, .74, True),
                                                      (.1, .3, True), (.8, .7, True)])
def test_only_clear_contradiction_rejects(positive, competitor, kept):
    assert experiment.keep_box(score(positive, competitor), RULE) is kept


def test_borderline_margin_is_inclusive():
    assert not experiment.keep_box({"competitor": .65, "margin": .06}, RULE)
    assert experiment.keep_box({"competitor": .649, "margin": .06}, RULE)


def test_uncertain_numeric_result_keeps_original():
    assert experiment.keep_box({"competitor": float("nan"), "margin": float("nan")}, RULE)


def test_filter_preserves_bbox_class_confidence_and_order():
    frame = {"detections": [box(), box("pressure_gauge", .9), box("flange", .32)], "label": None}
    original = copy.deepcopy(frame)
    result = experiment.compare(frame, [score(.8, .7), score(.7, .9), score(.8, .8)], RULE)
    assert result["detections"] == [frame["detections"][0], frame["detections"][2]]
    assert result["kept_indices"] == [0, 2]
    assert frame == original


def test_empty_detections():
    result = experiment.compare({"detections": [], "label": None}, [], RULE)
    assert result["detections"] == [] and result["removed"] == []


def test_misaligned_features_are_not_silently_zipped():
    with pytest.raises(ValueError, match="разную длину"):
        experiment.compare({"detections": [box()]}, [], RULE)


def test_removed_true_and_loose_potential_true_are_reported():
    label = {"evaluated_classes": ["electric_motor"], "objects": [box()]}
    result = experiment.compare({"detections": [box()], "label": label}, [score(.5, .8)], RULE)
    assert result["removed"][0]["status"] == "tp"
    assert result["removed"][0]["possible_true"]
    assert result["after"]["electric_motor"]["fn"] == 1


def test_visual_similarity_is_not_detector_confidence():
    kinds = [*experiment.CLASSES, "negative"]
    bank = [{"cv_class": kind, "id": kind} for kind in kinds]
    embedding = np.array([.6, 0, 0, .8, 0])
    values = experiment.similarities(np.eye(5), bank, embedding, "electric_motor")
    assert values["positive"] == .6 and values["competitor"] == .8
    assert values["competitor_class"] == "flange" and values["nearest_example"] == "flange"


def test_default_plan_bank_and_test_sources_do_not_overlap():
    plan, groups, labels = experiment.load_plan(experiment.DEFAULT_PLAN)
    assert len(plan["bank"]) == 10
    assert all(groups[item["file"]]["phase"] == "bank" for item in plan["bank"])
    protected = {"demo/photos/pump_unit_01.jpg", "demo/photos/pump_unit_drawing_01.jpg",
                 "demo/reference/PU-001/case_pump_01.jpg"}
    assert not protected & {item["file"] for item in plan["bank"]}
    assert len(labels) >= 16


def test_duplicate_source_group_is_rejected(tmp_path):
    plan = experiment.read(experiment.DEFAULT_PLAN)
    plan["groups"].append(plan["groups"][0])
    path = tmp_path / "plan.json"
    experiment.write(path, plan)
    with pytest.raises(ValueError, match="Повторная группа"):
        experiment.load_plan(path)


def test_bank_mislabeled_as_control_is_rejected(tmp_path):
    plan = experiment.read(experiment.DEFAULT_PLAN)
    plan["groups"][0]["phase"] = "holdout"
    path = tmp_path / "plan.json"
    experiment.write(path, plan)
    with pytest.raises(ValueError, match="пересекается"):
        experiment.load_plan(path)


def test_crop_padding_and_edges():
    image = Image.new("RGB", (1000, 1000))
    assert experiment.crop(image, [.2, .2, .2, .2], .0).size == (200, 200)
    assert experiment.crop(image, [.2, .2, .2, .2], .15).size == (260, 260)
    assert experiment.crop(image, [0, 0, 1, 1], .15).size == image.size


def test_fit_never_reads_control_and_writes_once(tmp_path, monkeypatch):
    frame = {"phase": "tune", "detections": [box("flange")],
             "label": {"evaluated_classes": list(experiment.CLASSES), "objects": []}}
    frames = {"tune": frame, "control": {"phase": "holdout"}}
    monkeypatch.setattr(experiment, "verified_capture", lambda *_: {"frames": frames})
    monkeypatch.setattr(experiment, "checked_features", lambda root, phase: {
        "tune": {"0.0": [score(.7, .8)], "0.15": [score(.7, .8)]}} if phase == "tune" else pytest.fail("Прочитан контроль"))
    experiment.write(tmp_path / "capture.json", {})
    experiment.write(tmp_path / "features_tune.json", {})
    experiment.fit(experiment.DEFAULT_PLAN, tmp_path)
    chosen = experiment.read(tmp_path / "frozen.json")["selected"]
    assert chosen["removed_tp"] == 0 and chosen["rule"]["padding"] == 0
    with pytest.raises(SystemExit, match="уже заморожено"):
        experiment.fit(experiment.DEFAULT_PLAN, tmp_path)
