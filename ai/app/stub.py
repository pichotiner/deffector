"""Режим заглушки: ответы-примеры без моделей.

Нужен для разработки бэкенда на ПК без видеокарты. Ответы постоянные и подобраны так,
чтобы на стороне бэкенда сработала каждая ветка сведения результатов.
"""
from __future__ import annotations

from . import rules

# Насосный агрегат: по одному узлу каждого типа, фланцев два (проверка порядка слева направо).
STUB_DETECTIONS = [
    {"bbox": [0.08, 0.30, 0.34, 0.42], "cv_class": "electric_motor", "confidence": 0.91},
    {"bbox": [0.41, 0.22, 0.12, 0.18], "cv_class": "pressure_gauge", "confidence": 0.87},
    {"bbox": [0.62, 0.40, 0.14, 0.22], "cv_class": "valve", "confidence": 0.78},
    {"bbox": [0.48, 0.52, 0.09, 0.16], "cv_class": "flange", "confidence": 0.66},
    {"bbox": [0.80, 0.50, 0.09, 0.17], "cv_class": "flange", "confidence": 0.58},
]


def detect(classes: list[str] | None) -> list[dict]:
    if classes is None:
        return [dict(d) for d in STUB_DETECTIONS]
    return [dict(d) for d in STUB_DETECTIONS if d["cv_class"] in classes]


def analyze(component_type: str, component_name: str) -> dict:
    """Категория зависит от типа узла — так бэкенд может проверить все варианты ответа."""
    name = component_name.strip() or "узел"
    if component_type == "pressure_gauge":
        result = rules.Assessment(
            category=rules.CHECK_RECOMMENDED,
            signs=["коррозия"],
            explanation="На корпусе видны рыжие пятна, похожие на коррозию.",
            recommendation="Осмотреть корпус, оценить глубину коррозии.",
            assessment_confidence=0.7,
        )
    elif component_type == "flange":
        result = rules.Assessment(
            category=rules.POSSIBLE_DEFECT,
            signs=["течь/подтёки"],
            explanation="Под фланцевым соединением видны тёмные подтёки и капли.",
            recommendation="Проверить герметичность соединений и уплотнений.",
            assessment_confidence=0.82,
        )
    elif component_type == "valve":
        result = rules.poor_quality("снимок смазан")
    else:
        result = rules.Assessment(
            category=rules.NO_VISIBLE_ISSUES,
            signs=[],
            explanation=rules.template_explanation(rules.NO_VISIBLE_ISSUES, [], name),
            recommendation=rules.template_recommendation(rules.NO_VISIBLE_ISSUES, []),
            assessment_confidence=0.75,
        )
    return result.as_dict()


def identify() -> dict:
    return {
        "recognized": True,
        "candidates": [
            {"equipment_id": "PU-001", "confidence": 0.82},
            {"equipment_id": "PU-002", "confidence": 0.11},
        ],
    }
