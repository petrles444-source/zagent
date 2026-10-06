"""События и поток: сервер не должен вываливать историю целиком.

Три поломки, из-за которых интерфейс тормозил на пустом месте:

* `since=0` при каждой загрузке отдавал до 200 старых событий, и каждое
  дёргало ещё `GET /api/state` — до 400 параллельных запросов;
* события не несли `session_id`, поэтому чужие шаги дописывались в переписку
  (фильтр на клиенте был, но сравнивать было не с чем);
* подписка включалась до чтения backlog, и событие на границе приходило дважды.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.server import _in_session  # noqa: E402
from hub.store import Store  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    (tmp_path / "config").mkdir(parents=True)
    return Store(tmp_path)


# =========================================================== фильтр по сессии


def test_чужое_событие_не_проходит() -> None:
    assert not _in_session({"session_id": "из-браузера"}, "другая")
    assert _in_session({"session_id": "моя"}, "моя")


def test_событие_без_сессии_пропускается() -> None:
    """Пинги и состояние моделей не привязаны к переписке."""
    assert _in_session({}, "любая")
    assert _in_session({"type": "ping_done"}, "любая")


# =========================================================== last_event_id


def test_last_event_id_растёт(store: Store) -> None:
    start = store.last_event_id()
    store.add_event({"type": "step"}, task_id=None)
    assert store.last_event_id() > start


def test_backlog_с_момента(store: Store) -> None:
    first = store.add_event({"type": "step", "n": 1})
    second = store.add_event({"type": "step", "n": 2})

    tail = store.events_since(first)
    ids = [e["id"] for e in tail]
    assert second in ids
    assert first not in ids


def test_session_id_пишется_в_payload(store: Store) -> None:
    """Событие обязано нести сессию, иначе поток нечем фильтровать."""
    store.add_event({"type": "step"}, task_id=None)
    event = store.events_since(0)[-1]
    assert "session_id" in event


def test_битый_payload_не_ломает_backlog(store: Store) -> None:
    store.add_event({"type": "step"}, task_id=None)
    store._exec(
        "INSERT INTO events (task_id, at, type, payload) VALUES (?, ?, ?, ?)",
        (None, 0.0, "broken", "{не json"),
    )
    events = store.events_since(0)
    assert all(e.get("type") != "broken" for e in events)


# =========================================================== интерфейс


def script() -> str:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    _, _, rest = src.partition("</style>")
    return rest.partition("<script>")[2].partition("</script>")[0]


def test_скрипт_извлекается() -> None:
    assert len(script().splitlines()) > 100


def test_last_event_переживает_перезагрузку() -> None:
    body = script()
    assert "sessionStorage" in body, "lastEvent обязан сохраняться между загрузками"
    assert "zagent.lastEvent" in body


def test_localStorage_не_используется_для_событий() -> None:
    """localStorage переживает закрытие вкладки — лента устаревает на сутки."""
    body = script()
    for line in body.splitlines():
        if "localStorage" in line and "zagent.lastEvent" in line:
            pytest.fail("события нельзя хранить в localStorage")


def test_дубли_событий_отсекаются() -> None:
    """Событие с границы приходит и из backlog, и из очереди."""
    body = script()
    assert "noteSeen" in body
    assert "seen.has" in body


def test_множество_ограничено() -> None:
    """Вкладка может висеть сутки: без обрезки уйдёт память."""
    body = script()
    assert "SEEN_MAX" in body
    assert "seen.size >= SEEN_MAX" in body


def test_поток_фильтруется_по_сессии() -> None:
    body = script()
    assert "&session=" in body, "поток должен фильтроваться по сессии"


def test_since_не_начинается_с_нулём() -> None:
    """Клиент шлёт 0 после перезагрузки — сервер обязан это учесть."""
    src = (ROOT / "hub" / "server.py").read_text(encoding="utf-8")
    assert "last_event_id() - 50" in src, (
        "since=0 должен означать «последние 50», а не всю историю"
    )


def test_подписка_до_backlog_и_двухсторонняя_защита() -> None:
    """Дубль на границе убирает клиент, потеря — нет.

    Если прочитать backlog после подписки, событие придёт дважды; если до —
    событие между чтением и подпиской пропадёт навсегда. Поэтому подписка
    идёт первой, а дедупликация — на клиенте.
    """
    src = (ROOT / "hub" / "server.py").read_text(encoding="utf-8")
    subscribe_at = src.index("worker.subscribe(on_event)")
    backlog_at = src.index("worker.store.events_since(")
    assert subscribe_at < backlog_at, "подписка должна идти до чтения backlog"


def test_фильтр_применяется_и_к_backlog_и_к_потоку() -> None:
    """Одного фильтра мало: чужие события шли обоими путями."""
    src = (ROOT / "hub" / "server.py").read_text(encoding="utf-8")
    assert src.count("_in_session(") >= 3, (
        "фильтр должен стоять и на backlog, и в цикле, плюс определение"
    )