"""Расчёт эксплуатационного ресурса (ТЗ 4.3; правила — план Андрея, этап 2).

Вход — словарь с полями оборудования или компонента:
  installed_at / commissioned_at, last_replaced_at, last_maintenance_at,
  life_years, life_hours, life_cycles, maintenance_interval_days,
  operating_hours, cycles (наработка и циклы — от точки отсчёта).
Выход — блоки `normative`, `usage`, `resource` контракта. Они не смешиваются.
"""

from datetime import date, timedelta

DAYS_PER_YEAR = 365.25

MISSING_LABELS = {
    "installed_at": "дата установки",
    "operating_hours": "наработка",
    "cycles": "число рабочих циклов",
    "last_maintenance_at": "дата последнего обслуживания",
    "normative": "нормативный срок службы",
}

_INDICATOR_TEXT = {
    "years": "календарному сроку",
    "hours": "наработке",
    "cycles": "числу циклов",
}


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def days_text(n):
    return f"{n} {plural(n, 'день', 'дня', 'дней')}"


def _d(s):
    return date.fromisoformat(s[:10]) if s else None


def normative_block(item):
    return {
        "life_years": item.get("life_years"),
        "life_hours": item.get("life_hours"),
        "life_cycles": item.get("life_cycles"),
        "maintenance_interval_days": item.get("maintenance_interval_days"),
    }


def usage_block(item):
    return {"operating_hours": item.get("operating_hours"), "cycles": item.get("cycles")}


def _maintenance(item, ref, today, warn_days):
    interval = item.get("maintenance_interval_days")
    if not interval:
        return None, []
    last = _d(item.get("last_maintenance_at")) or ref
    if last is None:
        return None, ["last_maintenance_at"]
    nxt = last + timedelta(days=int(interval))
    left = (nxt - today).days
    if left <= 0:
        m = {"next_due_date": nxt.isoformat(), "status": "due", "overdue_days": -left}
    elif left <= warn_days:
        m = {"next_due_date": nxt.isoformat(), "status": "approaching", "days_left": left}
    else:
        m = {"next_due_date": nxt.isoformat(), "status": "ok", "days_left": left}
    return m, []


def calculate(item, today: date, approaching_percent=80, warn_days=30):
    replaced = _d(item.get("last_replaced_at"))
    installed = _d(item.get("installed_at") or item.get("commissioned_at"))
    ref = replaced or installed
    ref_text = "от даты последней замены" if replaced else (
        "от даты ввода в эксплуатацию" if item.get("commissioned_at") else "от даты установки")

    elapsed_days = (today - ref).days if ref else None
    fractions, remaining, end_dates, missing = {}, {"years": None, "hours": None, "cycles": None}, {}, []

    # Календарный срок
    if item.get("life_years"):
        if ref is None:
            missing.append("installed_at")
        else:
            life_days = item["life_years"] * DAYS_PER_YEAR
            fractions["years"] = elapsed_days / life_days
            remaining["years"] = round(max(item["life_years"] - elapsed_days / DAYS_PER_YEAR, 0), 1)
            end_dates["years"] = ref + timedelta(days=round(life_days))

    # Наработка и циклы: доля выработки и прогноз по средней скорости с точки отсчёта
    for key, life_key, field in (("hours", "life_hours", "operating_hours"),
                                 ("cycles", "life_cycles", "cycles")):
        life, used = item.get(life_key), item.get(field)
        if not life:
            continue
        if used is None:
            missing.append(field)
            continue
        fractions[key] = used / life
        remaining[key] = max(round(life - used), 0)
        if elapsed_days and used > 0:
            # по средней скорости расхода с точки отсчёта; если ресурс исчерпан — дата в прошлом
            per_day = used / elapsed_days
            end_dates[key] = ref + timedelta(days=round(life / per_day))

    if not any(item.get(k) for k in ("life_years", "life_hours", "life_cycles")):
        missing.append("normative")
    if ref is None and "installed_at" not in missing:
        missing.insert(0, "installed_at")  # без даты отсчёта ресурс не посчитать ни по какому нормативу

    maintenance, m_missing = _maintenance(item, ref, today, warn_days)
    missing += m_missing

    used_fraction = max(fractions.values()) if fractions else None
    used_percent = round(used_fraction * 100) if used_fraction is not None else None
    m_status = maintenance["status"] if maintenance else None
    life_due = used_fraction is not None and used_fraction >= 1
    life_near = used_fraction is not None and used_fraction * 100 >= approaching_percent

    if life_due or m_status == "due":
        status = "due"
    elif life_near or m_status == "approaching":
        status = "approaching"
    elif not fractions:
        status = "insufficient_data"
    else:
        status = "ok"

    # На чём основана оценка
    if fractions:
        names = [_INDICATOR_TEXT[k] for k in ("years", "hours", "cycles") if k in fractions]
        basis = "Оценка по " + " и ".join(names) + " " + ref_text
    else:
        basis = "Оценка ресурса невозможна"
    if missing:
        basis += "; не предоставлено: " + ", ".join(MISSING_LABELS[m] for m in missing)

    first_end = min(end_dates.values()) if end_dates else None
    limiting = max(fractions, key=fractions.get) if fractions else None

    # Одна фраза для экрана — по самой серьёзной причине
    if life_due:
        message = f"Наступил срок замены: выработано {used_percent} % ресурса"
    elif m_status == "due":
        n = maintenance["overdue_days"]
        message = "Срок обслуживания наступил сегодня" if n == 0 else \
            f"Срок обслуживания наступил {days_text(n)} назад"
    elif life_near:
        message = f"Выработано {used_percent} % ресурса по {_INDICATOR_TEXT[limiting]}"
    elif m_status == "approaching":
        message = f"До обслуживания {days_text(maintenance['days_left'])}"
    elif status == "insufficient_data":
        message = "Недостаточно данных для оценки ресурса"
    else:
        message = "Ресурс в норме"

    return {
        "status": status,
        "used_percent": used_percent,
        "remaining": remaining,
        "estimated_end_date": first_end.isoformat() if first_end else None,
        "basis": basis,
        "missing_data": missing,
        "maintenance": maintenance,
        "message": message,
        # служебные поля для правила attention (в ответ не попадают)
        "_life_due": life_due,
        "_life_near": life_near,
    }


def public(resource):
    return {k: v for k, v in resource.items() if not k.startswith("_")}
