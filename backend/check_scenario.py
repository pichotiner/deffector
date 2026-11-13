"""Проверка всего сценария одной командой (план, раздел 6.1, п. 1).

    python backend/check_scenario.py
    python backend/check_scenario.py --image demo/photos/pump.jpg   # снимок для ИИ
    python backend/check_scenario.py --url http://192.168.1.20:8000

Проходит через бэкенд все 10 шагов сценария ТЗ так же, как это делает телефон,
и в конце пишет «ВСЁ РАБОТАЕТ» или какие шаги не прошли. Нужен только Python —
окружение бэкенда не требуется.

Когда запускать: на контроле 2, после холодной перезагрузки без интернета, утром перед
защитой. Проверка пишет в базу (анализ и запись осмотра), поэтому в конце база
сбрасывается к демо-данным — если бэкенд на этом же ПК. Отключить: --no-reset.
"""

import argparse
import base64
import json
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

BACKEND = Path(__file__).resolve().parent
ROOT = BACKEND.parent

# Серый кадр 64×48 — если снимок не указан. ИИ на нём ничего не найдёт: это проверка связи.
_GRAY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4"
    "UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2Nj"
    "Y2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAwAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcI"
    "CQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRol"
    "JicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAA"
    "AAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLR"
    "ChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaX"
    "mJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEA"
    "PwAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD/2Q==")

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # только локальная сеть


class Check:
    def __init__(self, base, image):
        self.base = base.rstrip("/")
        self.image = image
        self.failed, self.warnings = [], []
        self.step = ""

    # ---------- HTTP ----------

    def call(self, method, path, json_body=None, form=None, image=False, timeout=30):
        url = self.base + path
        headers, data = {}, None
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif image:
            b = uuid.uuid4().hex
            parts = [f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                     for k, v in (form or {}).items()]
            parts += [f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"f.jpg\"\r\n"
                      f"Content-Type: image/jpeg\r\n\r\n".encode(), self.image, f"\r\n--{b}--\r\n".encode()]
            data = b"".join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={b}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        t = time.perf_counter()
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                body, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            body, status = e.read(), e.code
        ms = (time.perf_counter() - t) * 1000
        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError:
            payload = {"raw": body[:200].decode("utf-8", "replace")}
        return status, payload, ms

    # ---------- вывод ----------

    def title(self, text):
        self.step = text
        print(f"\n{text}")

    def ok(self, text):
        print(f"  [OK] {text}")

    def warn(self, text):
        print(f"  [!!] {text}")
        self.warnings.append(f"{self.step}: {text}")

    def fail(self, text):
        print(f"  [XX] {text}")
        self.failed.append(f"{self.step}: {text}")

    def expect(self, cond, good, bad):
        (self.ok if cond else self.fail)(good if cond else bad)
        return cond


def internet_available():
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53), ("77.88.8.8", 53)):
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            continue
    return False


