"""Демо-данные заглушки.

Формат — строго по контракту (README плана, раздел 5.3). Значения ресурса здесь
вписаны вручную, а не рассчитаны: настоящий расчёт появится на этапе 2.
Данные подобраны так, чтобы в приложении встретились все статусы и цвета.
Даты — от 13.11.2026.
"""

from .enums import COMPONENT_TYPES, DISCLAIMER, NO_ISSUES_NOTE


def _visual(category, signs=(), explanation=None, recommendation=None,
            detection_confidence=None, assessment_confidence=None, analyzed_at=None):
    if category == "not_analyzed":
        return {
            "category": "not_analyzed", "signs": [], "explanation": None,
            "recommendation": None, "detection_confidence": None,
            "assessment_confidence": None, "analyzed_at": None, "disclaimer": None,
        }
    v = {
        "category": category,
        "signs": list(signs),
        "explanation": explanation,
        "recommendation": recommendation,
        "detection_confidence": detection_confidence,
        "assessment_confidence": assessment_confidence,
        "analyzed_at": analyzed_at,
        "disclaimer": DISCLAIMER,
    }
    if category == "no_visible_issues":
        v["note"] = NO_ISSUES_NOTE
    return v


def _component(id, parent_id, kind, name, type, *, characteristics=(), installed_at=None,
               last_replaced_at=None, last_maintenance_at=None, normative, usage, resource,
               visual, recommended_action=None, order=None):
    return {
        "id": id,
        "parent_id": parent_id,
        "kind": kind,
        "name": name,
        "type": type,
        "type_name": COMPONENT_TYPES[type]["name"],
        "order": order,
        "characteristics": list(characteristics),
        "installed_at": installed_at,
        "last_replaced_at": last_replaced_at,
        "last_maintenance_at": last_maintenance_at,
        "normative": normative,
        "usage": usage,
        "resource": resource,
        "visual": visual,
        # attention, parameters и previous_results достраиваются в main.py
        "_recommended_action": recommended_action,
    }


def _norm(years=None, hours=None, cycles=None, interval=None):
    return {"life_years": years, "life_hours": hours, "life_cycles": cycles,
            "maintenance_interval_days": interval}


def _usage(hours=None, cycles=None):
    return {"operating_hours": hours, "cycles": cycles}


def _resource(status, used, remaining, end, basis, missing, maint, message):
    return {
        "status": status,
        "used_percent": used,
        "remaining": remaining,
        "estimated_end_date": end,
        "basis": basis,
        "missing_data": missing,
        "maintenance": maint,
        "message": message,
    }


def _rem(years=None, hours=None, cycles=None):
    return {"years": years, "hours": hours, "cycles": cycles}


def _maint(next_due, status, overdue_days=None, days_left=None):
    m = {"next_due_date": next_due, "status": status}
    if overdue_days is not None:
        m["overdue_days"] = overdue_days
    if days_left is not None:
        m["days_left"] = days_left
    return m


EQUIPMENT = {
    "PU-001": {
        "id": "PU-001",
        "name": "Насосный агрегат",
        "model": "К 100-65-200",
        "manufacturer": "Демо-завод насосного оборудования",
        "serial_number": "SN2021-004587",
        "marking": "PU-001",
        "qr_code": "KST:PU-001",
        "location": "Насосная станция, зал 1",
        "commissioned_at": "2019-06-10",
        "characteristics": [
            {"name": "Подача", "value": "100", "unit": "м³/ч"},
            {"name": "Напор", "value": "50", "unit": "м"},
            {"name": "Мощность двигателя", "value": "30", "unit": "кВт"},
        ],
        "normative": _norm(years=15, hours=60000, interval=180),
        "usage": _usage(hours=38500),
        "resource": _resource(
            "approaching", 64, _rem(years=7.6, hours=21500), "2034-06-10",
            "Оценка по календарному сроку и наработке от даты ввода в эксплуатацию",
            [], _maint("2026-11-30", "approaching", days_left=17),
            "До планового обслуживания 17 дней",
        ),
    },
    "CC-001": {
        "id": "CC-001",
        "name": "Шкаф управления",
        "model": "ШУН-30",
        "manufacturer": "Демо-завод электрооборудования",
        "serial_number": "SN2020-001233",
        "marking": "CC-001",
        "qr_code": "KST:CC-001",
        "location": "Насосная станция, щитовая",
        "commissioned_at": "2020-02-20",
        "characteristics": [
            {"name": "Напряжение питания", "value": "380", "unit": "В"},
            {"name": "Степень защиты", "value": "IP54", "unit": None},
        ],
        "normative": _norm(years=20, interval=365),
        "usage": _usage(),
        "resource": _resource(
            "ok", 34, _rem(years=13.3), "2040-02-20",
            "Оценка по календарному сроку от даты ввода в эксплуатацию; наработка не предоставлена",
            ["operating_hours"], _maint("2027-03-01", "ok", days_left=108),
            "Ресурс в норме",
        ),
    },
}

