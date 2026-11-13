"""Поиск оборудования по QR, серийному номеру и маркировке (ТЗ 4.1)."""

import difflib

# Типичные ошибки распознавания текста: буква ↔ похожая цифра.
_OCR = str.maketrans("OISBZ", "01582")


def normalize(s):
    """Без регистра, пробелов и дефисов; O→0, I→1, S→5, B→8, Z→2."""
    s = "".join(ch for ch in (s or "") if ch.isalnum()).upper()
    return s.translate(_OCR)


def find(equipment, qr=None, serial=None, marking=None):
    # 1. QR — точное совпадение
    if qr is not None:
        for eq in equipment:
            if qr.strip() == eq["qr_code"]:
                return {"found": True, "equipment_id": eq["id"], "matched_by": "qr",
                        "match_confidence": 1.0}

    # 2. Номер — с допуском. Содержимое чужого QR тоже пробуем как номер.
    tries = [("serial", serial, "serial_number"), ("marking", marking, "marking")]
    if qr is not None:
        tries += [("qr", qr, "serial_number"), ("qr", qr, "marking")]
    for by, value, field in tries:
        if value is None or not normalize(value):
            continue
        for eq in equipment:
            if eq[field] and normalize(value) == normalize(eq[field]):
                exact = value.strip().upper() == eq[field].upper()
                return {"found": True, "equipment_id": eq["id"], "matched_by": by,
                        "match_confidence": 1.0 if exact else 0.93}

    # 3. Не нашли — похожие варианты
    query = normalize(serial or marking or qr)
    suggestions = []
    for eq in equipment:
        score = max(difflib.SequenceMatcher(None, query, normalize(eq[f])).ratio()
                    for f in ("qr_code", "serial_number", "marking") if eq[f])
        if score >= 0.4:
            suggestions.append({"equipment_id": eq["id"], "name": eq["name"], "score": round(score, 2)})
    suggestions.sort(key=lambda s: -s["score"])
    return {"found": False, "suggestions": suggestions}


def search(equipment, q):
    ql = (q or "").strip().lower()
    qn = normalize(q)
    out = []
    for eq in equipment:
        text_hit = not ql or any(ql in str(eq[f] or "").lower()
                                 for f in ("id", "name", "model", "serial_number", "marking", "location"))
        num_hit = bool(qn) and any(qn in normalize(eq[f]) for f in ("serial_number", "marking"))
        if text_hit or num_hit:
            out.append({k: eq[k] for k in ("id", "name", "model", "serial_number", "marking", "location")})
    return out
