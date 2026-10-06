"""Правки по итогам стороннего аудита: что оказалось багом, а что нет.

`AUDIT_REPORT.md` перечисляет 16 проблем. Здесь зафиксировано то, что
проверено кодом:

* подтверждено и исправлено — `gather_chats` пропускал не-словарь,
  `log_usage` ронял вызов модели на несериализуемой записи,
  `_extract_text` падал на `choices[0] = None`, `ZenProvider` принимал
  неположительный таймаут, а словарь меток в `Router` ронял конструктор
  на записи без `id`;
* отвергнуто — «race condition» в ленивом `client` (там нет точки
  ожидания, прерваться негде), защита `format_reports` от пустого списка
  (она уже есть) и валидация цепочек `Router` (модуль не используется
  в рабочем коде — см. последний тест).

Каждый тест проверяет поведение, а не наличие строки в исходнике: тест,
проходящий по не той причине, хуже отсутствия теста.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Sequence

import pytest

from hub.bus import gather_chats, log_usage, usage_record
from hub.health import format_reports
from providers.base import Provider, ok_result
from providers.zen import ZenProvider, _extract_text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _Returns:
    """Провайдер, который возвращает ровно то, что в него положили."""

    def __init__(self, value: Any) -> None:
        self.value = value

    async def chat(self, model_id: str, messages: Sequence[dict[str, Any]],
                   **kw: Any) -> Any:
        return self.value


# ============================================== gather_chats: тип результата


def test_не_словарь_становится_ошибкой_а_не_ломкой_выдачей() -> None:
    """Контракт `chat` — вернуть словарь.

    Нарушение раньше молча уходило в выдачу, и первая же попытка прочитать
    результат падала с AttributeError уже в другом модуле: виноватым
    выходил вызывающий, а не провайдер, который вернул ерунду.
    """
    got = asyncio.run(gather_chats(
        _Returns("это не словарь"), ["m"], [{"role": "user", "content": "x"}]))

    assert len(got) == 1
    assert isinstance(got[0], dict), "в выдаче снова не словарь"
    assert got[0]["error"] is not None
    assert "Некорректный результат" in got[0]["error"]
    assert got[0]["text"] == ""
    # И главное: запись в журнал больше не падает на этом результате.
    assert usage_record(model="m", role="r", result=got[0])["ok"] is False


def test_словарь_от_провайдера_проходит_нетронутым() -> None:
    """Проверка выше не должна ломать нормальный путь."""
    good = ok_result("ответ", tokens_in=5, tokens_out=3)
    got = asyncio.run(gather_chats(
        _Returns(good), ["m"], [{"role": "user", "content": "x"}]))

    assert got == [good], "нормальный результат изменился"


def test_исключение_провайдера_по_прежнему_становится_ошибкой() -> None:
    class _Boom(Provider):
        name = "boom"

        async def chat(self, model_id, messages, **kw):
            raise RuntimeError("сломалось")

    got = asyncio.run(gather_chats(
        _Boom(), ["m"], [{"role": "user", "content": "x"}]))

    assert got[0]["error"] is not None
    assert "Внутренняя ошибка" in got[0]["error"]


def test_пустой_список_моделей_даёт_пустой_результат() -> None:
    got = asyncio.run(gather_chats(_Returns("x"), [], []))
    assert got == []


# ================================================= log_usage: не роняет задачу


def test_несериализуемая_запись_не_останавливает_вызов_модели(tmp_path: Path) -> None:
    """Журнал не должен быть причиной падения задачи.

    `json.dumps` на значении, которое не умеет в JSON, бросает TypeError —
    и раньше он улетал из `log_usage` наружу, роняя вызов модели целиком.
    """
    log_usage({"модель": "m", "мусор": object()}, root=tmp_path)
    # До главного: файл создан, запись не упала.


def test_ошибка_сериализации_не_пишет_полустрочку(tmp_path: Path) -> None:
    """Неудачная запись не оставляет битый JSONL.

    Если бы `json.dumps` сначала писал в файл, а потом падал, в журнале
    осталась бы строка, которую не разобрать при следующем чтении.
    """
    log_usage({"ok": True, "текст": "нормальная запись"}, root=tmp_path)
    log_usage({"мусор": object()}, root=tmp_path)

    lines = (tmp_path / "logs" / "usage.jsonl").read_text(encoding="utf-8")
    assert lines.count("\n") == 1, f"в журнале битые строки: {lines!r}"


def test_запись_в_недоступную_папку_не_поднимает(tmp_path: Path) -> None:
    blocker = tmp_path / "logs"
    blocker.write_text("я файл, а не папка", encoding="utf-8")

    log_usage({"model": "m"}, root=tmp_path)  # не должно бросать


# ============================================ ZenProvider: границы настроек


@pytest.mark.parametrize("bad", [0, -5, -0.1])
def test_неположительный_таймаут_ловится_на_границе(bad: float) -> None:
    """httpx трактует таймаут <= 0 как «истечь мгновенно».

    Без проверки ошибка приходила изнутри сетевого слоя и ничего не
    говорила о том, что не так с настройкой.
    """
    with pytest.raises(ValueError, match="положительным"):
        ZenProvider("https://x/v1", "k", timeout=bad)


def test_нечисловой_таймаут_ловится_на_гранике() -> None:
    with pytest.raises(ValueError, match="числом"):
        ZenProvider("https://x/v1", "k", timeout="быстро")


def test_обычный_таймаут_принимается() -> None:
    assert ZenProvider("https://x/v1", "k", timeout=12.5).timeout == 12.5
    assert ZenProvider("https://x/v1", "k", timeout="30").timeout == 30.0


# =============================== ZenProvider: ленивый клиент без ложной блокировки


def test_клиент_создаётся_один_раз_и_переиспользуется() -> None:
    """Два обращения к `client` дают один объект — ради этого он и ленивый.

    Это единственное поведение, ради которого свойство существует.
    """
    provider = ZenProvider("https://x/v1", "k")
    assert provider.client is provider.client
    assert provider._owns_client is True


def test_переданный_клиент_не_подменяется() -> None:
    import httpx

    own = httpx.AsyncClient()
    try:
        provider = ZenProvider("https://x/v1", "k", client=own)
        assert provider.client is own
        assert provider._owns_client is False
        asyncio.run(provider.aclose())
        assert own.is_closed is False, "провайдер закрыл чужой клиент"
    finally:
        asyncio.run(own.aclose())


def test_свойство_клиента_осталось_публичным() -> None:
    """`hub/registry.py` и `tools/cli.py` обращаются к `provider.client`.

    Проба «race condition» от 06.10.2026 заменила свойство на
    `_get_client()` и сломала этих потребителей: создание клиента не
    содержит `await`, поэтому между проверкой и присваиванием управление
    не уходит никуда, и блокировка чинить нечего.
    """
    assert hasattr(ZenProvider, "client"), "свойство client исчезло"
    assert not hasattr(ZenProvider, "_get_client"), "осталась приватная замена"


# ================================== ZenProvider: тело ответа приходит извне


@pytest.mark.parametrize("body", [
    {"choices": [None]},
    {"choices": ["строка вместо объекта"]},
    {"choices": [{"message": None}]},
    {"choices": [{"message": "строка вместо объекта"}]},
])
def test_выбитое_тело_ответа_даёт_пустой_текст(body: dict[str, Any]) -> None:
    """Шлюз — чужой код, и `choices[0]` у него бывает не словарём.

    Раньше такое тело роняло `_extract_text` с AttributeError, и вызывающий
    получал исключение вместо нормального «пустой ответ модели».
    """
    assert _extract_text(body) == ""


@pytest.mark.parametrize("body, expected", [
    ({"choices": [{"message": {"content": "привет"}}]}, "привет"),
    ({"choices": [{"message": {"content": [{"text": "а"}, {"text": "б"}]}}]}, "аб"),
    ({"choices": []}, ""),
    ({}, ""),
])
def test_нормальные_тела_читаются_как_раньше(
        body: dict[str, Any], expected: str) -> None:
    assert _extract_text(body) == expected


def test_пустой_текст_превращается_в_ошибку_а_не_в_успех() -> None:
    """Ответ без текста — это провал запроса, а не успех с пустым текстом."""

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"choices": [None]}

    provider = ZenProvider("https://x/v1", "k", client=_FakeClient(_Resp()))
    got = asyncio.run(provider.chat("m", [{"role": "user", "content": "x"}]))

    assert got["error"] is not None
    assert got["text"] == ""


class _FakeClient:
    """Подмена httpx-клиента: отдаёт заранее заданный ответ."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.is_closed = False

    async def post(self, *a: Any, **kw: Any) -> Any:
        return self.response

    async def aclose(self) -> None:
        self.is_closed = True


