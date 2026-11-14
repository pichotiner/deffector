import json
from pathlib import Path

import pytest

from tools.evaluate_boxes import CLASSES, iou, metrics, saved_predictions, score_frame, validate_box
from tools.quality_check import crop_pixels


def obj(box, kind="electric_motor", confidence=None):
    result = dict(bbox=box, cv_class=kind)
    if confidence is not None:
        result["confidence"] = confidence
    return result


def frame(truth=(), ignore=(), scope=CLASSES):
    return dict(objects=list(truth), ignore_regions=list(ignore), evaluated_classes=list(scope))


def pred(box=(.1, .1, .2, .2), kind="electric_motor", confidence=.8):
    return obj(list(box), kind, confidence)


def test_iou_identity_and_nonoverlap():
    assert iou([0, 0, .5, .5], [0, 0, .5, .5]) == 1
    assert iou([0, 0, .2, .2], [.5, .5, .2, .2]) == 0


def test_correct_box():
    result = score_frame(frame([pred()]), [pred()])
    assert result["metrics"]["electric_motor"] == metrics(1, 0, 0)


def test_correct_count_wrong_location_is_not_a_hit():
    result = score_frame(frame([pred()]), [pred((.7, .7, .2, .2))])
    assert result["metrics"]["electric_motor"] == metrics(0, 1, 1)


def test_wrong_class():
    result = score_frame(frame([pred()]), [pred(kind="valve")])
    assert result["metrics"]["electric_motor"] == metrics(0, 0, 1)
    assert result["metrics"]["valve"] == metrics(0, 1, 0)


def test_duplicate_box_is_false_positive_and_confidence_orders_matching():
    result = score_frame(frame([pred()]), [pred(confidence=.3), pred(confidence=.9)])
    assert result["metrics"]["electric_motor"] == metrics(1, 1, 0)
    assert result["decisions"][0]["prediction"] == 1


def test_missing_box():
    result = score_frame(frame([pred()]), [])
    assert result["missing"] == [0]
    assert result["metrics"]["electric_motor"] == metrics(0, 0, 1)


def test_ties_use_input_indices_for_predictions_and_targets():
    result = score_frame(frame([pred(), pred()]), [pred(), pred()])
    assert [d["target"] for d in result["decisions"]] == [0, 1]


def test_iou_threshold_inclusive():
    # Эталон вдвое шире предсказания, IoU ровно 0,5.
    result = score_frame(frame([pred((0, 0, .4, .2))]), [pred((0, 0, .2, .2))])
    assert result["metrics"]["electric_motor"]["tp"] == 1


def test_ignored_region_does_not_give_true_positive():
    result = score_frame(frame(ignore=[pred()]), [pred()])
    assert result["decisions"][0]["status"] == "ignored_region"
    assert result["metrics"]["electric_motor"] == metrics(0, 0, 0)


def test_ignore_region_is_class_specific_and_requires_half_prediction_area():
    result = score_frame(frame(ignore=[pred(kind="valve")]), [pred()])
    assert result["metrics"]["electric_motor"]["fp"] == 1
    result = score_frame(frame(ignore=[pred((.1, .1, .05, .05))]), [pred()])
    assert result["metrics"]["electric_motor"]["fp"] == 1


def test_target_matching_precedes_ignoring():
    result = score_frame(frame([pred()], [pred()]), [pred()])
    assert result["metrics"]["electric_motor"]["tp"] == 1


def test_unannotated_class_is_not_background():
    result = score_frame(frame(scope=["valve"]), [pred()])
    assert result["decisions"][0]["status"] == "unscored_class"
    assert result["metrics"]["electric_motor"] == metrics(0, 0, 0)


def test_zero_denominator_is_not_perfect_accuracy():
    assert metrics(0, 0, 0)["precision"] is None
    assert metrics(0, 0, 1)["recall"] == 0
    assert metrics(0, 1, 0)["recall"] is None


@pytest.mark.parametrize("box", [[0, 0, 0, 1], [0, 0, float("nan"), 1], [True, 0, 1, 1],
                                 [0, 0, 2, 1], [-1, 0, 1, 1], [0, 0, 1]])
def test_invalid_coordinates_fail_loudly(box):
    with pytest.raises(ValueError):
        validate_box(box)


def test_crop_matches_mobile_geometry():
    assert crop_pixels([.2, .2, .2, .2], 1000, 1000) == (170, 170, 430, 430)
    assert crop_pixels([0, 0, 1, 1], 1000, 800) == (0, 0, 1000, 800)
    assert crop_pixels([.99, .99, .2, .2], 100, 100) == (98, 98, 100, 100)


def test_dataset_paths_scope_and_group_separation():
    root = Path(__file__).resolve().parents[2]
    labels = json.loads((root / "demo/photos/quality/labels.json").read_text(encoding="utf-8"))
    groups = {}
    for spec in labels["frames"].values():
        assert (root / spec["file"]).is_file()
        assert groups.setdefault(spec["group"], spec["split"]) == spec["split"]
        assert spec["split"] in {"tune", "control"}
        score_frame(spec, [])


@pytest.mark.parametrize("threshold", [0, -1, 1.1, float("nan")])
def test_invalid_iou_threshold(threshold):
    with pytest.raises(ValueError):
        score_frame(frame(), [], threshold)


def test_saved_old_count_report_remains_readable(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"image.jpg": {"detections": [pred()]}}), encoding="utf-8")
    assert saved_predictions(path, tmp_path) == {(tmp_path / "image.jpg").resolve(): [pred()]}


def test_saved_show_report_remains_readable(tmp_path):
    path = tmp_path / "show.json"
    photo = tmp_path / "image.jpg"
    path.write_text(json.dumps([{"file": str(photo), "boxes": [pred()]}]), encoding="utf-8")
    assert saved_predictions(path, tmp_path) == {photo.resolve(): [pred()]}


def test_saved_own_report_remains_readable(tmp_path):
    root = Path(__file__).resolve().parents[2]
    path = tmp_path / "new.json"
    path.write_text(json.dumps({"frames": {"image": {"file": "demo/photos/motor_corrosion_01.jpg",
                                                   "detections": [pred()]}}}), encoding="utf-8")
    assert saved_predictions(path, tmp_path) == {(root / "demo/photos/motor_corrosion_01.jpg").resolve(): [pred()]}
