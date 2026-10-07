"""Разбор битого тела ответа: провайдер не должен ронять хоп.

Тот же класс дефекта уже закрыт в `providers/zen.py::_extract_text`
(см. tests/test_audit_round5.py) — но девять шлюзов из десяти ходят через
`providers/openai_compat.py`, и там защита стояла только на бумаге: цепочка
`choices[0].get("message") or {}` падала с AttributeError на `choices[0] =
null` или на строке вместо объекта.

Почему это не «мелочь на границе», а дыра: исключение уходило наружу из
`chat()`, то есть из `AutoCaller.ask()` — один кривой ответ одного шлюза
ронял не одну модель, а весь хоп, и вместо «пустой ответ модели» в отчёт
попадала трассировка. Тесты ниже проверяют именно это: провайдер отдаёт
мусор, а программа обязана продолжить работать.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from providers.openai_compat import (  # noqa: E402
    OpenAICompatProvider,
    _extract_reasoning,
    _extract_text,
)


# ------------------------------------------------------- битые тела ответов

@pytest.mark.parametrize("body", [
    {"choices": [None]},
    {"choices": ["строка вместо объекта"]},
    {"choices": [{"message": None}]},
    {"choices": [{"message": "строка вместо словаря"}]},
    {"choices": [{"message": {"content": None}}]},
    {"choices": [{"message": {}}]},
    {"choices": []},
    {},
])
def test_мусор_в_ответе_даёт_пустой_текст(body: dict) -> None:
    """Ни одно из этих тел не имеет права бросить исключение.

    Раньше `choices[0] = None` ронял разбор с AttributeError прямо из
    `chat()` — то есть исключение уходило наружу и обрушивал весь хоп.
    """
    assert _extract_text(body) == ""


@pytest.mark.parametrize("body", [
    {"choices": [None]},
    {"choices": [{"message": None}]},
    {"choices": []},
    {},
])
def test_размышление_тоже_переживает_мусор(body: dict) -> None:
    """Второе место с той же цепочкой: у reasoning-моделей поле отдельное."""
    assert _extract_reasoning(body) == ""


@pytest.mark.parametrize("body, expected", [
    ({"choices": [{"message": {"content": "привет"}}]}, "привет"),
    ({"choices": [{"message": {"content": [{"text": "а"}, {"text": "б"}]}}]}, "аб"),
    ({"choices": [{"message": {"reasoning": "размышляю", "content": ""}}]}, ""),
])
def test_нормальные_тела_читаются(body: dict, expected: str) -> None:
    assert _extract_text(body) == expected


def test_размышление_берётся_из_обоих_полей() -> None:
    assert _extract_reasoning(
        {"choices": [{"message": {"reasoning_content": "думаю"}}]}) == "думаю"


# ------------------------------------------------------------ сквозной путь

@pytest.mark.parametrize("body", [
    {"choices": [None]},
    {"choices": ["строка"]},
    {"choices": [{"message": None}]},
])
def test_chat_на_битом_теле_не_бросает(body: dict) -> None:
    """Самая важная проверка: исключение из `chat()` не выходит наружу.

    Именно на этом стоит вся цепочка failover — если провайдер вместо
    результата отдаст исключение, хоп не продолжится.
    """
    import asyncio

    async def run() -> dict:
        provider = OpenAICompatProvider("openrouter", "https://example.invalid",
                                       "ключ")

        class _Resp:
            status_code = 200
            headers: dict[str, str] = {}
            text = "{}"

            def json(self) -> dict:
                return body

        class _Client:
            async def post(self, *a, **kw):
                return _Resp()

            async def get(self, *a, **kw):
                return _Resp()

            async def aclose(self) -> None:
                return None

        provider._client = _Client()  # noqa: SLF001 — подмена сети в тесте
        provider._owns_client = False  # noqa: SLF001
        try:
            return await provider.chat("m", [{"role": "user", "content": "x"}])
        finally:
            await provider.aclose()

    result = asyncio.run(run())
    # Успех в zagent означает `error is None`, а не флаг `ok`: в провайдере
    # такого ключа нет вообще, и проверять надо по тому, что есть.
    assert result["error"] is None, f"вместо пустого ответа: {result['error']}"
    assert result["text"] == ""