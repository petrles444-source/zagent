"""Сессии: переключение воркспейса и новая сессия в том же воркспейсе."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from hub.store import Store


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    instance = Store(tmp_path)
    yield instance
    instance.close()


# ------------------------------------------------------------------ создание


def test_add_session_defaults_to_workspace(store: Store) -> None:
    session_id = store.add_session("ws-a")

    record = store.get_session(session_id)
    assert record["workspace_id"] == "ws-a"
    assert record["name"]  # без имени показывать нечего
    assert record["task_count"] == 0


def test_add_session_keeps_given_name(store: Store) -> None:
    session_id = store.add_session("ws-a", "Правка README")

    assert store.get_session(session_id)["name"] == "Правка README"


def test_add_session_makes_unique_id(store: Store) -> None:
    first = store.add_session("ws-a", "работа")
    second = store.add_session("ws-a", "работа")

    assert first != second
    # Обе сессии живы: вторая не перетирала первую.
    assert store.get_session(first) is not None
    assert store.get_session(second) is not None
    assert second == "работа-2"


def test_session_ids_are_readable(store: Store) -> None:
    session_id = store.add_session("ws-a", "Правка тестов")

    # Кириллица в id — не помеха, лишь бы не было пробелов и спецсимволов.
    assert " " not in session_id
    assert session_id


def test_get_unknown_session(store: Store) -> None:
    assert store.get_session("нет-такой") is None


# -------------------------------------------------------------------- списки


def test_list_sessions_filtered_by_workspace(store: Store) -> None:
    one = store.add_session("ws-a", "а")
    two = store.add_session("ws-b", "б")

    assert [s["id"] for s in store.list_sessions("ws-a")] == [one]
    assert [s["id"] for s in store.list_sessions("ws-b")] == [two]


def test_list_sessions_newest_first(store: Store) -> None:
    first = store.add_session("ws-a", "первая")
    time.sleep(0.01)
    second = store.add_session("ws-a", "вторая")

    order = [s["id"] for s in store.list_sessions("ws-a")]
    assert order[0] == second
    assert first in order


def test_list_all_sessions(store: Store) -> None:
    store.add_session("ws-a", "а")
    store.add_session("ws-b", "б")

    assert len(store.list_sessions()) == 2


def test_task_count_grows_with_tasks(store: Store) -> None:
    session_id = store.add_session("ws-a", "работа")
    store.add_task("одна", session_id=session_id)
    store.add_task("две", session_id=session_id)

    assert store.get_session(session_id)["task_count"] == 2


# --------------------------------------------------------------------- touch


def test_touch_moves_session_to_top(store: Store) -> None:
    first = store.add_session("ws-a", "первая")
    second = store.add_session("ws-a", "вторая")
    assert [s["id"] for s in store.list_sessions("ws-a")][0] == second

    store.touch_session(first)

    assert [s["id"] for s in store.list_sessions("ws-a")][0] == first


def test_touch_unknown_session_is_noop(store: Store) -> None:
    store.touch_session("нет")
    assert store.list_sessions() == []


# ------------------------------------------------------------- активная сессия


def test_active_session_roundtrip(store: Store) -> None:
    session_id = store.add_session("ws-a", "работа")

    store.set_active_session(session_id)

    assert store.active_session_id() == session_id


def test_no_active_session_by_default(store: Store) -> None:
    assert store.active_session_id() == ""


def test_ensure_session_creates_when_missing(store: Store) -> None:
    session_id = store.ensure_session("ws-a")

    assert store.get_session(session_id)["workspace_id"] == "ws-a"


def test_ensure_session_reuses_active_in_same_workspace(store: Store) -> None:
    first = store.add_session("ws-a", "работа")
    store.set_active_session(first)

    assert store.ensure_session("ws-a") == first


def test_ensure_session_switches_workspace(store: Store) -> None:
    store.set_active_session(store.add_session("ws-a", "работа"))

    session_id = store.ensure_session("ws-b")

    assert store.get_session(session_id)["workspace_id"] == "ws-b"


def test_ensure_session_replaces_deleted_active(store: Store) -> None:
    """Активная сессия пропала — интерфейсу всё равно надо что показывать."""
    store.set_active_session("исчезла")

    session_id = store.ensure_session("ws-a")

    assert store.get_session(session_id) is not None


def test_set_active_session_touches_it(store: Store) -> None:
    first = store.add_session("ws-a", "первая")
    second = store.add_session("ws-a", "вторая")

    store.set_active_session(first)

    assert [s["id"] for s in store.list_sessions("ws-a")][0] == first
    assert store.active_session_id() == first
    assert second != first


# -------------------------------------------------------------- переименование


def test_rename_session(store: Store) -> None:
    session_id = store.add_session("ws-a", "черновик")

    record = store.rename_session(session_id, "чистовик")

    assert record["name"] == "чистовик"


def test_rename_unknown_session(store: Store) -> None:
    assert store.rename_session("нет", "имя") is None


def test_rename_with_blank_name_keeps_old(store: Store) -> None:
    session_id = store.add_session("ws-a", "работа")

    record = store.rename_session(session_id, "   ")

    assert record["name"] == "работа"


# --------------------------------------------------------------------- удаление


def test_remove_session(store: Store) -> None:
    keep = store.add_session("ws-a", "остаётся")
    drop = store.add_session("ws-a", "удаляется")

    assert store.remove_session(drop) is True
    assert store.get_session(drop) is None
    assert store.get_session(keep) is not None


def test_cannot_remove_last_session(store: Store) -> None:
    """Без сессии интерфейсу нечего показывать, поэтому последняя неприкосновенна."""
    only = store.add_session("ws-a", "единственная")

    assert store.remove_session(only) is False
    assert store.get_session(only) is not None


def test_last_session_guard_is_per_workspace(store: Store) -> None:
    """Страховка относится к своей папке, а не ко всей базе."""
    keep = store.add_session("ws-a", "первая в своей папке")
    mine = store.add_session("ws-a", "вторая в своей папке")
    store.add_session("ws-b", "единственная в другой папке")

    assert store.remove_session(mine) is True
    assert store.get_session(mine) is None
    assert store.get_session(keep) is not None
    # Последняя сессия другой папки на месте и не пострадала.
    assert len(store.list_sessions("ws-b")) == 1


def test_last_session_of_other_workspace_is_protected(store: Store) -> None:
    store.add_session("ws-a", "в другой папке")
    only_b = store.add_session("ws-b", "единственная в своей")

    assert store.remove_session(only_b) is False
    assert store.get_session(only_b) is not None


def test_remove_unknown_session(store: Store) -> None:
    assert store.remove_session("нет") is False


def test_remove_keeps_tasks_of_session(store: Store) -> None:
    """История задач не должна пропадать вместе с сессией."""
    store.add_session("ws-a", "первая")
    drop = store.add_session("ws-a", "вторая")
    task_id = store.add_task("задача", session_id=drop)

    store.remove_session(drop)

    task = store.get_task(task_id)
    assert task is not None
    assert task["session_id"] == drop


# ------------------------------------------------------------------- задачи


def test_task_records_session(store: Store) -> None:
    session_id = store.add_session("ws-a", "работа")

    task_id = store.add_task("задача", session_id=session_id)

    assert store.get_task(task_id)["session_id"] == session_id


def test_task_without_session(store: Store) -> None:
    task_id = store.add_task("старая задача")

    assert store.get_task(task_id)["session_id"] is None


def test_list_tasks_filtered_by_session(store: Store) -> None:
    mine = store.add_session("ws-a", "моя")
    other = store.add_session("ws-a", "чужая")
    my_task = store.add_task("моя", session_id=mine)
    other_task = store.add_task("чужая", session_id=other)

    found = store.list_tasks(session_id=mine)

    assert [t["id"] for t in found] == [my_task]
    assert other_task not in [t["id"] for t in found]


def test_list_tasks_empty_string_means_no_session(store: Store) -> None:
    store.add_session("ws-a", "работа")
    store.add_task("с сессией", session_id=store.ensure_session("ws-a"))
    orphan = store.add_task("без сессии")

    found = store.list_tasks(session_id="")

    assert [t["id"] for t in found] == [orphan]


def test_list_tasks_none_means_no_filter(store: Store) -> None:
    session_id = store.add_session("ws-a", "работа")
    store.add_task("с сессией", session_id=session_id)
    store.add_task("без сессии")

    assert len(store.list_tasks()) == 2


def test_list_tasks_status_and_session_together(store: Store) -> None:
    session_id = store.add_session("ws-a", "работа")
    done = store.add_task("готова", session_id=session_id)
    store.update_task(done, status="done")
    store.add_task("в очереди", session_id=session_id)

    found = store.list_tasks(status="done", session_id=session_id)

    assert [t["id"] for t in found] == [done]


# -------------------------------------------------------------------- миграция


def test_migration_adds_session_column_to_old_db(tmp_path: Path) -> None:
    """Старая база без колонки сессий должна открыться, а не упасть."""
    import sqlite3

    path = Store(tmp_path).path
    legacy = sqlite3.connect(str(path))
    legacy.execute("DROP TABLE tasks")
    legacy.execute(
        "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'queued', priority INTEGER NOT NULL DEFAULT 5, "
        "created_at REAL NOT NULL, started_at REAL, finished_at REAL, "
        "steps INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0, "
        "models TEXT NOT NULL DEFAULT '', result TEXT, error TEXT, "
        "payload TEXT NOT NULL DEFAULT '{}')"
    )
    legacy.execute(
        "INSERT INTO tasks (task, created_at) VALUES ('старая', 1.0)"
    )
    legacy.commit()
    legacy.close()

    # Открытие базы добавляет колонку; старая задача остаётся на месте.
    store = Store(tmp_path)
    try:
        tasks = store.list_tasks()
        assert [t["task"] for t in tasks] == ["старая"]
        assert tasks[0]["session_id"] is None
    finally:
        store.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Второй запуск не должен пытаться добавить колонку ещё раз."""
    first = Store(tmp_path)
    first.close()

    second = Store(tmp_path)
    try:
        second.add_session("ws-a", "работа")
    finally:
        second.close()


def test_sessions_survive_restart(tmp_path: Path) -> None:
    store = Store(tmp_path)
    session_id = store.add_session("ws-a", "Правка README")
    store.set_active_session(session_id)
    store.close()

    reopened = Store(tmp_path)
    try:
        assert reopened.active_session_id() == session_id
        assert reopened.get_session(session_id)["name"] == "Правка README"
    finally:
        reopened.close()
