"""Правила классификации и ограничения формулировок (ТЗ, раздел 4.2).

Модель предлагает ответ, код его проверяет: категория, признаки и тексты приводятся
к разрешённому виду независимо от того, что написала модель.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NO_VISIBLE_ISSUES = "no_visible_issues"
CHECK_RECOMMENDED = "check_recommended"
POSSIBLE_DEFECT = "possible_defect"
CATEGORIES = (NO_VISIBLE_ISSUES, CHECK_RECOMMENDED, POSSIBLE_DEFECT)

# Утверждённый список признаков: код для модели -> текст в ответе.
SIGNS = {
    "corrosion": "коррозия",
    "leak": "течь/подтёки",
    "mechanical_damage": "механическое повреждение",
    "overheating": "следы перегрева",
}

# Признаки, которые имеют смысл только для некоторых типов узлов (перечень дефектов заказчика:
# следы перегрева — у электродвигателя). Для остальных типов код такой признак отбрасывает.
SIGN_TYPES = {"overheating": {"electric_motor"}}

# Слова, которыми результат подавать нельзя: утверждение исправности, диагноз,
# внутренняя неисправность. Проверяются по началу слова, без учёта регистра.
FORBIDDEN_PATTERNS = (
    r"\bисправ",            # исправен, исправно, исправность
    r"\bнеисправ",          # неисправен, неисправность
    r"\bв\s+(полном\s+)?порядке\b",
    r"\bдефект\w*\s+(нет|не\s+обнаруж|не\s+выявл|отсутств)",
    r"\b(нет|без|отсутств\w*)\s+(каких[- ]либо\s+|видимых\s+)?дефект",
    r"\bработоспособ",
    r"\bв\s+(хорошем|отличном|нормальном|рабочем|идеальном)\s+состоянии\b",
    r"\bв\s+норме\b",
    r"\bгод(ен|на|но|ны)\b",
    r"\bдиагноз",
    r"\bвнутренн",          # любые утверждения о внутреннем состоянии
    r"\bвышел\s+из\s+строя\b",
    r"\bвыш(ла|ло|ли)\s+из\s+строя\b",
    r"\bизнос\s+подшипник",
    r"\bнеобходим\w*\s+замен",  # замену назначает инженер, а не предварительный осмотр
    r"\bтребу\w+\s+замен",
)
_FORBIDDEN = re.compile("|".join(FORBIDDEN_PATTERNS), re.IGNORECASE)
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

MAX_TEXT_LEN = 300


@dataclass
class Assessment:
    category: str
    signs: list[str] = field(default_factory=list)
    explanation: str = ""
    recommendation: str = ""
    assessment_confidence: float = 0.0
    image_quality: str = "ok"

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "signs": list(self.signs),
            "explanation": self.explanation,
            "recommendation": self.recommendation,
            "assessment_confidence": round(self.assessment_confidence, 2),
            "image_quality": self.image_quality,
        }


def has_forbidden(text: str) -> bool:
    return bool(_FORBIDDEN.search(text))


def _join_signs(signs: list[str]) -> str:
    return ", ".join(signs)


def template_explanation(category: str, signs: list[str], component_name: str) -> str:
    if category == NO_VISIBLE_ISSUES:
        return f"На снимке узла «{component_name}» видимых проблем не обнаружено."
    if category == POSSIBLE_DEFECT:
        return f"На снимке узла «{component_name}» видны признаки возможного дефекта: {_join_signs(signs)}."
    if signs:
        return f"На снимке узла «{component_name}» есть признаки, похожие на: {_join_signs(signs)}."
    return f"На снимке узла «{component_name}» есть участки, которые по изображению оценить однозначно нельзя."


def template_recommendation(category: str, signs: list[str]) -> str:
    if category == NO_VISIBLE_ISSUES:
        return "Продолжить осмотр по регламенту."
    parts = []
    if SIGNS["corrosion"] in signs:
        parts.append("осмотреть поверхность и оценить глубину коррозии")
    if SIGNS["leak"] in signs:
        parts.append("проверить герметичность соединений и уплотнений")
    if SIGNS["mechanical_damage"] in signs:
        parts.append("осмотреть место повреждения и проверить целостность корпуса")
    if SIGNS["overheating"] in signs:
        parts.append("проверить нагрев корпуса и состояние клеммной коробки и изоляции кабелей")
    if not parts:
        return "Осмотреть узел на месте."
    text = "; ".join(parts) + "."
    return text[0].upper() + text[1:]


def poor_quality(reason: str | None) -> Assessment:
    """Плохой снимок: всегда «рекомендуется проверка», никогда «видимых проблем не обнаружено»."""
    detail = f": {reason}" if reason else ""
    return Assessment(
        category=CHECK_RECOMMENDED,
        signs=[],
        explanation=f"По снимку оценить состояние узла нельзя{detail}.",
        recommendation="Повторить съёмку ближе и при хорошем освещении либо осмотреть узел на месте.",
        assessment_confidence=0.0,
        image_quality="poor",
    )


def analysis_failed() -> Assessment:
    """Модель не ответила вовремя или дважды нарушила формат."""
    return Assessment(
        category=CHECK_RECOMMENDED,
        signs=[],
        explanation="Автоматический анализ не выполнен.",
        recommendation="Повторить анализ или осмотреть узел на месте.",
        assessment_confidence=0.0,
        image_quality="ok",
    )


def _clean_text(text: str) -> str:
    text = " ".join(str(text).split())
    sentences = _SENTENCE_END.split(text)
    text = " ".join(sentences[:2])
    if len(text) > MAX_TEXT_LEN:
        text = text[: MAX_TEXT_LEN - 1].rstrip(" ,;:") + "…"
    return text


def _text_ok(text: str) -> bool:
    return len(text) >= 5 and bool(_CYRILLIC.search(text)) and not has_forbidden(text)


class FormatError(ValueError):
    """Ответ модели не соответствует схеме."""


def parse_model_answer(raw: dict) -> Assessment:
    """Проверяет ответ модели по схеме. Нарушение формата — FormatError (повод для повтора)."""
    if not isinstance(raw, dict):
        raise FormatError("ответ не является объектом")
    category = raw.get("category")
    if category not in CATEGORIES:
        raise FormatError(f"недопустимая категория: {category!r}")
    quality = raw.get("image_quality")
    if quality not in ("ok", "poor"):
        raise FormatError(f"недопустимое качество снимка: {quality!r}")
    signs_raw = raw.get("signs")
    if not isinstance(signs_raw, list):
        raise FormatError("signs не является списком")
    signs: list[str] = []
    for code in signs_raw:
        if code not in SIGNS:
            raise FormatError(f"признак не из утверждённого списка: {code!r}")
        if SIGNS[code] not in signs:
            signs.append(SIGNS[code])
    confidence = raw.get("assessment_confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise FormatError("assessment_confidence не число")
    if not isinstance(raw.get("explanation"), str) or not isinstance(raw.get("recommendation"), str):
        raise FormatError("нет текста объяснения или рекомендации")
    return Assessment(
        category=category,
        signs=signs,
        explanation=raw["explanation"],
        recommendation=raw["recommendation"],
        assessment_confidence=min(1.0, max(0.0, float(confidence))),
        image_quality=quality,
    )


def allowed_signs(component_type: str) -> list[str]:
    """Коды признаков, допустимые для типа узла."""
    return [code for code in SIGNS if code not in SIGN_TYPES or component_type in SIGN_TYPES[code]]


def enforce(assessment: Assessment, component_name: str, component_type: str = "") -> Assessment:
    """Приводит разобранный ответ модели к правилам классификации и формулировок."""
    allowed = {SIGNS[code] for code in allowed_signs(component_type)}
    assessment = Assessment(**{**assessment.__dict__, "signs": [s for s in assessment.signs if s in allowed]})
    if assessment.image_quality == "poor":
        result = poor_quality(None)
        explanation = _clean_text(assessment.explanation)
        # объяснение модели оставляем, только если оно действительно про качество снимка
        if _text_ok(explanation) and re.search(r"снимк|изображен|фото|кадр", explanation, re.IGNORECASE):
            result.explanation = explanation
        return result

    category = assessment.category
    signs = list(assessment.signs)
    # «Видимых проблем не обнаружено» — только при хорошем снимке без признаков.
    if category == NO_VISIBLE_ISSUES and signs:
        category = CHECK_RECOMMENDED
    # Возможный дефект должен опираться на признак из утверждённого списка.
    if category == POSSIBLE_DEFECT and not signs:
        category = CHECK_RECOMMENDED

    explanation = _clean_text(assessment.explanation)
    recommendation = _clean_text(assessment.recommendation)
    changed = category != assessment.category
    if changed or not _text_ok(explanation):
        explanation = template_explanation(category, signs, component_name)
    if changed or not _text_ok(recommendation) or category == NO_VISIBLE_ISSUES:
        recommendation = template_recommendation(category, signs)
    return Assessment(
        category=category,
        signs=signs,
        explanation=explanation,
        recommendation=recommendation,
        assessment_confidence=assessment.assessment_confidence,
        image_quality="ok",
    )