COMPONENTS = {
    "PU-001": [
        _component(
            "N-01", None, "node", "Насос центробежный", "pump", order=2,
            characteristics=[{"name": "Тип", "value": "консольный", "unit": None}],
            installed_at="2019-06-10", last_maintenance_at="2026-05-20",
            normative=_norm(years=15, hours=60000, interval=180),
            usage=_usage(hours=38500),
            resource=_resource(
                "approaching", 64, _rem(years=7.6, hours=21500), "2034-06-10",
                "Оценка по календарному сроку и наработке от даты установки", [],
                _maint("2026-11-16", "approaching", days_left=3),
                "До планового обслуживания 3 дня",
            ),
            visual=_visual("not_analyzed"),
        ),
        _component(
            "C-02", "N-01", "part", "Манометр на напорном патрубке", "pressure_gauge", order=3,
            characteristics=[{"name": "Диапазон", "value": "0–10", "unit": "бар"}],
            installed_at="2019-06-10", last_replaced_at="2021-03-15",
            last_maintenance_at="2025-11-02",
            normative=_norm(years=8, interval=365),
            usage=_usage(),
            resource=_resource(
                "due", 71, _rem(years=2.3), "2029-03-15",
                "Оценка по календарному сроку от даты последней замены",
                ["operating_hours"], _maint("2026-11-02", "due", overdue_days=11),
                "Срок обслуживания наступил 11 дней назад",
            ),
            visual=_visual(
                "check_recommended", ["запотевшее стекло"],
                "Стекло помутнело, шкала читается плохо",
                "Проверить герметичность корпуса и читаемость шкалы",
                0.87, 0.6, "2026-11-13T12:05:00+03:00",
            ),
            recommended_action="Провести поверку манометра и проверить давление в линии",
        ),
        _component(
            "C-03", "N-01", "part", "Задвижка на всасывающей линии", "valve", order=1,
            characteristics=[{"name": "Условный проход", "value": "100", "unit": "мм"}],
            installed_at="2019-06-10", last_maintenance_at="2026-01-15",
            normative=_norm(years=8, cycles=2000, interval=365),
            usage=_usage(cycles=1780),
            resource=_resource(
                "approaching", 89, _rem(years=0.6, cycles=220), "2027-06-20",
                "Оценка по числу циклов от даты установки", [],
                _maint("2027-01-15", "ok", days_left=63),
                "Выработано 89 % ресурса по циклам",
            ),
            visual=_visual("not_analyzed"),
            recommended_action="Запланировать замену задвижки",
        ),
        _component(
            "C-04", "N-01", "part", "Задвижка на напорной линии", "valve", order=4,
            characteristics=[{"name": "Условный проход", "value": "65", "unit": "мм"}],
            installed_at="2024-04-01", last_maintenance_at="2026-04-01",
            normative=_norm(years=8, cycles=2000, interval=365),
            usage=_usage(cycles=310),
            resource=_resource(
                "ok", 33, _rem(years=5.4, cycles=1690), "2032-04-01",
                "Оценка по календарному сроку и числу циклов от даты установки", [],
                _maint("2027-04-01", "ok", days_left=139),
                "Ресурс в норме",
            ),
            visual=_visual(
                "no_visible_issues", [], "Корпус и шток задвижки чистые, подтёков не видно",
                "Продолжить плановые осмотры", 0.91, 0.8, "2026-11-12T15:20:00+03:00",
            ),
        ),
        _component(
            "C-05", "N-01", "part", "Фланцевое соединение напорного патрубка", "flange", order=5,
            installed_at=None,
            normative=_norm(years=10),
            usage=_usage(),
            resource=_resource(
                "insufficient_data", None, _rem(), None,
                "Оценка невозможна", ["installed_at", "operating_hours"], None,
                "Недостаточно данных для оценки ресурса",
            ),
            visual=_visual("not_analyzed"),
        ),
        _component(
            "N-02", None, "node", "Электродвигатель АИР 180M2", "electric_motor", order=0,
            characteristics=[
                {"name": "Мощность", "value": "30", "unit": "кВт"},
                {"name": "Частота вращения", "value": "2940", "unit": "об/мин"},
            ],
            installed_at="2019-06-10", last_maintenance_at="2026-08-10",
            normative=_norm(years=15, hours=40000, interval=180),
            usage=_usage(hours=36800),
            resource=_resource(
                "approaching", 92, _rem(years=7.6, hours=3200), "2027-08-01",
                "Оценка по наработке от даты установки", [],
                _maint("2027-02-06", "ok", days_left=85),
                "Выработано 92 % ресурса по наработке",
            ),
            visual=_visual(
                "possible_defect", ["следы коррозии на корпусе"],
                "На корпусе двигателя у лап крепления видны рыжие пятна, похожие на коррозию",
                "Осмотреть корпус, оценить глубину коррозии", 0.93, 0.7,
                "2026-11-13T11:48:00+03:00",
            ),
            recommended_action="Осмотреть корпус двигателя и крепления, оценить глубину коррозии",
        ),
    ],
    "CC-001": [
        _component(
            "C-11", None, "node", "Вентилятор охлаждения шкафа", "electric_motor", order=0,
            installed_at="2020-02-20", last_maintenance_at="2026-03-01",
            normative=_norm(years=7, hours=50000, interval=365),
            usage=_usage(hours=21000),
            resource=_resource(
                "ok", 42, _rem(years=3.7, hours=29000), "2030-07-20",
                "Оценка по наработке от даты установки", [],
                _maint("2027-03-01", "ok", days_left=108),
                "Ресурс в норме",
            ),
            visual=_visual("not_analyzed"),
        ),
        _component(
            "C-12", None, "node", "Автоматический выключатель QF1", "circuit_breaker", order=1,
            installed_at="2014-02-20",
            normative=_norm(years=12, cycles=10000),
            usage=_usage(cycles=4100),
            resource=_resource(
                "due", 105, _rem(years=0, cycles=5900), "2026-02-20",
                "Оценка по календарному сроку от даты установки", [],
                None, "Наступил срок замены: нормативный срок истёк 9 месяцев назад",
            ),
            visual=_visual("not_analyzed"),
            recommended_action="Заменить автоматический выключатель",
        ),
    ],
}

