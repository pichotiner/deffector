from app.identifier import rank_candidates

PARAMS = dict(threshold=0.78, top_k=3, temperature=0.03)


def test_clear_match():
    recognized, candidates = rank_candidates({"PU-001": [0.93, 0.9, 0.88, 0.6], "PU-002": [0.55, 0.5]}, **PARAMS)
    assert recognized
    assert [c["equipment_id"] for c in candidates] == ["PU-001", "PU-002"]
    assert candidates[0]["confidence"] > 0.9
    assert candidates[1]["confidence"] < 0.05


def test_foreign_object_not_recognized_and_low_confidence():
    recognized, candidates = rank_candidates({"PU-001": [0.52, 0.5], "PU-002": [0.48, 0.4]}, **PARAMS)
    assert not recognized
    assert all(c["confidence"] < 0.05 for c in candidates)


def test_below_threshold_not_recognized():
    recognized, candidates = rank_candidates({"PU-001": [0.75, 0.74, 0.7], "PU-002": [0.5]}, **PARAMS)
    assert not recognized
    assert candidates[0]["equipment_id"] == "PU-001"
    assert 0 < candidates[0]["confidence"] < 0.6


def test_ambiguous_split_confidence():
    recognized, candidates = rank_candidates({"PU-001": [0.95], "PU-002": [0.95]}, **PARAMS)
    assert recognized
    assert candidates[0]["confidence"] == candidates[1]["confidence"] == 0.5


def test_no_references():
    assert rank_candidates({}, **PARAMS) == (False, [])
    assert rank_candidates({"PU-001": []}, **PARAMS) == (False, [])


def test_below_threshold_confidence_under_half():
    # бэкенд считает «распознано» по уверенности >= 0.5: ниже порога её быть не должно
    for top in (0.6, 0.7, 0.77, 0.779):
        recognized, candidates = rank_candidates({"PU-001": [top], "PU-002": [0.3]}, **PARAMS)
        assert not recognized and candidates[0]["confidence"] < 0.5
    # ровно на пороге уверенность чуть ниже 0.5 (бэкенд осторожнее), чуть выше порога — уже >= 0.5
    recognized, candidates = rank_candidates({"PU-001": [0.79], "PU-002": [0.3]}, **PARAMS)
    assert recognized and candidates[0]["confidence"] >= 0.5