def run(c: Check, eq="PU-001"):
    # ---- связь ----
    c.title("Связь")
    try:
        st, h, ms = c.call("GET", "/api/health", timeout=5)
    except OSError as e:
        c.fail(f"бэкенд не отвечает по адресу {c.base}: {e}")
        return
    c.expect(st == 200, f"бэкенд отвечает ({ms:.0f} мс)", f"бэкенд: код {st}")
    ai = h.get("ai", {})
    if ai.get("mode") == "stub":
        c.warn("ИИ в режиме заглушки — на защите нужен настоящий ИИ: python stand.py без --stub")
    else:
        c.expect(ai.get("status") == "ok", "ИИ-сервис отвечает", "ИИ-сервис не отвечает — запустите его")
    real_ai = ai.get("mode") == "real"
    print(f"  [..] интернет на этом ПК: {'ЕСТЬ' if internet_available() else 'нет'}"
          " (для проверки без интернета должно быть «нет»)")

    # ---- 1–2. идентификация ----
    c.title("Шаги 1–2. Идентификация оборудования")
    st, r, _ = c.call("GET", "/api/equipment")
    c.expect(st == 200 and len(r.get("items", [])) >= 2, "ручной выбор: список оборудования",
             f"список оборудования: {st} {r}")
    st, r, _ = c.call("GET", f"/api/equipment/lookup?qr={quote('KST:PU-001')}")
    c.expect(r.get("found") and r.get("equipment_id") == eq, "по QR-коду", f"по QR-коду: {r}")
    st, r, _ = c.call("GET", f"/api/equipment/lookup?serial={quote('sn 2021-OO4587')}")
    c.expect(r.get("found") and r.get("equipment_id") == eq,
             "по серийному номеру (с ошибками распознавания O/0)", f"по серийному номеру: {r}")
    st, r, _ = c.call("GET", "/api/equipment/lookup?marking=PU-001")
    c.expect(r.get("found") and r.get("equipment_id") == eq, "по маркировке", f"по маркировке: {r}")
    st, r, ms = c.call("POST", "/api/identify/image", image=True)
    if st == 200:
        c.ok(f"по изображению: ответ за {ms:.0f} мс, кандидатов {len(r.get('candidates', []))}")
        if real_ai and not r.get("recognized"):
            c.warn("по изображению: оборудование не распознано на этом снимке (укажите --image)")
    else:
        c.fail(f"по изображению: код {st} {r.get('error', r)}")

    # ---- 3. карточка ----
    c.title("Шаг 3. Цифровая карточка")
    st, card, ms = c.call("GET", f"/api/equipment/{eq}")
    if not c.expect(st == 200, f"карточка загружена ({ms:.0f} мс)", f"карточка: код {st}"):
        return
    comps = card.get("components", [])
    c.expect(card.get("model") and comps, f"модель {card.get('model')}, узлов и комплектующих: {len(comps)}",
             "нет модели или состава")
    dev = [p for p in card.get("parameters", []) if p["status"] == "deviation"]
    c.expect(bool(dev), f"сигнализация по отклонениям: {dev[0]['name']} — {dev[0]['message']}" if dev else "",
             "нет параметров с отклонением в демо-данных")
    c.expect(len(card.get("history", [])) >= 6, f"история: {len(card.get('history', []))} записей",
             "история пустая или короткая")

    # ---- 4–5. что проверить ----
    c.title("Шаги 4–5. Узлы, требующие проверки, и подсказка")
    st, att, _ = c.call("GET", f"/api/equipment/{eq}/attention")
    items = att.get("items", [])
    if c.expect(st == 200 and items, f"требуют проверки: {len(items)}", f"список пуст: {st} {att}"):
        first = items[0]
        c.ok(f"первый: {first['name']} — {'; '.join(first['reasons'][:2])}")
        c.expect(first["hint"].startswith("Наведите камеру"), f"подсказка: «{first['hint']}»", "нет подсказки")

    # ---- 6, 8. рамки ----
    c.title("Шаги 6 и 8. Рамки узлов на кадре")
    times, det = [], None
    for _ in range(5):
        st, det, ms = c.call("POST", f"/api/equipment/{eq}/detect", image=True)
        if st != 200:
            break
        times.append(ms)
    if c.expect(st == 200, f"detect отвечает, в среднем {sum(times) / len(times):.0f} мс"
                if times else "", f"detect: код {st} {det.get('error', det)}"):
        avg = sum(times) / len(times)
        if avg > 333:
            c.warn(f"detect медленнее 3 кадров в секунду ({avg:.0f} мс)")
        ds = det["detections"]
        if ds:
            d = ds[0]
            c.ok(f"рамок: {len(ds)}; {d['label']} — {d['attention_level']}, «{d['reason']}»")
            c.expect(all(x["attention_level"] and x["label"] for x in ds),
                     "у каждой рамки есть цвет и подпись", "у рамки нет цвета или подписи")
        elif real_ai:
            c.warn("на снимке не найдено ни одного узла — укажите снимок оборудования: --image")
        else:
            c.fail("заглушка ИИ не вернула рамок")

    # ---- 6. анализ узла ----
    c.title("Шаг 6. Визуальный анализ узла")
    target = next((i for i in items if i.get("detectable")), None) or {"component_id": "C-02"}
    cid = target["component_id"]
    st, comp, ms = c.call("POST", f"/api/equipment/{eq}/components/{cid}/analyze", image=True,
                          form={"detection_confidence": "0.9"}, timeout=40)
    if c.expect(st == 200, f"анализ {cid} за {ms / 1000:.1f} с", f"анализ: код {st} {comp.get('error', comp)}"):
        v = comp["visual"]
        c.expect(v["category"] in ("no_visible_issues", "check_recommended", "possible_defect"),
                 f"категория: {v['category']}; {v['explanation']}", f"категория не из ТЗ: {v['category']}")
        c.expect(bool(v.get("disclaimer")), "оговорка о предварительном осмотре есть", "нет оговорки")
        if ms > 15000:
            c.warn("анализ дольше 15 секунд")

    # ---- 7, 9. карточка узла ----
    c.title("Шаги 7 и 9. Сопоставление с данными и карточка узла")
    st, comp, _ = c.call("GET", f"/api/equipment/{eq}/components/C-02")
    if c.expect(st == 200, "карточка узла C-02 загружена", f"карточка узла: код {st}"):
        c.expect(all(k in comp for k in ("normative", "resource", "visual")),
                 "три раздельных блока: норматив, расчётный ресурс, визуальный анализ", "блоки смешаны")
        c.ok(f"ресурс: {comp['resource']['message']}; {comp['resource']['basis']}")
        c.expect(bool(comp["attention"]["recommended_action"]),
                 f"рекомендуемое действие: {comp['attention']['recommended_action']}", "нет рекомендации")
        c.expect(comp.get("last_maintenance_at") and comp.get("characteristics"),
                 f"последнее обслуживание {comp['last_maintenance_at']}, характеристики есть",
                 "нет даты обслуживания или характеристик")
    st, c5, _ = c.call("GET", f"/api/equipment/{eq}/components/C-05")
    if st == 200 and c5["resource"]["status"] == "insufficient_data":
        c.ok("нехватка данных указана явно (C-05)")
    elif st == 200:
        c.warn(f"C-05: ожидалось «недостаточно данных», пришло {c5['resource']['status']}")

    # ---- 10. запись осмотра ----
    c.title("Шаг 10. Фиксация выполненных работ")
    st, r, _ = c.call("POST", f"/api/equipment/{eq}/inspections",
                      json_body={"component_id": "C-02", "type": "defect", "comment": ""})
    c.expect(st == 422, "дефект без описания отклонён", f"дефект без описания: код {st}")
    st, r, _ = c.call("POST", f"/api/equipment/{eq}/inspections", json_body={
        "component_id": "C-02", "type": "checked", "comment": "Проверка сценария",
        "performed_by": "check_scenario", "attach_last_visual": True})
    if c.expect(st == 201, "запись «компонент проверен» сохранена", f"запись осмотра: код {st} {r}"):
        st, h, _ = c.call("GET", f"/api/equipment/{eq}/history")
        c.expect(h["items"][0]["id"] == r["inspection"]["id"], "запись видна в истории первой",
                 "записи нет в истории")


