"""Сопоставление рамок ИИ с узлами цифровой карточки (ТЗ 4.2; правило — план Андрея, этап 2).

  тип совпал, узел такого типа один ............ matched
  узлов такого типа несколько .................. по порядку слева направо (order),
                                                 если число рамок = числу узлов; иначе ambiguous
  типа нет в карточке .......................... not_in_card
  распознаваемые узлы карточки, которых нет ...... not_in_frame
"""

from .cards import Card
from .enums import COMPONENT_TYPES, DETECTABLE_TYPES


def classes_for(card: Card):
    return sorted({c["type"] for c in card.components if c["type"] in DETECTABLE_TYPES})


def match(card: Card, raw):
    by_type = {}
    for c in card.components:
        by_type.setdefault(c["type"], []).append(c)
    by_class = {}
    for d in raw:
        by_class.setdefault(d["cv_class"], []).append(d)

    detections, seen = [], set()
    for cv_class, dets in by_class.items():
        cands = sorted(by_type.get(cv_class, []),
                       key=lambda c: (c["sort_order"] is None, c["sort_order"] or 0))
        dets = sorted(dets, key=lambda d: d["bbox"][0])  # слева направо
        if not cands:
            pairs = [(d, None, "not_in_card") for d in dets]
        elif len(cands) == len(dets):
            pairs = [(d, c, "matched") for d, c in zip(dets, cands)]
        else:
            pairs = [(d, None, "ambiguous") for d in dets]

        type_name = COMPONENT_TYPES.get(cv_class, {}).get("name", cv_class)
        for d, c, kind in pairs:
            item = {"bbox": [round(x, 4) for x in d["bbox"]], "cv_class": cv_class,
                    "detection_confidence": d["confidence"], "match": kind}
            if kind == "matched":
                seen.add(c["id"])
                res, vis, att = card.evaluated(c)
                item.update({
                    "component_id": c["id"], "candidates": None, "label": c["name"],
                    "attention_level": att["level"], "resource_status": res["status"],
                    "visual_category": vis["category"],
                    "reason": att["reasons"][0] if att["reasons"] else None,
                    "recommended_action": att["recommended_action"],
                })
            elif kind == "ambiguous":
                seen.update(x["id"] for x in cands)
                item.update({
                    "component_id": None, "candidates": [x["id"] for x in cands],
                    "label": type_name, "attention_level": "unknown",
                    "resource_status": None, "visual_category": None,
                    "reason": "Подходит несколько узлов карточки — выберите нужный",
                    "recommended_action": None,
                })
            else:
                item.update({
                    "component_id": None, "candidates": None, "label": type_name,
                    "attention_level": "unknown", "resource_status": None,
                    "visual_category": None,
                    "reason": "Узел не найден в карточке оборудования",
                    "recommended_action": None,
                })
            detections.append(item)

    not_in_frame = [c["id"] for c in card.components
                    if c["type"] in DETECTABLE_TYPES and c["id"] not in seen]
    return {"detections": detections, "not_in_frame": not_in_frame}
