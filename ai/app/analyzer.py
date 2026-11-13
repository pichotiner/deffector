"""Оценка видимых дефектов узла мультимодальной моделью через Ollama."""
from __future__ import annotations

import base64
import json
import logging
import time

import httpx
from PIL import Image

from . import rules
from .config import Settings
from .images import check_quality, resize_max_side, to_jpeg

log = logging.getLogger("ai.analyzer")

ANSWER_SCHEMA = {
    "type": "object",
    # порядок полей задаёт порядок ответа: сначала описание увиденного, затем выводы
    "properties": {
        "explanation": {"type": "string"},
        "image_quality": {"type": "string", "enum": ["ok", "poor"]},
        "signs": {"type": "array", "items": {"type": "string", "enum": list(rules.SIGNS)}},
        "category": {"type": "string", "enum": list(rules.CATEGORIES)},
        "recommendation": {"type": "string"},
        "assessment_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["explanation", "image_quality", "signs", "category", "recommendation", "assessment_confidence"],
}

SYSTEM_PROMPT = """Ты помогаешь инженеру при предварительном визуальном осмотре промышленного оборудования. \
Тебе показывают снимок одного узла. Опиши только то, что видно на изображении.

Ищи только такие признаки:
- corrosion — коррозия: ржавчина, рыжие или бурые пятна, вздутие и отслоение краски от ржавчины;
- leak — течь или подтёки: капли, мокрые пятна, потёки масла или воды, белый налёт солей, лужа под узлом;
- mechanical_damage — механическое повреждение: трещина, вмятина, скол, разбитое стекло, погнутая, \
сломанная или оторванная деталь, повреждённая изоляция кабеля;
- overheating — следы перегрева (только для электродвигателя): потемневшая, бурая, жёлтая или \
радужная краска у щитов и клеммной коробки, оплавленная или обугленная изоляция, дым.

Ответь одним объектом JSON с полями в таком порядке:
- explanation: одно-два предложения на русском — что именно и где видно на изображении;
- image_quality: "ok", если узел можно рассмотреть; "poor" — только если снимок смазан, слишком тёмный, \
узел закрыт или слишком мелкий и рассмотреть его нельзя;
- signs: список найденных признаков из трёх перечисленных; пустой список, если их не видно;
- category:
  "possible_defect" — признак виден явно;
  "check_recommended" — признак есть, но он сомнительный, либо снимок плохой;
  "no_visible_issues" — снимок хороший и ни одного признака не видно;
- recommendation: одно предложение на русском — что проверить дальше при осмотре на месте;
- assessment_confidence: число от 0 до 1 — насколько ты уверен в своей оценке.

Строгие ограничения:
- не ставь диагноз и ничего не утверждай о внутреннем состоянии узла: по снимку его не видно;
- не пиши, что узел исправен, в порядке, в норме или что дефектов нет; если признаков не видно, пиши \
«видимых проблем не обнаружено»;
- не назначай ремонт или замену — только что проверить;
- при плохом снимке никогда не выбирай "no_visible_issues";
- грязь, пыль и обычные потёртости краски признаками не считай;
- не выдумывай признаки: называй только то, что действительно различимо на снимке."""


def build_user_prompt(component_type_name: str, component_name: str) -> str:
    return (
        f"Узел: {component_name}. Тип узла: {component_type_name}. "
        "Оцени видимые признаки на снимке и ответь в формате JSON."
    )


class Analyzer:
    def __init__(self, settings: Settings):
        self.settings = settings
        # trust_env=False: обращаемся только к локальному Ollama, системные прокси не используем
        self._client = httpx.Client(base_url=settings.ollama_url, trust_env=False)

    @property
    def name(self) -> str:
        return self.settings.vlm_model

    def close(self) -> None:
        self._client.close()

    def check_ready(self) -> None:
        """Проверяет, что Ollama отвечает и модель скачана. Иначе — исключение с понятным текстом."""
        try:
            response = self._client.get("/api/tags", timeout=5)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama не отвечает по адресу {self.settings.ollama_url}") from exc
        names = {m.get("name", "") for m in response.json().get("models", [])}
        wanted = self.settings.vlm_model
        if wanted not in names and f"{wanted}:latest" not in names:
            raise RuntimeError(f"Модель {wanted} не скачана в Ollama. Запустите python ai/install.py")

    def warmup(self) -> None:
        """Загружает модель в видеопамять, чтобы первый запрос не ждал."""
        image = Image.new("RGB", (224, 224), (120, 120, 120))
        self._ask(image, "узел", "узел", timeout=300.0)

    def _ask(self, image: Image.Image, type_name: str, component_name: str, timeout: float) -> dict:
        payload = {
            "model": self.settings.vlm_model,
            "stream": False,
            "format": ANSWER_SCHEMA,
            "keep_alive": -1,  # не выгружать модель из памяти между запросами
            "options": {
                "temperature": 0,  # нулевая случайность: один снимок — один ответ
                "seed": 0,
                "top_k": 1,
                "num_predict": 300,
                "num_ctx": self.settings.vlm_num_ctx,
            },
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(type_name, component_name),
                    "images": [base64.b64encode(to_jpeg(image)).decode("ascii")],
                },
            ],
        }
        response = self._client.post("/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise rules.FormatError("ответ модели не является JSON") from exc

    def analyze(self, image: Image.Image, component_type: str, component_name: str) -> rules.Assessment:
        settings = self.settings
        name = component_name.strip() or "узел"
        spec = settings.classes.get(component_type)
        type_name = spec.name if spec else (component_type.strip() or "узел")

        quality = check_quality(image, settings.min_side_px, settings.min_brightness, settings.min_sharpness)
        if not quality.ok:
            return rules.poor_quality(quality.reason)

        prepared = resize_max_side(image, settings.vlm_image_side)
        deadline = time.monotonic() + settings.analyze_timeout_s
        for attempt in (1, 2):  # при сбое формата — один повтор
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                break
            try:
                raw = self._ask(prepared, type_name, name, timeout=remaining)
                return rules.enforce(rules.parse_model_answer(raw), name, component_type)
            except rules.FormatError as exc:
                log.warning("Ответ модели не по формату (попытка %d): %s", attempt, exc)
            except httpx.TimeoutException:
                log.warning("Модель не ответила за %.0f с", settings.analyze_timeout_s)
                break
            except httpx.HTTPError as exc:
                log.error("Ошибка обращения к Ollama: %s", exc)
                break
        return rules.analysis_failed()