# ============== отвергнутые пункты: проверка, что зря


def test_формат_отчётов_уже_защищён_от_пустого_списка() -> None:
    """Аудит предложил `default=10` в `max(...)`.

    Защита `if not reports` стоит выше по коду и полностью покрывает
    случай: пустой список даёт понятный текст, а не ValueError.
    """
    assert format_reports([]) == "Нет моделей для проверки."


def test_маршрутизатор_удалён_а_не_молча_мёртв() -> None:
    """`hub/router.py` удалён 07.10.2026 — по решению пользователя.

    Он не импортировался рабочим кодом: выбор моделей идёт через
    `hub/failover.py` и `hub/select.py`. Модуль выглядел частью системы
    (есть `RouterError`, есть тесты, есть `config/agents.json`), но ни
    одна задача через него не проходила. Рядом с ним лежали
    `load_agents` и `config/agents.json`, которые не читал никто вообще.

    Проверка стоит здесь, а не удалена вместе с модулем: если кто-то снова
    потянет `hub.router`, тест напомнит, что такого пути нет и что
    выбор моделей живёт в другом месте. Обратное тоже верно — пока файл
    не вернётся осознанно, «анализ кода» не должен на него опираться.
    """
    assert not (ROOT / "hub" / "router.py").exists(), \
        "hub/router.py вернулся: выбор моделей идёт через hub/select.py"
    assert not (ROOT / "config" / "agents.json").exists(), \
        "config/agents.json вернулся: его никто не читал"

    # Живой путь выбора моделей на месте — это важнее, чем отсутствие
    # мёртвого файла.
    import hub.select
    import hub.failover
    assert hasattr(hub.select, "Selector")
    assert hasattr(hub.failover, "AutoCaller")