def is_local(url):
    host = urlparse(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        return host in socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser(description="Проверка сценария через бэкенд")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--image", help="JPEG со снимком оборудования для ИИ")
    ap.add_argument("--no-reset", action="store_true", help="не сбрасывать базу в конце")
    args = ap.parse_args()

    image = Path(args.image).read_bytes() if args.image else _GRAY_JPEG
    c = Check(args.url, image)
    print(f"Проверка сценария: {args.url}" + ("" if args.image else "  (снимок не указан — серый кадр)"))
    started = time.perf_counter()
    try:
        run(c)
    except Exception as e:  # noqa: BLE001 — любая неожиданность = провал проверки
        c.fail(f"проверка прервалась: {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    if not args.no_reset and is_local(args.url):
        sys.path.insert(0, str(BACKEND))
        try:
            from app import seed
            seed.main([])
        except Exception as e:  # noqa: BLE001
            print(f"[!!] базу сбросить не удалось ({e}) — выполните python backend/reset_db.py")
    elif not args.no_reset:
        print("Бэкенд на другом ПК — сбросьте базу там: python backend/reset_db.py")

    for w in c.warnings:
        print(f"[!!] {w}")
    if c.failed:
        print(f"НЕ ПРОШЛО ({len(c.failed)}):")
        for f in c.failed:
            print(f"  [XX] {f}")
        print(f"Время проверки: {time.perf_counter() - started:.0f} с")
        return 1
    print(f"ВСЁ РАБОТАЕТ — сценарий проходит. Время проверки: {time.perf_counter() - started:.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
