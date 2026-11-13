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
        {"signs": ["vibration"]},
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
        "Повреждений нет, состояние хорошее.",
        "Проблем нет.",
        "Никаких дефектов.",
        "Не обнаружено дефектов.",
        "Узел пригоден к эксплуатации.",
        "Двигатель работает нормально.",
        "Нормальное состояние.",
        "В удовлетворительном состоянии.",
        "Параметры в пределах нормы.",
        "Допускается к эксплуатации.",
        "Можно продолжать эксплуатацию.",
        "Утечек нет, всё герметично.",
        "Подшипник изношен.",
        "Признаки кавитации.",
        "Дисбаланс ротора.",
        "Обмотка статора повреждена.",
        "Следует заменить задвижку.",
        "Рекомендуется замена.",
        "Нужен ремонт.",
        "Повреждения отсутствуют.",
        "Повреждений не видно.",
        "Состояние хорошее.",
        "Работает штатно.",
        "Корпус целый, герметичен.",
        "Ротор задевает статор.",
        "Короткое замыкание.",
        "Обнаружен дефект: трещина.",
        "Нужно поменять прокладку.",
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
        "Видна ржавчина у основания корпуса.",
        "Осмотреть место повреждения и проверить целостность корпуса.",
        "Снимок смазан, детали не видны.",
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
    result = check(explanation="Rust spots на корпусе are visible, see photo.")
    assert "коррозия" in result.explanation


def test_long_text_cut_to_two_sentences():
    result = check(explanation="Видна ржавчина. Она на корпусе. Она рыжая. Её много.")
    assert result.explanation == "Видна ржавчина. Она на корпусе."


def test_no_issues_texts_are_templates():
    # свободный текст модели при «видимых проблем не обнаружено» не показываем:
    # он может звучать как подтверждение исправности (ТЗ 4.2)
    result = check(category="no_visible_issues", signs=[], explanation="Узел годится, всё хорошо.",
                   recommendation="Ничего делать не нужно.")
    assert result.category == "no_visible_issues"
    assert result.recommendation == rules.template_recommendation("no_visible_issues", [])
    assert result.explanation == rules.template_explanation("no_visible_issues", [], "Манометр")


def test_dropped_sign_never_gives_no_issues():
    raw = rules.parse_model_answer(answer(signs=["overheating"], category="no_visible_issues",
                                          explanation="Видны бурые пятна у фланца."))
    result = rules.enforce(raw, "Задвижка", "valve")
    assert result.category == "check_recommended" and result.signs == []


def test_dropped_sign_texts_follow_kept_signs():
    raw = rules.parse_model_answer(answer(signs=["corrosion", "overheating"], category="possible_defect",
                                          explanation="Ржавчина и потемнение краски.",
                                          recommendation="Проверить нагрев корпуса."))
    result = rules.enforce(raw, "Задвижка", "valve")
    assert result.signs == ["коррозия"] and result.category == "possible_defect"
    assert result.recommendation == rules.template_recommendation("possible_defect", ["коррозия"])


def test_non_string_sign_is_format_error():
    with pytest.raises(rules.FormatError):
        rules.parse_model_answer(answer(signs=[{"code": "corrosion"}]))


def test_overheating_only_for_motor():
    raw = rules.parse_model_answer(answer(signs=["overheating"], category="possible_defect"))
    motor = rules.enforce(raw, "Электродвигатель", "electric_motor")
    assert motor.signs == ["следы перегрева"] and motor.category == "possible_defect"
    assert "клеммной коробки" in rules.template_recommendation("possible_defect", motor.signs)
    valve = rules.enforce(raw, "Задвижка", "valve")
    assert valve.signs == [] and valve.category == "check_recommended"


def test_allowed_signs():
    assert "overheating" in rules.allowed_signs("electric_motor")
    assert "overheating" not in rules.allowed_signs("flange")
    assert rules.allowed_signs("flange") == ["corrosion", "leak", "mechanical_damage"]
