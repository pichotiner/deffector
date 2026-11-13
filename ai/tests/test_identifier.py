from app.identifier import rank_candidates

PARAMS = dict(threshold=0.78, top_k=3, temperature=0.03)


def test_clear_match():
    recognized, candidates = rank_candidates({"PU-001": [0.93, 0.9, 0.88, 0.6], "CC-001": [0.55, 0.5]}, **PARAMS)
    assert recognized
    assert [c["equipment_id"] for c in candidates] == ["PU-001", "CC-001"]
    assert candidates[0]["confidence"] > 0.9
    assert candidates[1]["confidence"] < 0.05


def test_foreign_object_not_recognized_and_low_confidence():
    recognized, candidates = rank_candidates({"PU-001": [0.52, 0.5], "CC-001": [0.48, 0.4]}, **PARAMS)
    assert not recognized
    assert all(c["confidence"] < 0.05 for c in candidates)


def test_below_threshold_not_recognized():
    recognized, candidates = rank_candidates({"PU-001": [0.75, 0.74, 0.7], "CC-001": [0.5]}, **PARAMS)
    assert not recognized
    assert candidates[0]["equipment_id"] == "PU-001"
    assert 0 < candidates[0]["confidence"] < 0.6


def test_ambiguous_split_confidence():
    recognized, candidates = rank_candidates({"PU-001": [0.9], "CC-001": [0.9]}, **PARAMS)
    assert recognized
    assert candidates[0]["confidence"] == candidates[1]["confidence"] == 0.5


def test_no_references():
    assert rank_candidates({}, **PARAMS) == (False, [])
    assert rank_candidates({"PU-001": []}, **PARAMS) == (False, [])
