# План: сравнение моделей ИИ-сервиса на ПК Тимофея, 13–14.11

Для Тимофея и Claude Code на его ПК (RTX 5070 12 ГБ, Windows 11). Цель — проверить, дают ли
более новые модели лучший результат, чем текущие. Код не меняется: модели переключаются
переменными окружения. **Решение и вливание в `main` — до 14.11, 10:00**, чтобы Павел успел
скачать модель на стенд, пока у него есть интернет. Не уверены — оставляем текущие модели:
они проверены (0 пропусков дефектов из 31).

Команды — PowerShell, из корня репозитория.

## 0. Подготовка

Ollama у Тимофея распакована из архива — в каждом новом окне:

```
$env:PATH = "D:\Tim\учеба\hacks\ufa\ollama;" + $env:PATH; $env:OLLAMA_MODELS = "D:\Tim\учеба\hacks\ufa\ollama\models"
```

Папка для отчётов: `mkdir runs` (в git её не добавлять).

## 1. Эталон — текущие модели

Окно 1: `python ai/run.py`, дождаться `"status": "ok"` в `http://127.0.0.1:8001/health`.

Окно 2:

```
ai\.venv\Scripts\python ai/tools/evaluate.py --report runs\base.json
```

Записать из `/health`: `gpu.memory_used_mb`.

## 2. Модель анализа: Qwen3-VL 8B

```
ollama pull qwen3-vl:8b
```

Нужен вариант **instruct**, не thinking (с «рассуждениями» ответ будет в разы дольше) —
проверить имя в библиотеке Ollama и `ollama show qwen3-vl:8b`. Окно 1 — перезапустить сервис:

```
$env:AI_VLM_MODEL="qwen3-vl:8b"; python ai/run.py
```

Окно 2:

```
ai\.venv\Scripts\python ai/tools/evaluate.py --report runs\qwen3vl.json
```

По желанию тем же способом — `gemma3:12b` (`runs\gemma3.json`).

## 3. Детектор: OWLv2 large

Скачать веса (~1,7 ГБ):

```
ai\.venv\Scripts\python -c "from huggingface_hub import snapshot_download; snapshot_download('google/owlv2-large-patch14-ensemble', local_dir='ai/weights/owlv2-large', allow_patterns=['config.json','preprocessor_config.json','model.safetensors','tokenizer_config.json','vocab.json','merges.txt','special_tokens_map.json'])"
```

Окно 1 (модель анализа — прежняя):

```
$env:AI_VLM_MODEL=""; $env:AI_DETECTOR_DIR="owlv2-large"; python ai/run.py
```

Окно 2 — только рамки, быстрее:

```
ai\.venv\Scripts\python ai/tools/evaluate.py --skip-analyze --report runs\owlv2large.json
```

## 4. Когда новая модель лучше — только если всё сразу

| | Сейчас (base) | Условие |
|---|---|---|
| Кадры с дефектом → «видимых проблем не обнаружено» | 0 из 31 | **строго 0** |
| Кадры с лишними признаками | 11 из 31 | меньше |
| Ответы «Автоматический анализ не выполнен» (сбой формата) | 0 | 0 |
| `/analyze`, медиана | 1,6 с | до 3–4 с |
| Фланцы / арматура найдены | 5 из 11 / 8 из 14 | больше |
| Ложных рамок на кадр | 0,46 | не больше |
| `/detect`, медиана | 41 мс | до 200 мс |
| Видеопамять (`/health`) | 7,8 ГБ (8,8 с рабочим столом) | ≤ 12 ГБ у Тимофея; на 16 ГБ у Павла с запасом под звонок |

Сравнение: попросить Claude Code сопоставить `runs\*.json` и записать таблицу «было / стало»
в `ai/README.md`, раздел «Результаты» (дата, ПК, модели).

## 5. Если меняем

- **Модель анализа:** `python ai/install.py --vlm <имя>` — запишет модель в
  `ai/.venv/installed.json`, `run.py` будет брать её сам. Поменять значение по умолчанию
  в `ai/install.py` (`DEFAULT_VLM`), `ai/app/config.py` (`vlm_model`), `ai/run.py` и в
  `ai/README.md` / `docs/qa.md` / слайде 5 — названия модели. Павлу на стенде — тот же
  `install.py --vlm <имя>`.
- **Детектор:** добавить `owlv2-large` в `HF_MODELS` в `ai/install.py` и в `WEIGHT_FILES`
  в `ai/_setup.py`, значение по умолчанию `detector_dir` в `ai/app/config.py`; пороги в
  `ai/classes.json` проверить заново (у large другие уверенности). Павлу — `python ai/install.py`.
- Прогнать `cd ai && .venv\Scripts\python -m pytest`, влить в `main`, написать сообщение
  в `TEAM_MESSAGES.md` (что поменяли, цифры, что сделать Павлу) — **до 10:00**.

## 6. Не делать

- Не дообучать модели и не менять промпт ради новой модели в последний момент без полного
  прогона по набору.
- Не трогать идентификацию (CLIP): работает (свои эталоны 0,999, посторонние ≤ 0,26).
- Не оставлять `AI_VLM_MODEL` / `AI_DETECTOR_DIR` заданными в окне, из которого потом
  запускается обычный стенд.
