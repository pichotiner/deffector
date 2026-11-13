import pytest

from app import rules


def answer(**overrides):
    base = {
        "image_quality": "ok",
        "signs": ["corrosion"],
        "category": "possible_defect",
        "explanation": "На корпусе видны рыжие пятна ржавчины.",
        "recommendation": "Осмотреть корпус и оценить глубину коррозии.",
        "assessment_confidence": 0.8,
    }
    base.update(overrides)
    return base


def check(**overrides):
    return rules.enforce(rules.parse_model_answer(answer(**overrides)), "Манометр")


def test_valid_answer_kept():
    result = check()
    assert result.category == "possible_defect"
    assert result.signs == ["коррозия"]
    assert result.explanation == "На корпусе видны рыжие пятна ржавчины."
    assert result.image_quality == "ok"


@pytest.mark.parametrize(
    "broken",
    [
        {"category": "broken"},
        {"category": None},
        {"image_quality": "bad"},
        {"signs": ["overheating"]},
        {"signs": "corrosion"},
        {"assessment_confidence": "высокая"},
        {"assessment_confidence": True},
        {"explanation": None},
    ],
)
def test_format_errors(broken):
    with pytest.raises(rules.FormatError):
        rules.parse_model_answer(answer(**broken))


def test_missing_field_is_format_error():
    raw = answer()
    del raw["recommendation"]
    with pytest.raises(rules.FormatError):
        rules.parse_model_answer(raw)


def test_poor_image_never_no_visible_issues():
    result = check(image_quality="poor", category="no_visible_issues", signs=[])
    assert result.category == "check_recommended"
    assert result.image_quality == "poor"
    assert "оценить" in result.explanation
    assert result.signs == []


def test_poor_image_overrides_defect():
    result = check(image_quality="poor", category="possible_defect")
    assert result.category == "check_recommended"
    assert result.image_quality == "poor"


def test_no_issues_with_signs_becomes_check():
    result = check(category="no_visible_issues", signs=["leak"])
    assert result.category == "check_recommended"
    assert result.signs == ["течь/подтёки"]
    assert "течь/подтёки" in result.explanation


def test_defect_without_signs_becomes_check():
    assert check(category="possible_defect", signs=[]).category == "check_recommended"


def test_confidence_clamped():
    assert check(assessment_confidence=7).assessment_confidence == 1.0
    assert check(assessment_confidence=-1).assessment_confidence == 0.0


def test_duplicate_signs_removed():
    assert check(signs=["leak", "leak", "corrosion"]).signs == ["течь/подтёки", "коррозия"]


@pytest.mark.parametrize(
    "text",
    [
        "Манометр исправен.",
        "Узел в порядке, замечаний нет.",
        "Дефектов нет.",
        "Дефекты не обнаружены.",
        "Нет видимых дефектов на корпусе.",
        "Узел в хорошем состоянии.",
        "Оборудование работоспособно.",
        "Вероятно, внутренняя неисправность подшипника.",
        "Диагноз: износ уплотнения.",
        "Показания в норме.",
        "Требуется замена манометра.",
        "Двигатель вышел из строя.",
    ],
)
def test_forbidden_wording_replaced(text):
    assert rules.has_forbidden(text)
    result = check(category="no_visible_issues", signs=[], explanation=text)
    assert not rules.has_forbidden(result.explanation)
    assert "видимых проблем не обнаружено" in result.explanation
    result = check(recommendation=text)
    assert not rules.has_forbidden(result.recommendation)


@pytest.mark.parametrize(
    "text",
    [
        "На корпусе видны рыжие пятна, похожие на коррозию.",
        "Под фланцем видны тёмные подтёки.",
        "Видимых проблем не обнаружено.",
        "Проверить герметичность соединений.",
    ],
)
def test_allowed_wording(text):
    assert not rules.has_forbidden(text)


def test_templates_are_clean():
    for category in rules.CATEGORIES:
        for signs in ([], ["коррозия"], list(rules.SIGNS.values())):
            assert not rules.has_forbidden(rules.template_explanation(category, signs, "Задвижка"))
            assert not rules.has_forbidden(rules.template_recommendation(category, signs))
    for result in (rules.poor_quality("снимок смазан"), rules.analysis_failed()):
        assert result.category == "check_recommended"
        assert not rules.has_forbidden(result.explanation + " " + result.recommendation)


def test_non_russian_text_replaced():
    result = check(explanation="Rust spots are visible on the housing.")
    assert "коррозия" in result.explanation


def test_long_text_cut_to_two_sentences():
    result = check(explanation="Видна ржавчина. Она на корпусе. Она рыжая. Её много.")
    assert result.explanation == "Видна ржавчина. Она на корпусе."


def test_no_issues_recommendation_is_template():
    result = check(category="no_visible_issues", signs=[], explanation="Корпус чистый, стекло целое.",
                   recommendation="Ничего делать не нужно.")
    assert result.recommendation == rules.template_recommendation("no_visible_issues", [])
    assert result.explanation == "Корпус чистый, стекло целое."
