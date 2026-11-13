"""Перечисления и подписи из контракта (README плана, раздел 5.1).

Подписи — дословно из ТЗ. Меняются только по согласию всех троих.
"""

# Словарь типов узлов: type в базе = cv_class в ИИ-сервисе.
# prompt — текстовое название класса для детектора с открытым словарём (подбирает Тимофей).
# detectable=False — тип есть в карточке, но ИИ его не ищет.
COMPONENT_TYPES = {
    "electric_motor": {"name": "Электродвигатель", "prompt": "electric motor", "detectable": True},
    "pressure_gauge": {"name": "Манометр", "prompt": "pressure gauge", "detectable": True},
    "valve": {"name": "Запорная арматура", "prompt": "valve", "detectable": True},
    "flange": {"name": "Фланцевое соединение", "prompt": "pipe flange", "detectable": True},
    # Не распознаются ИИ — нужны только для полноты состава оборудования.
    "pump": {"name": "Насос", "prompt": None, "detectable": False},
    "circuit_breaker": {"name": "Автоматический выключатель", "prompt": None, "detectable": False},
}

DETECTABLE_TYPES = [t for t, v in COMPONENT_TYPES.items() if v["detectable"]]

VISUAL_CATEGORY_LABELS = {
    "no_visible_issues": "Видимых проблем не обнаружено",
    "check_recommended": "Рекомендуется проверка",
    "possible_defect": "Обнаружены признаки возможного дефекта",
    "not_analyzed": "Визуальный анализ не проводился",
}

RESOURCE_STATUS_LABELS = {
    "ok": "Ресурс в норме",
    "approaching": "Приближается срок обслуживания или замены",
    "due": "Наступил срок обслуживания или замены",
    "insufficient_data": "Недостаточно данных для оценки ресурса",
}

PARAMETER_STATUS_LABELS = {
    "normal": "В норме",
    "deviation": "Отклонение",
    "no_data": "Нет данных",
}

ATTENTION_LEVELS = ("defect", "check", "none", "unknown")

INSPECTION_TYPES = {
    "checked": "Компонент проверен",
    "defect": "Обнаружен дефект",
    "remark": "Замечание",
    "maintenance": "Обслуживание",
    "replacement": "Замена",
}
INSPECTION_TYPES_NEED_COMMENT = ("defect", "remark")

# Обязательные тексты (ТЗ, раздел 4.2).
DISCLAIMER = "Предварительный осмотр по изображению. Внутренние неисправности так не определяются"
NO_ISSUES_NOTE = "Отсутствие видимых дефектов не подтверждает исправность оборудования"
