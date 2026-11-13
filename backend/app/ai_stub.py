"""Ответы ИИ-сервиса в режиме заглушки (ai_mode = "stub")."""

# Ответы «ИИ» в заглушке: рамки в долях кадра [x, y, ширина, высота].
DETECT = {
    "PU-001": [
        {"bbox": [0.05, 0.40, 0.30, 0.35], "cv_class": "electric_motor", "confidence": 0.93},
        {"bbox": [0.41, 0.22, 0.12, 0.18], "cv_class": "pressure_gauge", "confidence": 0.87},
        {"bbox": [0.62, 0.55, 0.14, 0.20], "cv_class": "valve", "confidence": 0.78},
    ],
    "CC-001": [
        {"bbox": [0.30, 0.10, 0.25, 0.20], "cv_class": "electric_motor", "confidence": 0.81},
        {"bbox": [0.70, 0.60, 0.10, 0.12], "cv_class": "pressure_gauge", "confidence": 0.55},
    ],
}

ANALYZE = {
    "category": "check_recommended",
    "signs": ["следы коррозии"],
    "explanation": "На поверхности узла видны рыжие пятна, похожие на коррозию",
    "recommendation": "Осмотреть узел вблизи, оценить глубину коррозии",
    "assessment_confidence": 0.65,
    "image_quality": "ok",
}

IDENTIFY = {
    "recognized": True,
    "candidates": [
        {"equipment_id": "PU-001", "confidence": 0.82},
        {"equipment_id": "CC-001", "confidence": 0.11},
    ],
}
