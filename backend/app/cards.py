"""Сборка цифровой карточки и карточки узла по контракту + правило attention.

Здесь же собираются все тексты для экрана (причины, рекомендации, подсказки) —
приложение показывает их как есть (план, раздел 6.1, п. 5).
"""

from datetime import date, datetime

from . import config, repo, resource
from .enums import COMPONENT_TYPES, DISCLAIMER, NO_ISSUES_NOTE
from .parameters import evaluate

NOT_ANALYZED = {
    "category": "not_analyzed", "signs": [], "explanation": None, "recommendation": None,
    "detection_confidence": None, "assessment_confidence": None, "analyzed_at": None,
    "disclaimer": None,
}


def lower_first(s):
    return s[:1].lower() + s[1:] if s else s


def visual_block(v):
    if v is None:
        return dict(NOT_ANALYZED)
    out = {
        "category": v["category"], "signs": v["signs"], "explanation": v["explanation"],
        "recommendation": v["recommendation"],
        "detection_confidence": v["detection_confidence"],
        "assessment_confidence": v["assessment_confidence"],
        "analyzed_at": v["analyzed_at"], "disclaimer": DISCLAIMER,
    }
    if v["category"] == "no_visible_issues":
        out["note"] = NO_ISSUES_NOTE
    return out


def calc(item, today=None):
    s = config.SETTINGS
    return resource.calculate(item, today or config.today(),
                              s["resource_approaching_percent"], s["maintenance_warning_days"])


def attention(c, res, vis, params):
    """Правило attention.level (README плана, 5.1). Причины — от серьёзных к менее серьёзным."""
    maint = res.get("maintenance") or {}
    reasons = []  # (текст, действие)
    name_acc = lower_first(c["name"])
    m_action = c.get("maintenance_action") or "Провести плановое обслуживание"

    if maint.get("status") == "due":
        reasons.append(("Наступил срок обслуживания", m_action))
    if res["_life_due"]:
        reasons.append(("Наступил срок замены", f"Заменить {name_acc}"))
    deviations = [p for p in params if p["status"] == "deviation"]
    for p in deviations:
        reasons.append((f"{p['name']}: {lower_first(p['message'])}",
                        f"Проверить причину отклонения параметра «{p['name']}»"))
    if vis["category"] == "possible_defect":
        signs = ", ".join(vis["signs"])
        reasons.append(("Обнаружены признаки возможного дефекта" + (f": {signs}" if signs else ""),
                        vis["recommendation"] or "Осмотреть узел"))
    if res["_life_near"] and not res["_life_due"]:
        reasons.append((f"Выработано {res['used_percent']} % ресурса", f"Запланировать замену: {name_acc}"))
    if maint.get("status") == "approaching":
        due = date.fromisoformat(maint["next_due_date"]).strftime("%d.%m.%Y")
        reasons.append((f"До обслуживания {resource.days_text(maint['days_left'])}",
                        f"{m_action} до {due}"))
    if vis["category"] == "check_recommended":
        signs = ", ".join(vis["signs"])
        reasons.append(("Рекомендуется проверка" + (f": {signs}" if signs else ""),
                        vis["recommendation"] or "Осмотреть узел"))

    status = res["status"]
    if vis["category"] == "possible_defect" or status == "due" or deviations:
        level = "defect"
    elif vis["category"] == "check_recommended" or status == "approaching":
        level = "check"
    elif vis["category"] == "no_visible_issues" and status == "ok" and \
            all(p["status"] == "normal" for p in params):
        level = "none"
    else:
        level = "unknown"
        if vis["category"] == "not_analyzed":
            detectable = COMPONENT_TYPES.get(c["type"], {}).get("detectable")
            reasons.append(("Визуальный анализ не проводился",
                            "Провести визуальный анализ узла" if detectable else "Осмотреть узел"))
        if status == "insufficient_data":
            reasons.append(("Недостаточно данных для оценки ресурса",
                            "Внести в карточку недостающие данные"))
        if any(p["status"] == "no_data" for p in params):
            reasons.append(("Нет текущих значений части параметров", "Снять показания параметров"))

    action = reasons[0][1] if reasons else "Продолжить плановые осмотры"
    return {"level": level, "reasons": [r[0] for r in reasons], "recommended_action": action}


