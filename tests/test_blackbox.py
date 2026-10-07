"""Чёрный ящик задачи: трейс одним файлом, без секретов внутри.

Идея из `update/creativeupdate-07-10-26.txt` («Полётный регистратор»).
Проверяется главное: файл действительно собирается из журнала, сводка
считается верно, а настоящие ключи в выдачу не попадают — её выкладывают
в переписку при разборе.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from hub import blackbox
from hub.server import Handler
from hub.store import Store


def make_story(store: Store, task_id: int) -> None:
    """Трассировка задачи: два хопа, второй с отказом, потом инструмент."""
    store.add_event({"type": "step", "at": 1.0,
                     "step": {"index": 1, "phase": "plan", "model": "a/model",
                              "duration_ms": 120, "ok": True}}, task_id=task_id)
    store.add_event({"type": "model_call", "at": 1.1, "n": 1,
                     "sent": 300, "got": 50, "error": ""}, task_id=task_id)
    store.add_event({"type": "step", "at": 2.0,
                     "step": {"index": 2, "phase": "act", "model": "b/model",
                              "duration_ms": 80, "ok": False,
                              "error": "429 too many requests"}}, task_id=task_id)
    store.add_event({"type": "model_call", "at": 2.1, "n": 2,
                     "sent": 100, "got": 0, "error": "Rate limit"}, task_id=task_id)
    store.add_event({"type": "tool", "at": 3.0, "tool": "write_file"},
                    task_id=task_id)


def test_чёрный_ящик_собирает_карточку_сводку_и_события(tmp_path: Path) -> None:
    store = Store(tmp_path)
    task_id = store.add_task("почини баг")

    make_story(store, task_id)
    text = blackbox.build(store, task_id, root=tmp_path)
    lines = [json.loads(line) for line in text.splitlines()]

    assert lines[0]["record"] == "task"
    assert lines[0]["task"] == "почини баг"
    assert lines[0]["id"] == task_id

    summary = lines[1]
    assert summary["record"] == "summary"
    assert summary["events"] == 5
    assert summary["steps"] == 2
    assert summary["models"]["a/model"] == {"steps": 1, "failed": 0, "ms": 120}
    assert summary["models"]["b/model"] == {"steps": 1, "failed": 1, "ms": 80}
    assert summary["tokens_sent"] == 400 and summary["tokens_got"] == 50
    assert summary["duration_ms"] == 200
    assert "429" in summary["first_error"]
    assert summary["types"] == {"model_call": 2, "step": 2, "tool": 1}

    events = lines[2:]
    assert [e["record"] for e in events] == ["event"] * 5
    assert events[0]["type"] == "step" and events[-1]["tool"] == "write_file"
    # id события нужен, чтобы по ссылке дойти до конкретной попытки в базе
    assert isinstance(events[0]["id"], int)


def test_ключи_в_чёрном_ящике_вымараны(tmp_path: Path) -> None:
    """Файл выкладывают в переписку: секрета там быть не должно."""
    (tmp_path / "config").mkdir()
    secret = "gsk_SUPERSECRET_abcdef123456"
    (tmp_path / "config" / "secrets.local.json").write_text(
        json.dumps({"groq": [secret]}), encoding="utf-8"
    )
    store = Store(tmp_path)
    task_id = store.add_task("с ключом внутри")
    store.add_event({"type": "tool", "at": 1.0, "tool": "read_file",
                     "args": {"path": secret}}, task_id=task_id)

    text = blackbox.build(store, task_id, root=tmp_path)
    assert secret not in text
    assert "***" in text
    # сама запись не потеряна — заменено только значение
    assert "read_file" in text


def test_сводка_без_событий_не_падает(tmp_path: Path) -> None:
    store = Store(tmp_path)
    task_id = store.add_task("без истории")
    lines = [json.loads(line) for line in
             blackbox.build(store, task_id, root=tmp_path).splitlines()]
    assert len(lines) == 2
    assert lines[1]["events"] == 0
    assert lines[1]["first_error"] is None
    assert lines[1]["models"] == {}


def test_несуществующая_задача_отклоняется(tmp_path: Path) -> None:
    store = Store(tmp_path)
    with pytest.raises(blackbox.BlackboxError, match="777"):
        blackbox.build(store, 777, root=tmp_path)


def test_имя_файла_по_номеру_задачи() -> None:
    assert blackbox.filename(7) == "blackbox-task-7.jsonl"


# --------------------------------------------------------------- сервер


def test_маршрут_чёрного_ящика_в_get() -> None:
    import inspect

    src = inspect.getsource(Handler.do_GET)
    assert '"/api/blackbox"' in src
    assert "_download" in src


def test_ответ_чёрного_ящика_скачивается() -> None:
    """Content-Disposition — единственное, что превращает ответ в файл."""
    handler = Handler.__new__(Handler)
    seen: dict[str, str] = {}
    body = io.BytesIO()
    handler.send_response = lambda status: seen.__setitem__("status", str(status))
    handler.send_header = lambda k, v: seen.__setitem__(k, v)
    handler.end_headers = lambda: None
    handler.wfile = body

    Handler._download(handler, '{"record":"task"}\n', "blackbox-task-3.jsonl")

    assert seen["status"] == "200"
    assert seen["Content-Disposition"] == (
        'attachment; filename="blackbox-task-3.jsonl"'
    )
    assert seen["Content-Type"].startswith("application/x-ndjson")
    assert seen["Content-Length"] == str(len('{"record":"task"}\n'.encode("utf-8")))
    assert body.getvalue().decode("utf-8") == '{"record":"task"}\n'


# --------------------------------------------------------------- интерфейс


def test_кнопка_чёрного_ящика_в_интерфейсе() -> None:
    from hub.ui import UI_HTML

    assert "onclick=\"blackBox(" in UI_HTML
    assert "function blackBox" in UI_HTML
    assert "'/api/blackbox?task='" in UI_HTML
