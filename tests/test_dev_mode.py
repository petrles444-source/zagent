"""Режим разработчика: переключатель, диагностика, границы режима.

Что проверяется и почему:

* флаг переживает перезапуск — иначе пришлось бы включать его заново
  после каждого «разбил консоль»;
* диагностика показывает то, чего больше нигде не видно (пути, счётчики,
  последняя ошибка, версия Python);
* диагностика НЕ содержит значений ключей — иначе отладочная вкладка
  стала бы самой удобной утечкой ключей в программе;
* режим не включает право править собственный код: `self_edit` выдаётся
  на одну задачу, иначе флаг однажды остался бы включённым навсегда;
* маршрут `/api/dev` существует и в POST, и в GET (интерфейс читает
  состояние тем же маршрутом, которым меняет).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hub.server import ApiServer, Handler
from hub.ui import UI_HTML
from hub.worker import Worker


@pytest.fixture()
def worker(tmp_path: Path) -> Worker:
    return Worker(tmp_path)


class _FakeWorker:
    """Обработчик /api/dev проверяется без настоящего воркера."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[bool | None] = []
        self.on = False

    def dev_info(self) -> dict[str, Any]:
        return {"ok": True, "on": self.on, "root": str(self.root)}

    def set_dev_mode(self, on: bool) -> dict[str, Any]:
        self.calls.append(bool(on))
        self.on = bool(on)
        return self.dev_info()


def handler_for(tmp_path: Path) -> tuple[Handler, _FakeWorker]:
    worker = _FakeWorker(tmp_path)
    handler = Handler.__new__(Handler)
    handler.api = ApiServer(tmp_path, worker)  # type: ignore[arg-type]
    return handler, worker


# ------------------------------------------------------------- флаг и память

def test_выключен_по_умолчанию(worker: Worker) -> None:
    """Новая установка не должна приходить в режиме разработчика."""
    assert worker.dev_mode() is False


def test_флаг_переживает_перезапуск(tmp_path: Path) -> None:
    """Сервер перезапускают часто; флаг обязан пережить это, а не слететь."""
    worker = Worker(tmp_path)
    worker.set_dev_mode(True)
    worker.store.close()

    again = Worker(tmp_path)
    assert again.dev_mode() is True, "после перезапуска режим слетел"


def test_выключение_тоже_сохраняется(tmp_path: Path) -> None:
    """Обратный ход — не «сброс в ноль», а записанное решение."""
    worker = Worker(tmp_path)
    worker.set_dev_mode(True)
    worker.set_dev_mode(False)
    worker.store.close()
    assert Worker(tmp_path).dev_mode() is False


def test_событие_попадает_в_журнал(worker: Worker) -> None:
    """Кто и когда трогал режим — видно по журналу: «оно само включилось»
    худший ответ на вопрос «что случилось»."""
    seen: list[dict] = []
    worker.subscribe(seen.append)
    worker.set_dev_mode(True)
    assert [e["type"] for e in seen] == ["dev_mode_changed"]
    assert seen[0]["on"] is True


# ------------------------------------------------------------- диагностика

def test_диагностика_показывает_пути_и_счётчики(worker: Worker) -> None:
    info = worker.dev_info()
    assert info["ok"] is True
    assert info["root"] == str(worker.root)
    assert info["db"].endswith(".db"), info["db"]
    assert info["python"].count(".") >= 1, "версия Python не разобралась"
    assert isinstance(info["tasks"], int) and info["tasks"] >= 0
    assert isinstance(info["events"], int)
    assert "last_error" in info


def test_последняя_ошибка_видна_в_диагностике(worker: Worker) -> None:
    """Пустая строка — это «ошибок не было», а не «не знаю»."""
    assert worker.dev_info()["last_error"] == ""
    worker.last_error = "RuntimeError: сломалось"
    assert "сломалось" in worker.dev_info()["last_error"]


def test_диагностика_не_выдаёт_ключей(tmp_path: Path) -> None:
    """Главное правило вкладки Настроек: значений ключей в ответе нет.

    Здесь ключ заведён в config/secrets.local.json по-настоящему: если
    бы dev_info полез в секреты (например, ради «показать, какой ключ
    сломался»), тест это поймал бы, а не пропустил по привычке.
    """
    secrets = tmp_path / "config" / "secrets.local.json"
    secrets.parent.mkdir(parents=True, exist_ok=True)
    secrets.write_text(
        '{"openrouter": ["sk-or-v1-SECRETVALUE-0123456789abcdef"]}',
        encoding="utf-8",
    )
    worker = Worker(tmp_path)
    info = worker.dev_info()

    dumped = repr(info)
    assert "SECRETVALUE" not in dumped, "диагностика протекла ключом"
    assert "sk-or" not in dumped, "диагностика протекла формой ключа"
    worker.store.close()


def test_диагностика_не_ломается_на_сломанной_базе(worker: Worker) -> None:
    """Отладочная вкладка не должна сама давать 500."""
    worker.store.close()
    info = worker.dev_info()
    assert info["ok"] is True
    assert info["tasks"] == -1, "счётчик обязан честно сказать «не знаю»"


def test_диагностика_не_даёт_права_править_код(worker: Worker) -> None:
    """Режим разработчика не включает self_edit.

    Право править собственный код выдаётся на одну задачу (payload
    self_edit в _execute). Сделай его глобальным — и агент когда-нибудь
    правит программу без спроса, а человек об этом узнаёт постфактум.
    """
    info = worker.dev_info()
    assert "self_edit" not in info
    worker.set_dev_mode(True)
    assert "self_edit" not in worker.dev_info()


# --------------------------------------------------------------- обработчики

def test_обработчик_переключает_режим(tmp_path: Path) -> None:
    handler, fake = handler_for(tmp_path)
    out = Handler._dev(handler, {"on": True})
    assert out["ok"] is True and out["on"] is True
    assert fake.calls == [True]


def test_обработчик_без_тела_ничего_не_меняет(tmp_path: Path) -> None:
    """GET /api/dev идёт тем же маршрутом, что и POST: пустое тело — чтение."""
    handler, fake = handler_for(tmp_path)
    out = Handler._dev(handler, {})
    assert out["ok"] is True
    assert fake.calls == [], "чтение состояния переключило режим"


# ---------------------------------------------------------------- интерфейс

def test_кнопка_и_обработчики_в_интерфейсе() -> None:
    """Блок без функций — мёртвый блок: на странице он есть, а не работает."""
    for fn in ("function loadDev", "function renderDev", "function devToggle",
               "function devRefresh"):
        assert fn in UI_HTML, f"нет {fn}"
    assert 'id="devBtn"' in UI_HTML
    assert 'id="devBox"' in UI_HTML
    assert "Режим разработчика" in UI_HTML
    assert "/api/dev" in UI_HTML


def test_интерфейс_обещает_то_что_делает() -> None:
    """Рядом с переключателем написано, что режим НЕ даёт править код."""
    assert "не начнёт" in UI_HTML.lower() or "Не начнёт" in UI_HTML


def test_маршрут_dev_есть_на_get_и_post() -> None:
    """GET читает состояние, POST меняет: оба маршрута обязаны быть."""
    import inspect

    post_src = inspect.getsource(Handler.do_POST)
    get_src = inspect.getsource(Handler.do_GET)
    assert '"/api/dev"' in post_src
    assert '"/api/dev"' in get_src