class Card:
    """Все данные одного оборудования, загруженные за один проход по базе."""

    def __init__(self, conn, eq_id, today: date | None = None):
        self.conn = conn
        self.today = today or config.today()
        self.eq = repo.equipment(conn, eq_id)
        if self.eq is None:
            return
        self.components = repo.components(conn, eq_id)
        self.params = [evaluate(p) for p in repo.parameters(conn, eq_id)]
        self.visuals = repo.latest_visuals(conn, eq_id)
        self._built = {}

    @property
    def exists(self):
        return self.eq is not None

    def raw(self, cid):
        return next((c for c in self.components if c["id"] == cid), None)

    def params_of(self, cid):
        return [p for p in self.params if p["component_id"] == cid]

    def evaluated(self, c):
        """(resource, visual, attention) компонента — кешируется на время запроса."""
        if c["id"] not in self._built:
            res = calc(c, self.today)
            vis = visual_block(self.visuals.get(c["id"]))
            self._built[c["id"]] = (res, vis, attention(c, res, vis, self.params_of(c["id"])))
        return self._built[c["id"]]

    def component(self, c, with_history=True):
        res, vis, att = self.evaluated(c)
        out = {
            "id": c["id"], "parent_id": c["parent_id"], "kind": c["kind"], "name": c["name"],
            "type": c["type"], "type_name": COMPONENT_TYPES.get(c["type"], {}).get("name", c["type"]),
            "order": c["sort_order"], "characteristics": c["characteristics"],
            "installed_at": c["installed_at"], "last_replaced_at": c["last_replaced_at"],
            "last_maintenance_at": c["last_maintenance_at"],
            "normative": resource.normative_block(c),
            "usage": resource.usage_block(c),
            "resource": resource.public(res),
            "visual": vis,
            "attention": att,
            "parameters": [p["id"] for p in self.params_of(c["id"])],
        }
        if with_history:
            out["previous_results"] = [history_item(h) for h in
                                       repo.history(self.conn, self.eq["id"], c["id"], limit=5)]
        return out

    def full(self):
        eq = self.eq
        hist = [history_item(h) for h in repo.history(self.conn, eq["id"])]
        by_comp = {}
        for h in hist:
            by_comp.setdefault(h["component_id"], []).append(h)
        comps = []
        for c in self.components:
            item = self.component(c, with_history=False)
            item["previous_results"] = by_comp.get(c["id"], [])[:5]
            comps.append(item)
        return {
            "id": eq["id"], "name": eq["name"], "model": eq["model"],
            "manufacturer": eq["manufacturer"], "serial_number": eq["serial_number"],
            "marking": eq["marking"], "qr_code": eq["qr_code"], "location": eq["location"],
            "commissioned_at": eq["commissioned_at"], "characteristics": eq["characteristics"],
            "normative": resource.normative_block(eq),
            "usage": resource.usage_block(eq),
            "resource": resource.public(calc(eq, self.today)),
            "parameters": self.params,
            "deviations_count": sum(p["status"] == "deviation" for p in self.params),
            "components": comps,
            "history": hist,
        }

    def attention_items(self):
        """Узлы, требующие проверки (шаги 4–5 сценария), + давно не осматривавшиеся."""
        last = repo.last_inspection_dates(self.conn, self.eq["id"])
        days_limit = config.SETTINGS["not_inspected_days"]
        rank = {"defect": 0, "check": 1, "unknown": 2, "none": 3}
        items = []
        for c in self.components:
            _, _, att = self.evaluated(c)
            reasons = list(att["reasons"])
            stale = False
            if c["id"] in last:
                age = (self.today - datetime.fromisoformat(last[c["id"]]).date()).days
                if age > days_limit:
                    stale = True
                    reasons.append(f"Не осматривался {resource.days_text(age)}")
            else:
                stale = True
                reasons.append("Нет записей об осмотре")
            if att["level"] in ("defect", "check") or (stale and att["level"] == "unknown"):
                items.append({
                    "component_id": c["id"], "name": c["name"], "level": att["level"],
                    "reasons": reasons, "recommended_action": att["recommended_action"],
                    "hint": f"Наведите камеру на {lower_first(c['name'])}",
                    "detectable": bool(COMPONENT_TYPES.get(c["type"], {}).get("detectable")),
                })
        items.sort(key=lambda i: rank[i["level"]])
        return items


def history_item(h):
    return {
        "id": h["id"], "component_id": h["component_id"], "type": h["type"],
        "comment": h["comment"], "performed_by": h["performed_by"],
        "performed_at": h["performed_at"], "visual": h["visual"],
        "recommendation": h["recommendation"],
    }
