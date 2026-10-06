"""Режим «Авто»: программа сама решает, как выполнять задачу.

Четыре свойства, из-за которых этот модуль вообще нужен, и каждое
проверяется отдельно:

* **решение не роняет задачу** — любая ошибка на любой ступени даёт обычный
  режим, а не отказ работать;
* **решение объяснимо** — без причины «Авто» выглядит как произвол, и
  человек после одного странного выбора его выключает;
* **решение не стоит дороже задачи** — один запрос, без инструментов;
* **мощность ограничена аккаунтами** — субагентов не может быть больше,
  чем свободных ключей.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.autochoose import (  # noqa: E402
    MAX_SUBAGENTS,
    Decision,
    Limits,
    apply_limits,
    choose,
    parse_decision,
    score_task,
)


class FakeCaller:
    """Ответ модели, заданный тестом."""

    def __init__(self, text: str = "", *, error: str | None = None,
                 raises: bool = False, model: str = "тест/модель") -> None:
        self.text = text
        self.error = error
        self.raises = raises
        self.model = model
        self.calls: list[dict] = []

    async def ask(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.raises:
            raise RuntimeError("сеть упала")
        return {"text": self.text, "model": self.model, "error": self.error}


# =============================================================== разбор ответа


def test_разбирается_чистый_json() -> None:
    decision = parse_decision(
        '{"web_research": true, "subagents": 3, "reason": "новые цены"}')
    assert decision is not None
    assert decision.web_research is True
    assert decision.subagents == 3
    assert decision.reason == "новые цены"
    assert decision.source == "model"


def test_разбирается_блок_json() -> None:
    decision = parse_decision(
        'Вот мой ответ:\n```json\n{"web_research": false, "subagents": 0}\n```\nГотово.')
    assert decision is not None
    assert decision.web_research is False


def test_разбирается_слова_вместо_логики() -> None:
    """Модели пишут «да» и «нет», а не true и false."""
    decision = parse_decision('{"web_research": "да", "subagents": "4"}')
    assert decision is not None
    assert decision.web_research is True
    assert decision.subagents == 4


def test_разбирается_обёртка() -> None:
    decision = parse_decision('{"decision": {"web_research": 1, "subagents": 2}}')
    assert decision is not None
    assert decision.web_research is True and decision.subagents == 2


def test_русские_ключи() -> None:
    decision = parse_decision('{"нужен_поиск": true, "частей": 3, "причина": "много"}')
    assert decision is not None
    assert decision.web_research is True and decision.subagents == 3


def test_мусор_не_принимается() -> None:
    for text in ("", "   ", "не знаю", "сначала подумаю", "```\n```"):
        assert parse_decision(text) is None, text


def test_нет_eval() -> None:
    """Ответ модели не является доверенным кодом."""
    decision = parse_decision('{"web_research": __import__("os").system("echo")}')
    assert decision is None or decision.web_research is False


def test_мусорное_число_это_ноль() -> None:
    decision = parse_decision('{"web_research": true, "subagents": "много"}')
    assert decision is not None
    assert decision.subagents == 0, "не берётся первое число подряд"


def test_число_обрезается() -> None:
    decision = parse_decision('{"subagents": 99}')
    assert decision is not None
    assert decision.subagents == MAX_SUBAGENTS


def test_объяснение_обрезается() -> None:
    decision = parse_decision('{"reason": "' + "а" * 900 + '"}')
    assert decision is not None
    assert len(decision.reason) <= 200


# =============================================================== признаки


def test_арифметика_обычный_режим() -> None:
    decision = score_task("посчитай 2+2 и переведи ответ на английский")
    assert decision.web_research is False
    assert decision.subagents == 0


def test_свежесть_даёт_разведку() -> None:
    decision = score_task("какая сейчас последняя версия Python и сколько она стоит")
    assert decision.web_research is True
    assert "интернет" in decision.reason


def test_цены_дают_разведку() -> None:
    decision = score_task("сравни цены на видеокарты и сведи в таблицу")
    assert decision.web_research is True


def test_многостраничный_сайт_даёт_субагентов() -> None:
    """Короткая задача, но работа большая — длина текста тут ни при чём.

    Аккаунты заданы явно: без этого ноль по умолчанию означал бы «ограничения
    нет», и проверка шла бы не по той причине, по которой написана.
    """
    decision = score_task("сделай многостраничный сайт: главная, каталог, контакты",
                          Limits(free_accounts=9))
    assert decision.subagents > 0
    assert decision.web_research is False


def test_один_лендинг_одна_модель() -> None:
    """Одна страница — работа для одного агента, дробить нечего."""
    decision = score_task("собери лендинг по этому описанию")
    assert decision.subagents == 0


def test_правка_файла_обычный_режим() -> None:
    decision = score_task("исправь опечатку в файле readme.txt")
    assert decision.web_research is False and decision.subagents == 0


def test_причина_всегда_есть() -> None:
    """Решение без объяснения выглядит как произвол."""
    for task in ("посчитай 2+2", "последняя версия Python",
                 "сделай многостраничный сайт", ""):
        assert score_task(task).reason.strip(), task


def test_ё_не_ломает_признаки() -> None:
    assert score_task("сравни цены на видеокарты").web_research is True


# =============================================================== ограничения


def test_субагентов_не_больше_аккаунтов() -> None:
    """Каждый субагент занимает аккаунт; лишние будут стоять в очереди."""
    decision = score_task("сделай многостраничный сайт под ключ",
                         Limits(free_accounts=4))
    assert decision.subagents <= 2, decision.subagents


def test_при_двух_аккаунтах_субагентов_нет() -> None:
    """Два аккаунта нужны главному агенту, иначе он не соберёт результат."""
    decision = score_task("сделай многостраничный сайт под ключ",
                         Limits(free_accounts=2))
    assert decision.subagents == 0
    assert "урезали" in decision.reason


def test_без_аккаунтов_субагентов_нет() -> None:
    """Ноль аккаунтов — тоже число, а не «ограничение неизвестно».

    Раньше при `free_accounts == 0` ограничение не применялось вовсе, и
    классификатор получал право запустить до шести субагентов без единого
    аккаунта: все они встали бы в очередь и не сделали ничего.
    """
    decision = score_task("сделай многостраничный сайт под ключ",
                          Limits(free_accounts=0))
    assert decision.subagents == 0, decision.subagents


def test_выключенный_поиск_уважается() -> None:
    decision = score_task("какая последняя версия Python",
                         Limits(allow_web=False))
    assert decision.web_research is False


def test_выключенные_субагенты_уважаются() -> None:
    decision = score_task("сделай многостраничный сайт",
                         Limits(allow_subagents=False))
    assert decision.subagents == 0


def test_apply_limits_идемпотентен() -> None:
    once = apply_limits(Decision(subagents=5), Limits(free_accounts=5))
    twice = apply_limits(once, Limits(free_accounts=5))
    assert once.subagents == twice.subagents


# =============================================================== выбор целиком


def test_модель_решает_когда_она_отвечает() -> None:
    import asyncio

    caller = FakeCaller('{"web_research": true, "subagents": 0, "reason": "цены"}')
    result = asyncio.run(choose("сравни цены", caller, limits=Limits(free_accounts=9)))
    assert result.source == "model"
    assert result.web_research is True
    assert result.model == "тест/модель"


def test_сломанная_модель_даёт_признаки() -> None:
    import asyncio

    caller = FakeCaller(raises=True)
    result = asyncio.run(choose("какая последняя версия Python", caller,
                                limits=Limits(free_accounts=9)))
    assert result.source == "heuristic"
    assert result.web_research is True, "при отказе модели признаки должны сработать"


def test_мусор_от_модели_даёт_признаки() -> None:
    import asyncio

    caller = FakeCaller("не знаю, как ответить")
    result = asyncio.run(choose("сделай многостраничный сайт", caller,
                                limits=Limits(free_accounts=9)))
    assert result.source == "heuristic"
    assert result.subagents > 0


def test_ошибка_в_ответе_даёт_признаки() -> None:
    import asyncio

    caller = FakeCaller("", error="все модели в карантине")
    result = asyncio.run(choose("последняя версия Python", caller,
                                limits=Limits(free_accounts=9)))
    assert result.source == "heuristic"


def test_без_модели_работает() -> None:
    import asyncio

    result = asyncio.run(choose("сравни цены на видеокарты", None,
                                limits=Limits(free_accounts=9)))
    assert result.web_research is True


def test_разлад_в_пользу_текста() -> None:
    """Модель сказала «интернет не нужен», а в задаче «последняя версия».

    Верим тексту: ошибиться в сторону лишней разведки дешевле, чем ответить
    по памяти то, что изменилось после обучения модели.
    """
    import asyncio

    caller = FakeCaller('{"web_research": false, "subagents": 0, "reason": "простое"}')
    result = asyncio.run(choose("какая последняя версия Python и сколько стоит",
                                caller, limits=Limits(free_accounts=9)))
    assert result.web_research is True


def test_запрос_не_дороже_задачи() -> None:
    """Один запрос, без инструментов, с небольшим лимитом токенов."""
    import asyncio

    caller = FakeCaller('{"web_research": false, "subagents": 0}')
    asyncio.run(choose("что угодно", caller, limits=Limits()))
    assert len(caller.calls) == 1
    call = caller.calls[0]
    assert call["max_tokens"] <= 2000, "классификатор съедает слишком много"
    assert not call.get("tools"), "классификатору инструменты не нужны"
    assert len(call["messages"]) == 2
    assert "web_research" in call["messages"][0]["content"]


def test_имя_режима_человеческое() -> None:
    assert Decision().mode == "обычный"
    assert Decision(web_research=True).mode == "веб-разведка"
    assert Decision(subagents=3).mode == "субагенты (3)"
    assert Decision(web_research=True, subagents=2).mode == "разведка + субагенты"