from app.detector import Box, clip_box, iou, suppress_duplicates


def box(x, y, w, h, cls="valve", conf=0.5):
    return Box(x, y, w, h, cls, conf)


def test_iou():
    assert iou(box(0, 0, 0.2, 0.2), box(0, 0, 0.2, 0.2)) == 1.0
    assert iou(box(0, 0, 0.2, 0.2), box(0.5, 0.5, 0.2, 0.2)) == 0.0
    assert abs(iou(box(0, 0, 0.2, 0.2), box(0.1, 0, 0.2, 0.2)) - 1 / 3) < 1e-6


def test_same_node_two_prompts_keeps_best():
    kept = suppress_duplicates([box(0.1, 0.1, 0.2, 0.2, conf=0.4), box(0.11, 0.1, 0.2, 0.21, conf=0.7)])
    assert len(kept) == 1 and kept[0].confidence == 0.7


def test_nested_box_of_same_class_removed():
    kept = suppress_duplicates([box(0.1, 0.1, 0.4, 0.4, conf=0.6), box(0.2, 0.2, 0.1, 0.1, conf=0.5)])
    assert len(kept) == 1 and kept[0].w == 0.4


def test_two_separate_flanges_kept():
    kept = suppress_duplicates([box(0.1, 0.4, 0.1, 0.2, "flange", 0.6), box(0.6, 0.4, 0.1, 0.2, "flange", 0.5)])
    assert len(kept) == 2


def test_same_place_different_class_keeps_best():
    kept = suppress_duplicates([box(0.1, 0.1, 0.2, 0.2, "valve", 0.4), box(0.1, 0.1, 0.2, 0.2, "flange", 0.6)])
    assert [b.cv_class for b in kept] == ["flange"]


def test_gauge_on_motor_kept():
    # манометр внутри рамки двигателя — разные типы, оба остаются
    kept = suppress_duplicates(
        [box(0.1, 0.1, 0.6, 0.6, "electric_motor", 0.8), box(0.3, 0.2, 0.1, 0.1, "pressure_gauge", 0.5)]
    )
    assert len(kept) == 2


def test_sorted_by_confidence():
    kept = suppress_duplicates([box(0, 0, 0.1, 0.1, conf=0.3), box(0.5, 0.5, 0.1, 0.1, conf=0.9)])
    assert [b.confidence for b in kept] == [0.9, 0.3]


def test_clip_box():
    assert clip_box(-0.1, 0.2, 0.5, 1.3) == (0.0, 0.2, 0.5, 0.8)
    assert clip_box(0.5, 0.5, 0.501, 0.9) is None


def test_as_dict_matches_contract():
    assert box(0.41, 0.22, 0.12, 0.18, "pressure_gauge", 0.8712).as_dict() == {
        "bbox": [0.41, 0.22, 0.12, 0.18],
        "cv_class": "pressure_gauge",
        "confidence": 0.871,
    }
