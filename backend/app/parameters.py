"""Сравнение технических параметров с уставками (ТЗ 4.1)."""


def _num(x):
    s = f"{round(x, 2):g}"
    return s.replace(".", ",")


def evaluate(p):
    """Добавляет к параметру status и message."""
    p = dict(p)
    v, lo, hi, unit = p["value"], p["setpoint_min"], p["setpoint_max"], p.get("unit") or ""
    if v is None:
        p["status"], p["message"] = "no_data", "Нет данных"
    elif hi is not None and v > hi:
        p["status"] = "deviation"
        p["message"] = f"Выше верхней уставки на {_num(v - hi)} {unit}".rstrip()
    elif lo is not None and v < lo:
        p["status"] = "deviation"
        p["message"] = f"Ниже нижней уставки на {_num(lo - v)} {unit}".rstrip()
    else:
        p["status"], p["message"] = "normal", "В норме"
    return p
