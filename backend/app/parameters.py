"""Сравнение технических параметров с уставками (ТЗ 4.1).

У параметров из материалов заказчика (вибрация и температура насосного агрегата) две
границы: уставка предупреждения (setpoint_max) и уровень тревоги (alarm_max), и для
каждой — диагноз из описаний баз значений заказчика (warn_text, alarm_text).
Эти поля — внутренние, в ответ попадает готовый текст message.
"""


def _num(x):
    s = f"{round(x, 2):g}"
    return s.replace(".", ",")


def evaluate(p):
    """Добавляет к параметру status и message; внутренние поля убирает."""
    p = dict(p)
    warn_text, alarm_max, alarm_text = p.pop("warn_text", None), p.pop("alarm_max", None), \
        p.pop("alarm_text", None)
    v, lo, hi, unit = p["value"], p["setpoint_min"], p["setpoint_max"], p.get("unit") or ""
    u = f" {unit}" if unit else ""
    if v is None:
        p["status"], p["message"] = "no_data", "Нет данных"
    elif alarm_max is not None and v > alarm_max:
        p["status"] = "deviation"
        p["message"] = f"Тревога: выше {_num(alarm_max)}{u} на {_num(v - alarm_max)}{u}" + \
            (f" — {alarm_text}" if alarm_text else "")
    elif hi is not None and v > hi:
        p["status"] = "deviation"
        if warn_text:
            tail = f" (тревога — выше {_num(alarm_max)}{u})" if alarm_max is not None else ""
            p["message"] = f"Предупреждение: выше {_num(hi)}{u} на {_num(v - hi)}{u} — {warn_text}{tail}"
        else:
            p["message"] = f"Выше верхней уставки на {_num(v - hi)}{u}"
    elif lo is not None and v < lo:
        p["status"] = "deviation"
        p["message"] = f"Ниже нижней уставки на {_num(lo - v)}{u}"
    else:
        p["status"], p["message"] = "normal", "В норме"
    return p
