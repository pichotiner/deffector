import json

import httpx
import numpy as np
import pytest
from PIL import Image

from app.analyzer import Analyzer
from app.config import load_settings

GOOD = {
    "image_quality": "ok",
    "signs": ["leak"],
    "category": "possible_defect",
    "explanation": "Под фланцем видны тёмные подтёки.",
    "recommendation": "Проверить герметичность соединения.",
    "assessment_confidence": 0.85,
}


def sharp_image():
    rng = np.random.default_rng(0)
    return Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))


def make_analyzer(handler):
    analyzer = Analyzer(load_settings())
    analyzer._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama")
    return analyzer


def reply(content):
    return httpx.Response(200, json={"message": {"content": content if isinstance(content, str) else json.dumps(content)}})


def test_good_answer_and_request_shape():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return reply(GOOD)

    result = make_analyzer(handler).analyze(sharp_image(), "flange", "Фланец напорный")
    assert result.as_dict() == {
        "category": "possible_defect",
        "signs": ["течь/подтёки"],
        "explanation": "Под фланцем видны тёмные подтёки.",
        "recommendation": "Проверить герметичность соединения.",
        "assessment_confidence": 0.85,
        "image_quality": "ok",
    }
    body = seen[0]
    assert body["options"]["temperature"] == 0 and body["options"]["seed"] == 0
    assert body["format"]["properties"]["category"]["enum"] == [
        "no_visible_issues", "check_recommended", "possible_defect"]
    assert "Фланец напорный" in body["messages"][1]["content"]
    assert "Фланцевое соединение" in body["messages"][1]["content"]
    assert len(body["messages"][1]["images"]) == 1


def test_retry_once_on_bad_format():
    calls = []

    def handler(request):
        calls.append(1)
        return reply("это не json") if len(calls) == 1 else reply(GOOD)

    result = make_analyzer(handler).analyze(sharp_image(), "flange", "Фланец")
    assert len(calls) == 2 and result.category == "possible_defect"


def test_two_bad_answers_give_fallback():
    calls = []

    def handler(request):
        calls.append(1)
        return reply({"category": "fine"})

    result = make_analyzer(handler).analyze(sharp_image(), "flange", "Фланец")
    assert len(calls) == 2
    assert result.category == "check_recommended"
    assert result.explanation == "Автоматический анализ не выполнен."


def test_timeout_gives_fallback_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    result = make_analyzer(handler).analyze(sharp_image(), "flange", "Фланец")
    assert len(calls) == 1
    assert result.explanation == "Автоматический анализ не выполнен."


def test_ollama_down_gives_fallback():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    assert make_analyzer(handler).analyze(sharp_image(), "valve", "Задвижка").category == "check_recommended"


@pytest.mark.parametrize(
    "image, word",
    [
        (Image.new("RGB", (400, 300), (5, 5, 5)), "тёмный"),
        (Image.new("RGB", (400, 300), (128, 128, 128)), "смазан"),
        (Image.new("RGB", (40, 30), (128, 128, 128)), "мелкий"),
    ],
)
def test_poor_image_skips_model(image, word):
    def handler(request):
        raise AssertionError("модель не должна вызываться для плохого снимка")

    result = make_analyzer(handler).analyze(image, "valve", "Задвижка")
    assert result.category == "check_recommended"
    assert result.image_quality == "poor"
    assert word in result.explanation


def test_model_says_no_issues_on_good_image():
    answer = dict(GOOD, signs=[], category="no_visible_issues", explanation="Узел полностью исправен.")
    result = make_analyzer(lambda r: reply(answer)).analyze(sharp_image(), "valve", "Задвижка")
    assert result.category == "no_visible_issues"
    assert result.explanation == "На снимке узла «Задвижка» видимых проблем не обнаружено."


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>не Ollama</html>"),
        httpx.Response(200, json={"message": "строка вместо объекта"}),
        httpx.Response(200, json=[1, 2, 3]),
    ],
)
def test_garbage_from_ollama_is_cautious_answer(response):
    result = make_analyzer(lambda request: response).analyze(sharp_image(), "flange", "Фланец")
    assert result.category == "check_recommended"


def test_retry_gets_more_tokens():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["options"]["num_predict"])
        return reply("{обрезанный ответ" if len(seen) == 1 else GOOD)

    result = make_analyzer(handler).analyze(sharp_image(), "flange", "Фланец")
    assert result.category == "possible_defect" and seen == [300, 600]


def test_check_ready_garbage_is_clear_error():
    analyzer = make_analyzer(lambda request: httpx.Response(200, text="не json"))
    with pytest.raises(RuntimeError, match="не Ollama"):
        analyzer.check_ready()