PARAMETERS = {
    "PU-001": [
        {"id": "P-01", "component_id": "C-02", "name": "Давление на выходе", "value": 7.9,
         "unit": "бар", "setpoint_min": 4.0, "setpoint_max": 6.5,
         "measured_at": "2026-11-13T09:40:00+03:00", "status": "deviation",
         "message": "Выше верхней уставки на 1,4 бар"},
        {"id": "P-02", "component_id": "N-02", "name": "Ток двигателя", "value": 52.0,
         "unit": "А", "setpoint_min": None, "setpoint_max": 57.0,
         "measured_at": "2026-11-13T09:40:00+03:00", "status": "normal", "message": "В норме"},
        {"id": "P-03", "component_id": "N-02", "name": "Вибрация подшипникового узла",
         "value": None, "unit": "мм/с", "setpoint_min": None, "setpoint_max": 4.5,
         "measured_at": None, "status": "no_data", "message": "Нет данных"},
    ],
    "CC-001": [
        {"id": "P-11", "component_id": None, "name": "Температура внутри шкафа", "value": 31.0,
         "unit": "°C", "setpoint_min": 5.0, "setpoint_max": 40.0,
         "measured_at": "2026-11-13T09:40:00+03:00", "status": "normal", "message": "В норме"},
    ],
}

# От новых к старым.
HISTORY = {
    "PU-001": [
        {"id": 6, "component_id": "N-02", "type": "remark",
         "comment": "Пятна ржавчины у лап крепления двигателя",
         "performed_by": "Инженер Петров", "performed_at": "2026-11-13T11:50:00+03:00",
         "visual": None, "recommendation": "Оценить глубину коррозии при следующем ТО"},
        {"id": 5, "component_id": "N-02", "type": "maintenance",
         "comment": "Замена смазки подшипников", "performed_by": "Инженер Петров",
         "performed_at": "2026-08-10T10:00:00+03:00", "visual": None,
         "recommendation": "Следующее ТО через 6 месяцев"},
        {"id": 4, "component_id": "N-01", "type": "maintenance",
         "comment": "Плановое ТО насоса", "performed_by": "Инженер Сидоров",
         "performed_at": "2026-05-20T09:30:00+03:00", "visual": None,
         "recommendation": "Следующее ТО через 6 месяцев"},
        {"id": 3, "component_id": "C-03", "type": "checked",
         "comment": "Ход задвижки плавный", "performed_by": "Инженер Сидоров",
         "performed_at": "2026-01-15T14:00:00+03:00", "visual": None,
         "recommendation": "Подготовить замену при выработке 90 % по циклам"},
        {"id": 2, "component_id": "C-02", "type": "maintenance",
         "comment": "Поверка", "performed_by": "Инженер Иванов",
         "performed_at": "2025-11-02T10:00:00+03:00", "visual": None,
         "recommendation": "Следующая поверка через 12 месяцев"},
        {"id": 1, "component_id": "C-02", "type": "replacement",
         "comment": "Замена манометра: разбито стекло", "performed_by": "Инженер Иванов",
         "performed_at": "2021-03-15T11:00:00+03:00", "visual": None,
         "recommendation": None},
    ],
    "CC-001": [
        {"id": 7, "component_id": "C-11", "type": "maintenance",
         "comment": "Очистка фильтра вентилятора", "performed_by": "Инженер Иванов",
         "performed_at": "2026-03-01T10:00:00+03:00", "visual": None,
         "recommendation": "Следующая очистка через 12 месяцев"},
    ],
}

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
