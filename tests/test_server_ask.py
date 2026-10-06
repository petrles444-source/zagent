"""POST /api/ask: обработчик обязан дойти до воркера.

Раньше `_run()` читал `Handler.api` — атрибут базового класса, которому никто
не присваивал значение: `api` жил на динамическом подклассе. Итог — 500 на
любой вопрос при работающем воркере, то есть «агент не отвечает».
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from hub.server import ApiServer, Handler, _run


class _FakeWorker:
    """Воркер с настоящим loop и селектором-заглушкой."""

    def __init__(self, loop: Any) -> None:
        self.loop = loop
        self.selector = object()
        self.last_error = None


def test_run_берёт_loop_из_воркера() -> None:
    """Главное: loop берётся у того воркера, которому его передали.

    Именно так устроен сервер: HTTP-обработчик живёт в своём потоке, а
    корутину надо выполнить в loop'е воркера.
    """

    async def answer() -> str:
        return "да"

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        assert _run(_FakeWorker(loop), answer()) == "да"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()


def test_run_без_воркера_даёт_понятную_ошибку() -> None:
    async def answer() -> str:
        return "да"

    with pytest.raises(RuntimeError) as exc:
        _run(None, answer())
    assert "воркер" in str(exc.value).lower()


def test_run_закрывает_корутину_без_loop() -> None:
    """Иначе Python предупредит «coroutine was never awaited»."""

    async def answer() -> str:
        return "да"

    coro = answer()
    with pytest.raises(RuntimeError):
        _run(None, coro)
    # Закрытая корутина безопаснее для повторного закрытия.
    coro.close()


def test_run_с_пустым_loop() -> None:
    async def answer() -> str:
        return "да"

    with pytest.raises(RuntimeError):
        _run(_FakeWorker(None), answer())


def test_ask_пустой_запрос_не_доходит_до_сети(tmp_path: Path) -> None:
    """Пустой текст отсекается до создания корутины."""

    handler = Handler.__new__(Handler)
    worker = _FakeWorker(None)
    handler.api = ApiServer(tmp_path, worker)
    out = Handler._ask(handler, {"text": "   "})
    assert out["ok"] is False
    assert "пустой" in out["error"]


def test_ask_без_селектора_сообщает_про_реестр(tmp_path: Path) -> None:
    handler = Handler.__new__(Handler)

    class _NoSelector:
        loop = None
        selector = None
        last_error = "реестр не собран"

    handler.api = ApiServer(tmp_path, _NoSelector())
    out = Handler._ask(handler, {"text": "привет"})
    assert out["ok"] is False
    assert "реестр" in out["error"]