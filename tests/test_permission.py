"""Тесты мягкой границы воркспейса: запрос разрешения и его обработка."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from hub.autonomy import (
    AccessLevel,
    Autonomy,
    Escalation,
    Guard,
    is_permission_request,
    permission_question,
)
from hub.store import Store
from hub.tools import run_tool


@pytest.fixture()
def guard(tmp_path: Path) -> Guard:
    """Мягкая граница на tmp_path в обычном режиме.

    Уровень доступа здесь WRITE, а не FULL: при полном доступе агент выходит
    наружу без вопроса, и проверять было бы нечего. Случаи с FULL описаны
    отдельно в блоке «полный доступ без вопросов».
    """
    instance = Guard(
        access=AccessLevel.WRITE,
        autonomy=Autonomy.YOLO,
        escalation=Escalation.AUTO,
    )
    instance.set_workspace(tmp_path, "ws", soft_boundary=True)
    return instance


# ------------------------------------------------------------- распознавание


def test_permission_prefix_detected() -> None:
    assert is_permission_request("needs_permission:путь вне") is True
    assert is_permission_request("просто ошибка") is False


def test_permission_question_strips_prefix() -> None:
    assert permission_question("needs_permission:вне воркспейса") == "вне воркспейса"


# --------------------------------------------------------------- граница


def test_soft_boundary_asks_instead_of_denying(tmp_path: Path, guard: Guard) -> None:
    outside = tmp_path.parent / "elsewhere" / "file.txt"

    allowed, reason = guard.check_path(str(outside), writing=True)

    assert allowed is False
    assert is_permission_request(reason) is True
    assert str(outside) in permission_question(reason)


def test_hard_boundary_denies_plainly(tmp_path: Path) -> None:
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace(tmp_path, "ws", soft_boundary=False)

    allowed, reason = guard.check_path(str(tmp_path.parent / "other.txt"), writing=True)

    assert allowed is False
    assert is_permission_request(reason) is False
    assert "вне воркспейса" in reason


def test_inside_workspace_still_allowed(tmp_path: Path, guard: Guard) -> None:
    inside = tmp_path / "sub" / "file.txt"
    assert guard.check_path(str(inside), writing=True)[0] is True


def test_grant_path_opens_access(tmp_path: Path, guard: Guard) -> None:
    outside = tmp_path.parent / "elsewhere" / "file.txt"
    assert guard.check_path(str(outside), writing=True)[0] is False

    guard.grant_path(str(outside))

    allowed, reason = guard.check_path(str(outside), writing=True)
    assert allowed is True
    assert is_permission_request(reason) is False


def test_grant_specific_path_does_not_open_neighbours(tmp_path: Path, guard: Guard) -> None:
    allowed_path = tmp_path.parent / "elsewhere" / "a.txt"
    other_path = tmp_path.parent / "elsewhere" / "b.txt"

    guard.grant_path(str(allowed_path))

    assert guard.check_path(str(allowed_path), writing=True)[0] is True
    assert guard.check_path(str(other_path), writing=True)[0] is False


def test_granted_sibling_folder_stays_closed(tmp_path: Path, guard: Guard) -> None:
    """Разрешение на «data/file» не должно открывать соседнюю «data-secret».

    Пути строим рядом с воркспейсом, а не внутри него: внутри всё и так
    разрешено, проверять тут нечего. Граница сверяется по компонентам пути,
    иначе «data-secret» прошёл бы сравнение по префиксу для «data».
    """
    root = tmp_path.parent / "boundary-case"
    guard.grant_path(str(root / "data" / "file.txt"))

    assert guard.check_path(str(root / "data" / "file.txt"), writing=True)[0] is True
    assert guard.check_path(str(root / "data-secret" / "x.txt"), writing=True)[0] is False


def test_granted_folder_allows_its_files(tmp_path: Path, guard: Guard) -> None:
    """Разрешение на папку открывает всё, что в ней."""
    root = tmp_path.parent / "boundary-folder"
    guard.grant_path(str(root / "shared"))
    inside = root / "shared" / "config.json"

    allowed, reason = guard.check_path(str(inside), writing=True)
    assert allowed is True
    assert is_permission_request(reason) is False


def test_granted_file_does_not_open_siblings(tmp_path: Path, guard: Guard) -> None:
    """Разрешение на один файл не открывает соседний файл в той же папке."""
    root = tmp_path.parent / "boundary-file"
    guard.grant_path(str(root / "a.txt"))
    sibling = root / "b.txt"

    assert guard.check_path(str(root / "a.txt"), writing=True)[0] is True
    assert guard.check_path(str(sibling), writing=True)[0] is False


def test_granted_paths_are_isolated_per_task(tmp_path: Path, guard: Guard) -> None:
    """Разрешения одной задачи не должны действовать в другой."""
    first = tmp_path.parent / "task-a"
    second = tmp_path.parent / "task-b"
    guard.grant_path(str(first))
    guard.granted_paths = [str(first)]  # эмулируем загрузку только своей задачи

    assert guard.check_path(str(first / "x.txt"), writing=True)[0] is True
    assert guard.check_path(str(second / "x.txt"), writing=True)[0] is False


def test_outside_workspace_helper(tmp_path: Path, guard: Guard) -> None:
    assert guard.outside_workspace(str(tmp_path / "x.txt")) is False
    assert guard.outside_workspace(str(tmp_path.parent / "y.txt")) is True


# -------------------------------------------------------------- инструмент


def test_tool_requests_permission(tmp_path: Path, guard: Guard) -> None:
    target = tmp_path.parent / "escape-test.txt"
    target.write_text("старое", encoding="utf-8")

    result = run_tool("write_file", guard, base=tmp_path,
                      path=str(target), content="новое")

    assert result.ok is False
    assert result.needs_user is True
    assert result.needs_permission is True
    assert str(target) in result.question
    assert result.meta["path"] == str(target)
    # Файл не тронут: разрешения ещё нет.
    assert target.read_text(encoding="utf-8") == "старое"


def test_tool_succeeds_after_grant(tmp_path: Path, guard: Guard) -> None:
    target = tmp_path.parent / "escape-ok.txt"
    guard.grant_path(str(target))

    result = run_tool("write_file", guard, base=tmp_path,
                      path=str(target), content="новое")

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "новое"
    target.unlink()


def test_inside_write_needs_no_permission(tmp_path: Path, guard: Guard) -> None:
    result = run_tool("write_file", guard, base=tmp_path,
                      path="inside.txt", content="данные")

    assert result.ok is True
    assert result.needs_permission is False


def test_edit_outside_requests_permission(tmp_path: Path, guard: Guard) -> None:
    target = tmp_path.parent / "edit-escape.txt"
    target.write_text("старое", encoding="utf-8")

    result = run_tool("edit_file", guard, base=tmp_path,
                      path=str(target), old="старое", new="новое")

    assert result.needs_permission is True
    target.unlink()


def test_delete_outside_needs_full_access(tmp_path: Path, guard: Guard) -> None:
    """Удаление требует полного доступа, поэтому до границы не доходит.

    В обычном режиме инструмент недоступен вовсе, и спрашивать о выходе
    наружу бессмысленно: нечем. С полным доступом удаление просто выполняется.
    """
    target = tmp_path.parent / "del-escape.txt"
    target.write_text("x", encoding="utf-8")

    blocked = run_tool("delete_path", guard, base=tmp_path, path=str(target))
    assert blocked.ok is False
    assert blocked.needs_permission is False

    guard.access = AccessLevel.FULL
    allowed = run_tool("delete_path", guard, base=tmp_path, path=str(target))
    assert allowed.ok is True
    assert allowed.needs_permission is False
    assert not target.exists()


def test_read_outside_also_asks(tmp_path: Path, guard: Guard) -> None:
    """Чтение тоже за границей: иногда нужно прочитать файл из соседнего проекта."""
    target = tmp_path.parent / "read-escape.txt"
    target.write_text("данные", encoding="utf-8")

    result = run_tool("read_file", guard, base=tmp_path, path=str(target))

    assert result.needs_permission is True
    target.unlink()


def test_shell_outside_needs_full_access(tmp_path: Path, guard: Guard) -> None:
    """Команда оболочки пишет куда угодно, но доступна только при полном доступе."""
    outside = tmp_path.parent / "data.txt"

    blocked = run_tool("run_shell", guard, base=tmp_path, command=f"echo hi > {outside}")
    assert blocked.ok is False
    assert blocked.needs_permission is False
    assert not outside.exists()

    guard.access = AccessLevel.FULL
    allowed = run_tool("run_shell", guard, base=tmp_path, command=f"echo hi > {outside}")
    assert allowed.needs_permission is False
    if outside.exists():
        outside.unlink()


def test_permission_flag_distinct_from_needs_user(tmp_path: Path, guard: Guard) -> None:
    """Отказ по уровню доступа — это не запрос разрешения на границу."""
    read_only = Guard(access=AccessLevel.READ, escalation=Escalation.OFF)
    read_only.set_workspace(tmp_path, "ws")

    result = run_tool("write_file", read_only, base=tmp_path, path="x.txt", content="y")

    assert result.ok is False
    assert result.needs_permission is False
    assert result.needs_user is False


# ----------------------------------------------------------------- хранилище


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    instance = Store(tmp_path)
    yield instance
    instance.close()


def test_add_permission_is_pending(store: Store) -> None:
    permission_id = store.add_permission(
        operation="write_file", path="C:/other/f.txt", workspace="C:/ws", reason="нужен доступ"
    )

    request = store.get_permission(permission_id)
    assert request["status"] == "pending"
    assert request["operation"] == "write_file"
    assert len(store.pending_permissions()) == 1


def test_decide_granted(store: Store) -> None:
    permission_id = store.add_permission(operation="write_file", path="C:/o.txt",
                                        workspace="C:/ws")

    result = store.decide_permission(permission_id, True, scope="once")

    assert result["status"] == "granted"
    assert result["scope"] == "once"
    assert store.pending_permissions() == []


def test_decide_denied(store: Store) -> None:
    permission_id = store.add_permission(operation="write_file", path="C:/o.txt",
                                        workspace="C:/ws")

    result = store.decide_permission(permission_id, False)

    assert result["status"] == "denied"
    assert store.pending_permissions() == []


def test_decide_unknown_returns_none(store: Store) -> None:
    assert store.decide_permission(999, True) is None


def test_granted_paths_always(store: Store) -> None:
    store.decide_permission(
        store.add_permission(operation="w", path="C:/a.txt", workspace="C:/ws"),
        True, scope="always"
    )
    assert store.granted_paths() == ["C:/a.txt"]


def test_granted_paths_once_is_task_scoped(store: Store) -> None:
    task_id = store.add_task("задача")
    store.decide_permission(
        store.add_permission(operation="w", path="C:/b.txt", workspace="C:/ws",
                             task_id=task_id),
        True, scope="once"
    )

    # Глобально такой путь не действует.
    assert store.granted_paths() == []
    # Для своей задачи — действует.
    assert store.granted_paths(task_id=task_id) == ["C:/b.txt"]


def test_granted_paths_filter_by_other_task(store: Store) -> None:
    mine = store.add_task("моя")
    other = store.add_task("чужая")
    store.decide_permission(
        store.add_permission(operation="w", path="C:/c.txt", workspace="C:/ws",
                             task_id=mine),
        True, scope="once"
    )

    assert store.granted_paths(task_id=other) == []


def test_pending_permissions_filtered_by_task(store: Store) -> None:
    one = store.add_task("первая")
    two = store.add_task("вторая")
    store.add_permission(operation="w", path="C:/d.txt", workspace="C:/ws", task_id=one)
    store.add_permission(operation="w", path="C:/e.txt", workspace="C:/ws", task_id=two)

    assert len(store.pending_permissions(task_id=one)) == 1
    assert len(store.pending_permissions()) == 2


def test_permissions_survive_restart(tmp_path: Path) -> None:
    first = Store(tmp_path)
    permission_id = first.add_permission(
        operation="write_file", path="C:/outside.txt", workspace="C:/ws", reason="надо"
    )
    task_id = first.add_task("задача")
    first.close()

    second = Store(tmp_path)
    pending = second.pending_permissions()

    assert len(pending) == 1
    assert pending[0]["id"] == permission_id
    assert pending[0]["reason"] == "надо"
    second.close()


def test_stats_includes_pending(store: Store) -> None:
    store.add_permission(operation="w", path="C:/f.txt", workspace="C:/ws")
    assert store.stats()["permissions_pending"] == 1


def test_drop_permissions_clears_all(store: Store) -> None:
    store.add_permission(operation="w", path="C:/a.txt", workspace="C:/ws")
    store.add_permission(operation="w", path="C:/b.txt", workspace="C:/ws")

    assert store.drop_permissions(reason="перезапуск") == 2
    assert store.pending_permissions() == []


def test_drop_permissions_only_one_task(store: Store) -> None:
    mine = store.add_task("моя")
    store.add_permission(operation="w", path="C:/a.txt", workspace="C:/ws", task_id=mine)
    store.add_permission(operation="w", path="C:/b.txt", workspace="C:/ws")

    assert store.drop_permissions(task_id=mine, reason="отмена") == 1
    remaining = store.pending_permissions()
    assert [p["path"] for p in remaining] == ["C:/b.txt"]


def test_drop_permissions_keeps_note(store: Store) -> None:
    permission_id = store.add_permission(
        operation="w", path="C:/a.txt", workspace="C:/ws", reason="нужен доступ")

    store.drop_permissions(reason="задача отменена")

    record = store.get_permission(permission_id)
    assert record["status"] == "dropped"
    assert "нужен доступ" in record["reason"]
    assert "задача отменена" in record["reason"]
    assert record["decided_at"] is not None


def test_drop_permissions_touches_nothing_when_empty(store: Store) -> None:
    assert store.drop_permissions(reason="перезапуск") == 0


def test_dropped_permission_is_not_a_grant(store: Store) -> None:
    """Снятый запрос не должен открывать путь, как если бы вы его решили."""
    store.add_permission(operation="w", path="C:/a.txt", workspace="C:/ws")
    store.drop_permissions()
    assert store.granted_paths() == []


# -------------------------------------------------------------------- воркер


def test_worker_cancel_drops_pending_permission(tmp_path: Path) -> None:
    """Отмена задачи не должна оставлять окно разрешения навсегда."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        task_id = worker.store.add_task("задача")
        worker.store.update_task(task_id, status="waiting_permission", payload={})
        worker.store.add_permission(
            operation="write_file", path="C:/o.txt",
            workspace=str(tmp_path), task_id=task_id,
        )

        worker.cancel(task_id)

        assert worker.store.pending_permissions() == []
    finally:
        worker.store.close()


def test_cancel_parked_task_is_immediate(tmp_path: Path) -> None:
    """Задача, ждущая разрешения, должна отменяться сразу, а не висеть."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        for status in ("asking", "waiting_permission"):
            task_id = worker.store.add_task(f"задача {status}")
            worker.store.update_task(task_id, status=status, payload={})
            worker.store.add_permission(
                operation="w", path=f"C:/{status}.txt",
                workspace=str(tmp_path), task_id=task_id,
            )

            assert worker.cancel(task_id)["ok"] is True

            task = worker.store.get_task(task_id)
            assert task["status"] == "cancelled"
            assert worker.store.pending_permissions() == []
    finally:
        worker.store.close()


def test_cancel_queued_task(tmp_path: Path) -> None:
    from hub.store import Store

    store = Store(tmp_path)
    try:
        task_id = store.add_task("в очереди")
        assert store.cancel_task(task_id) is True
        assert store.get_task(task_id)["status"] == "cancelled"
    finally:
        store.close()


def test_cancel_running_sets_flag(tmp_path: Path) -> None:
    from hub.store import Store

    store = Store(tmp_path)
    try:
        task_id = store.add_task("выполняется", payload={"workspace_id": "ws"})
        store.update_task(task_id, status="running")

        assert store.cancel_task(task_id) is True

        task = store.get_task(task_id)
        # Статус остаётся running: воркер сам переведёт его в cancelled.
        assert task["status"] == "running"
        assert task["payload"]["cancel"] is True
        assert task["payload"]["workspace_id"] == "ws"
    finally:
        store.close()


def test_cancel_finished_task_is_noop(tmp_path: Path) -> None:
    from hub.store import Store

    store = Store(tmp_path)
    try:
        task_id = store.add_task("готова")
        store.update_task(task_id, status="done")
        assert store.cancel_task(task_id) is False
        assert store.get_task(task_id)["status"] == "done"
    finally:
        store.close()


def test_cancel_unknown_task(tmp_path: Path) -> None:
    from hub.store import Store

    store = Store(tmp_path)
    try:
        assert store.cancel_task(4242) is False
    finally:
        store.close()


def test_worker_soft_boundary_persists(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert worker.soft_boundary is True
        worker.set_soft_boundary(False)
        assert worker.store.get_meta("soft_boundary") is False

        second = Worker(tmp_path)
        try:
            assert second.soft_boundary is False
        finally:
            second.store.close()
    finally:
        worker.store.close()


def test_worker_answer_permission_requeues_task(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        task_id = worker.store.add_task("задача")
        worker.store.update_task(
            task_id, status="waiting_permission",
            payload={"checkpoint": {"messages": [{"role": "user", "content": "x"}]}},
        )
        permission_id = worker.store.add_permission(
            operation="write_file", path="C:/outside.txt",
            workspace=str(tmp_path), task_id=task_id,
        )

        result = worker.answer_permission(permission_id, True, scope="once")

        assert result["ok"] is True
        task = worker.store.get_task(task_id)
        assert task["status"] == "queued"
        assert task["payload"]["grant_path"] == "C:/outside.txt"
        # Чекпоинт сохранился: агент продолжит ту же сессию.
        assert task["payload"]["checkpoint"]["messages"]
    finally:
        worker.store.close()


def test_worker_deny_permission_does_not_grant(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        task_id = worker.store.add_task("задача")
        worker.store.update_task(task_id, status="waiting_permission", payload={})
        permission_id = worker.store.add_permission(
            operation="write_file", path="C:/x.txt",
            workspace=str(tmp_path), task_id=task_id,
        )

        worker.answer_permission(permission_id, False)

        task = worker.store.get_task(task_id)
        assert "grant_path" not in task["payload"]
        assert task["payload"].get("permission_id") is None
    finally:
        worker.store.close()


def test_worker_permission_without_task(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        permission_id = worker.store.add_permission(
            operation="w", path="C:/y.txt", workspace=str(tmp_path)
        )
        result = worker.answer_permission(permission_id, True)
        assert result["ok"] is True
        assert result.get("task_id") is None
    finally:
        worker.store.close()


# ------------------------------------------- доступ применяется к воркспейсу


def test_configure_access_reaches_active_workspace(tmp_path: Path) -> None:
    """Выбор «полный доступ» должен реально применяться.

    Настройки воркспейса перекрывают общие, поэтому если бы configure()
    менял только общий конфиг, выбор в интерфейсе выглядел бы рабочим,
    а задачи продолжали бы работать по старому уровню.
    """
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert worker.workspaces.get("default").access == 2

        worker.configure(access=3)

        assert worker.workspaces.get("default").access == 3
        # И состояние показывает действующее значение, а не только общее.
        assert worker.state()["config"]["access"] == 3
    finally:
        worker.store.close()


def test_configure_applies_all_agent_settings(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        worker.configure(access=1, autonomy="strict", escalation="on", max_steps=7)

        workspace = worker.workspaces.get("default")
        assert workspace.access == 1
        assert workspace.autonomy == "strict"
        assert workspace.escalation == "on"
        assert workspace.max_steps == 7

        effective = worker.state()["config"]
        assert effective["access"] == 1
        assert effective["autonomy"] == "strict"
        assert effective["escalation"] == "on"
        assert effective["max_steps"] == 7
    finally:
        worker.store.close()


def test_configure_survives_missing_workspace(tmp_path: Path) -> None:
    """Удалённый воркспейс не должен ронять настройку."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        worker.workspaces.items = []

        result = worker.configure(access=2)

        assert result["ok"] is True
        assert worker.config.access == AccessLevel.WRITE
    finally:
        worker.store.close()


def test_configure_keeps_unrelated_fields(tmp_path: Path) -> None:
    """prefer_speed не должен затирать уровень доступа и наоборот."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        worker.configure(prefer_speed=True)
        assert worker.workspaces.get("default").access == 2

        worker.configure(access=3)
        assert worker.config.prefer_speed is True
    finally:
        worker.store.close()


def test_worker_lists_permissions(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert worker.permissions()["permissions"] == []
        worker.store.add_permission(operation="w", path="C:/z.txt", workspace=str(tmp_path))
        assert len(worker.permissions()["permissions"]) == 1
    finally:
        worker.store.close()


def test_worker_state_includes_soft_boundary(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert worker.state()["soft_boundary"] is True
        worker.set_soft_boundary(False)
        assert worker.state()["soft_boundary"] is False
    finally:
        worker.store.close()


# ------------------------------------------------------- выполнение с грантом

def _make_worker(tmp_path: Path, monkeypatch):
    """Воркер с фальшивым агентом: проверяем путь продолжения без сети.

    Настоящий агент требует шлюз и сеть, а нам тут важна только обвязка
    `_execute`: что при grant_path вызов действительно происходит, а не падает
    с NameError, и что агент получает разрешение до старта run().
    """
    from hub.worker import Worker

    calls: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, selector, guard, config, on_event=None):
            self.guard = guard
            self.config = config
            calls["guard"] = guard
            calls["config"] = config

        def set_task(self, task: str) -> None:
            calls["task"] = task

        def restore_checkpoint(self, checkpoint):
            calls["checkpoint"] = checkpoint
            return True

        def approve_plan(self) -> None:
            calls["approved"] = True

        def answer_question(self, answer: str) -> None:
            calls["answer"] = answer

        async def grant_permission(self, path: str) -> None:
            calls["granted"] = path
            self.guard.grant_path(path)

        def request_cancel(self) -> None:
            calls["cancelled"] = True

        async def run(self):
            calls["ran"] = True
            return {"ok": True, "steps": 1, "models_used": ["fake/model"],
                    "pending_permission": None, "pending_question": None}

        @property
        def checkpoint(self):
            return {"messages": []}

    monkeypatch.setattr("hub.worker.Agent", FakeAgent)

    worker = Worker(tmp_path)
    # Селектор нужен, чтобы _execute не отказал на «реестр не загружен».
    worker.selector = object()
    # Loop поднимаем вручную: start() тянет реест�� и сеть.
    import asyncio
    import threading

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    worker.loop = loop
    calls["worker"] = worker
    return worker, calls


def _teardown_worker(worker) -> None:
    import asyncio

    if worker.loop is not None:
        worker.loop.call_soon_threadsafe(worker.loop.stop)
        worker.loop = None
    worker.store.close()


def test_execute_applies_grant_before_run(tmp_path: Path, monkeypatch) -> None:
    """Разрешение обязано попасть в guard ДО вызова run(), иначе агент
    снова упрётся в границу и запрос повторится по кругу."""
    from hub.workspace import WorkspaceManager

    outside = tmp_path.parent / "granted-exec"
    outside.mkdir(parents=True, exist_ok=True)

    worker, calls = _make_worker(tmp_path, monkeypatch)
    try:
        # Менеджер сразу даёт воркспейс "default" на tmp_path — добавлять нечего.
        manager = WorkspaceManager(tmp_path)
        monkeypatch.setattr(worker, "workspaces", manager)

        task_id = worker.store.add_task("задача", payload={
            "workspace_id": "default",
            "checkpoint": {"messages": [{"role": "user", "content": "x"}]},
            "grant_path": str(outside),
        })
        task = worker.store.get_task(task_id)

        worker._execute(task)

        assert calls.get("granted") == str(outside)
        assert calls.get("ran") is True
        # Порядок важен: grant до run.
        assert calls["granted"] is not None and calls["ran"] is not None
        guard = calls["guard"]
        assert guard.check_path(str(outside / "x.txt"), writing=True)[0] is True
        assert worker.store.get_task(task_id)["status"] == "done"
    finally:
        _teardown_worker(worker)
        shutil.rmtree(outside, ignore_errors=True)


def test_execute_without_grant_has_no_permission(tmp_path: Path, monkeypatch) -> None:
    """Обычная задача не должна получать разрешений ни на что."""
    from hub.workspace import WorkspaceManager

    worker, calls = _make_worker(tmp_path, monkeypatch)
    try:
        # Менеджер сразу даёт воркспейс "default" на tmp_path — добавлять нечего.
        manager = WorkspaceManager(tmp_path)
        monkeypatch.setattr(worker, "workspaces", manager)

        task_id = worker.store.add_task("задача", payload={"workspace_id": "default"})
        worker._execute(worker.store.get_task(task_id))

        assert "granted" not in calls
        assert calls.get("ran") is True
        assert worker.store.pending_permissions() == []
    finally:
        _teardown_worker(worker)


def test_execute_hard_boundary_denies_silently(tmp_path: Path, monkeypatch) -> None:
    """При жёсткой границе путь наружу не создаёт запрос — просто отказ."""
    from hub.workspace import WorkspaceManager

    worker, calls = _make_worker(tmp_path, monkeypatch)
    try:
        worker.soft_boundary = False
        # Менеджер сразу даёт воркспейс "default" на tmp_path — добавлять нечего.
        manager = WorkspaceManager(tmp_path)
        monkeypatch.setattr(worker, "workspaces", manager)

        task_id = worker.store.add_task("задача", payload={"workspace_id": "default"})
        worker._execute(worker.store.get_task(task_id))

        assert worker.store.pending_permissions() == []
        assert worker.store.get_task(task_id)["status"] == "done"
    finally:
        _teardown_worker(worker)


def test_denied_path_refuses_without_asking_again(tmp_path: Path, guard: Guard) -> None:
    """Отказ — это ответ. Повторный вопрос по тому же пути докучает."""
    outside = tmp_path.parent / "denied" / "file.txt"

    guard.deny_path(str(outside))

    allowed, reason = guard.check_path(str(outside), writing=True)
    assert allowed is False
    # Не запрос разрешения, а простой отказ: агент поймёт и не спросит снова.
    assert is_permission_request(reason) is False
    assert "отказано" in reason.lower()
    assert "не спрашиваю" in reason.lower()


def test_denial_covers_folder_contents(tmp_path: Path, guard: Guard) -> None:
    folder = tmp_path.parent / "denied-folder"
    guard.deny_path(str(folder))

    assert guard.check_path(str(folder / "a.txt"), writing=True)[0] is False
    assert guard.check_path(str(folder / "deep" / "b.txt"), writing=True)[0] is False


def test_denial_does_not_block_other_paths(tmp_path: Path, guard: Guard) -> None:
    """Отказ на один путь не закрывает всё остальное за воркспейсом."""
    root = tmp_path.parent / "partial"
    guard.deny_path(str(root / "a.txt"))

    assert guard.check_path(str(root / "a.txt"), writing=True)[0] is False
    # Другой путь по-прежнему можно запросить.
    allowed, reason = guard.check_path(str(root / "b.txt"), writing=True)
    assert allowed is False
    assert is_permission_request(reason) is True


def test_grant_after_deny_clears_denial(tmp_path: Path, guard: Guard) -> None:
    outside = tmp_path.parent / "flip-flop" / "f.txt"
    guard.deny_path(str(outside))
    assert guard.check_path(str(outside), writing=True)[0] is False

    guard.grant_path(str(outside))

    assert guard.check_path(str(outside), writing=True)[0] is True


# ------------------------------------------------- полный доступ без вопросов


def test_full_access_does_not_ask_permission(tmp_path: Path) -> None:
    """Полный доступ — это уже ответ на вопрос «можно ли выходить наружу».

    Спрашивать после того, как пользователь выбрал максимум, значило бы
    спрашивать про то, на что он уже ответил.
    """
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)
    outside = tmp_path.parent / "full" / "f.txt"

    allowed, reason = guard.check_path(str(outside), writing=True)

    assert allowed is True
    assert reason == ""


def test_write_access_still_asks(tmp_path: Path) -> None:
    """Обычный режим — как раз тот, где вопрос нужен."""
    guard = Guard(access=AccessLevel.WRITE)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)
    outside = tmp_path.parent / "normal" / "f.txt"

    allowed, reason = guard.check_path(str(outside), writing=True)

    assert allowed is False
    assert is_permission_request(reason) is True


def test_read_access_still_asks(tmp_path: Path) -> None:
    guard = Guard(access=AccessLevel.READ)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)

    allowed, reason = guard.check_path(str(tmp_path.parent / "f.txt"), writing=False)

    assert allowed is False
    assert is_permission_request(reason) is True


def test_full_access_hard_boundary_still_blocks(tmp_path: Path) -> None:
    """Жёсткая граница — осознанный запрет, полный доступ его не отменяет."""
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace(tmp_path, "ws", soft_boundary=False)
    outside = tmp_path.parent / "hard" / "f.txt"

    allowed, reason = guard.check_path(str(outside), writing=True)

    assert allowed is False
    assert is_permission_request(reason) is False


def test_full_access_respects_denial(tmp_path: Path) -> None:
    """Явный отказ по пути остаётся в силе даже при полном доступе."""
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)
    outside = tmp_path.parent / "denied-full" / "f.txt"
    guard.deny_path(str(outside))

    assert guard.check_path(str(outside), writing=True)[0] is False


def test_full_access_tool_writes_outside(tmp_path: Path) -> None:
    """Сквозной путь: инструмент пишет наружу без вопроса."""
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)
    outside_dir = tmp_path.parent / "full-write"
    outside_dir.mkdir(parents=True, exist_ok=True)
    target = outside_dir / "out.txt"

    result = run_tool("write_file", guard, base=tmp_path,
                      path=str(target), content="готово")

    assert result.ok is True
    assert result.needs_permission is False
    assert target.read_text(encoding="utf-8") == "готово"
    target.unlink()
    outside_dir.rmdir()


def test_denial_inside_workspace_is_ignored(tmp_path: Path, guard: Guard) -> None:
    """Внутри воркспейса отказ не действует: там и так всё разрешено."""
    inside = tmp_path / "x.txt"
    guard.deny_path(str(inside))
    assert guard.check_path(str(inside), writing=True)[0] is True


def test_denied_paths_are_isolated_per_task(tmp_path: Path, guard: Guard) -> None:
    first = tmp_path.parent / "task-denied"
    guard.denied_paths = [str(first)]

    assert guard.check_path(str(first / "x.txt"), writing=True)[0] is False
    assert guard.check_path(str(guard.workspace_root) + "", writing=True)[0] is True


def test_pending_permission_keeps_task_parked(tmp_path: Path) -> None:
    """Пока запрос не отвечен, задача обязана ждать, а не падать."""
    from hub.store import Store

    store = Store(tmp_path)
    try:
        task_id = store.add_task("задача")
        store.update_task(task_id, status="waiting_permission", payload={})
        store.add_permission(operation="w", path="C:/a.txt", workspace="C:/ws",
                             task_id=task_id)

        assert store.stranded_permission_tasks() == []
    finally:
        store.close()


def test_task_without_request_is_stranded(tmp_path: Path) -> None:
    """Запрос потерялся — задачу разблокировать уже нечем."""
    from hub.store import Store

    store = Store(tmp_path)
    try:
        task_id = store.add_task("задача")
        store.update_task(task_id, status="waiting_permission", payload={})

        stranded = store.stranded_permission_tasks()
        assert [t["id"] for t in stranded] == [task_id]
    finally:
        store.close()


def test_answered_request_strands_task(tmp_path: Path) -> None:
    """Ответили на чужом сервере, задача осталась ждать — тоже тупик."""
    from hub.store import Store

    store = Store(tmp_path)
    try:
        task_id = store.add_task("задача")
        store.update_task(task_id, status="waiting_permission", payload={})
        permission_id = store.add_permission(
            operation="w", path="C:/a.txt", workspace="C:/ws", task_id=task_id)
        store.decide_permission(permission_id, True, scope="once")

        # Задача сама должна была вернуться в очередь; раз этого не
        # произошло, ремонт обязан её подобрать.
        assert [t["id"] for t in store.stranded_permission_tasks()] == [task_id]
    finally:
        store.close()


def test_other_statuses_are_not_stranded(tmp_path: Path) -> None:
    from hub.store import Store

    store = Store(tmp_path)
    try:
        for status in ("done", "failed", "queued", "running", "asking", "cancelled"):
            task_id = store.add_task(f"задача {status}")
            store.update_task(task_id, status=status)

        assert store.stranded_permission_tasks() == []
    finally:
        store.close()


def test_store_denied_paths_scoped(tmp_path: Path) -> None:
    from hub.store import Store

    store = Store(tmp_path)
    try:
        task_id = store.add_task("задача")
        store.decide_permission(
            store.add_permission(operation="w", path="C:/no.txt", workspace="C:/ws",
                                 task_id=task_id),
            False, scope="once")

        assert store.denied_paths() == []
        assert store.denied_paths(task_id=task_id) == ["C:/no.txt"]
        # Отказ не должен выглядеть как разрешение.
        assert store.granted_paths(task_id=task_id) == []
    finally:
        store.close()


def test_store_denied_paths_always(tmp_path: Path) -> None:
    from hub.store import Store

    store = Store(tmp_path)
    try:
        store.decide_permission(
            store.add_permission(operation="w", path="C:/no.txt", workspace="C:/ws"),
            False, scope="always")
        assert store.denied_paths() == ["C:/no.txt"]
    finally:
        store.close()


def test_worker_deny_marks_path_instead_of_granting(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        task_id = worker.store.add_task("задача")
        worker.store.update_task(task_id, status="waiting_permission", payload={})
        permission_id = worker.store.add_permission(
            operation="write_file", path="C:/x.txt",
            workspace=str(tmp_path), task_id=task_id,
        )

        worker.answer_permission(permission_id, False)

        payload = worker.store.get_task(task_id)["payload"]
        assert payload["deny_path"] == "C:/x.txt"
        assert "grant_path" not in payload
    finally:
        worker.store.close()


# ------------------------------------------ модель отказывается словами


def test_mentions_boundary_block_detects_refusal() -> None:
    from hub.agent import mentions_boundary_block

    refusals = [
        "Не могу изменить файл, он вне рабочей директории.",
        "Мне нужен доступ к C:\\data\\x.txt",
        "Для этого нужно разрешение пользователя",
        "Я не могу работать с этим файлом",
        "I need permission to write there",
        "The file is outside the working directory",
        "не удалось получить доступ к пути",
    ]
    for text in refusals:
        assert mentions_boundary_block(text) is True, text


def test_mentions_boundary_block_ignores_normal_text() -> None:
    from hub.agent import mentions_boundary_block

    normal = [
        "Готово, файл изменён.",
        "Изменения внутри рабочей директории внесены.",
        "Создал новый файл readme.md",
        "Проверил доступ к папке, он есть.",
    ]
    for text in normal:
        assert mentions_boundary_block(text) is False, text


def test_paths_outside_finds_external_path(tmp_path: Path) -> None:
    from hub.agent import paths_outside

    outside = tmp_path.parent / "other-proj" / "file.txt"
    text = f"Не могу изменить {outside}, он вне рабочей директории"

    found = paths_outside(text, tmp_path)

    assert len(found) == 1
    assert found[0].lower().endswith("other-proj\\file.txt")


def test_paths_outside_ignores_inside_paths(tmp_path: Path) -> None:
    from hub.agent import paths_outside

    inside = tmp_path / "sub" / "file.txt"

    assert paths_outside(f"Не могу изменить {inside}", tmp_path) == []


def test_paths_outside_without_root() -> None:
    from hub.agent import paths_outside

    assert paths_outside("нужен доступ к C:\\x\\y.txt", None) == []


def test_paths_outside_finds_sibling_prefix(tmp_path: Path) -> None:
    """«data-secret» не считается находящимся в «data», но обе находятся снаружи."""
    from hub.agent import paths_outside

    secret = tmp_path.parent / "data-secret" / "x.txt"

    assert paths_outside(f"нужен доступ к {secret}", tmp_path) != []


# ------------------------------------------------ отказ через диалог агента


def _agent_for_dialog(tmp_path: Path, access=AccessLevel.WRITE):
    from hub.agent import Agent, AgentConfig
    from hub.registry import Registry
    from hub.selector import Selector
    from hub.tiers import TierBook

    registry = Registry(gateways=[], models=[])
    selector = Selector(registry, TierBook({}))
    guard = Guard(access=access)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)
    agent = Agent(selector, guard, AgentConfig(base_dir=str(tmp_path)))
    agent.set_task("задача")
    return agent


def test_refusal_asks_model_to_act_first(tmp_path: Path) -> None:
    """Первая попытка: требуем от модели вызвать инструмент, а не жаловаться."""
    import asyncio

    from hub.agent import MAX_BOUNDARY_NUDGES

    agent = _agent_for_dialog(tmp_path)
    outside = tmp_path.parent / "act-first" / "f.txt"

    handled = asyncio.run(agent._handle_boundary_refusal(
        f"Не могу изменить {outside}, он вне рабочей директории"))

    assert handled is True
    # Запроса ещё нет: сначала даём модели chance исправиться.
    assert agent.pending_permission is None
    assert agent.boundary_nudges == 1
    pushes = [str(m.get("content")) for m in agent.messages
              if m.get("role") == "user" and "не вызвал" in str(m.get("content"))]
    assert pushes, "в диалог не добавлено требование вызвать инструмент"
    assert str(outside).lower() in pushes[0].lower()
    assert agent.boundary_nudges < MAX_BOUNDARY_NUDGES


def test_stubborn_model_gets_permission_request(tmp_path: Path) -> None:
    """Упрямая модель: поднимаем запрос сами, чтобы пользователь увидел окно."""
    import asyncio

    from hub.agent import MAX_BOUNDARY_NUDGES

    agent = _agent_for_dialog(tmp_path)
    outside = tmp_path.parent / "stubborn" / "f.txt"
    text = f"Не могу изменить {outside}, он вне рабочей директории"

    # Модель проигнорировала требование столько раз, сколько разрешено.
    agent.boundary_nudges = MAX_BOUNDARY_NUDGES

    assert asyncio.run(agent._handle_boundary_refusal(text)) is True
    assert agent.pending_permission is not None
    assert str(outside).lower() in agent.pending_permission["path"].lower()
    assert agent.pending_question


def test_full_access_refusal_is_not_handled(tmp_path: Path) -> None:
    """При полном доступе модель упираться не должна, и чинить тут нечего."""
    import asyncio

    agent = _agent_for_dialog(tmp_path, access=AccessLevel.FULL)
    outside = tmp_path.parent / "full-refusal" / "f.txt"

    handled = asyncio.run(agent._handle_boundary_refusal(
        f"Не могу изменить {outside}, он вне рабочей директории"))

    assert handled is False
    assert agent.pending_permission is None
    assert agent.boundary_nudges == 0


def test_hard_boundary_refusal_is_not_handled(tmp_path: Path) -> None:
    """Жёсткая граница: просить не о чем, выход запрещён намеренно."""
    import asyncio

    from hub.agent import Agent, AgentConfig
    from hub.registry import Registry
    from hub.selector import Selector
    from hub.tiers import TierBook

    registry = Registry(gateways=[], models=[])
    selector = Selector(registry, TierBook({}))
    guard = Guard(access=AccessLevel.WRITE)
    guard.set_workspace(tmp_path, "ws", soft_boundary=False)
    agent = Agent(selector, guard, AgentConfig(base_dir=str(tmp_path)))
    agent.set_task("задача")
    outside = tmp_path.parent / "hard-refusal" / "f.txt"

    handled = asyncio.run(agent._handle_boundary_refusal(
        f"Не могу изменить {outside}, он вне рабочей директории"))

    assert handled is False
    assert agent.pending_permission is None


def test_refusal_without_path_is_not_handled(tmp_path: Path) -> None:
    """Отказ без конкретного пути чинить нечем: спрашивать не о чем."""
    import asyncio

    agent = _agent_for_dialog(tmp_path)

    handled = asyncio.run(agent._handle_boundary_refusal(
        "Не могу выполнить задачу, нужен доступ к данным"))

    assert handled is False
    assert agent.boundary_nudges == 0


def test_normal_completion_is_not_handled(tmp_path: Path) -> None:
    import asyncio

    agent = _agent_for_dialog(tmp_path)

    assert asyncio.run(agent._handle_boundary_refusal("Готово, файл изменён.")) is False


def test_nudges_reset_per_task(tmp_path: Path) -> None:
    """Счётчик требований не должен копиться между задачами."""
    agent = _agent_for_dialog(tmp_path)
    agent.boundary_nudges = 2
    agent._reset_cycle()
    assert agent.boundary_nudges == 0


# ------------------------------------------------------------------- сессии


def _worker(tmp_path: Path):
    from hub.worker import Worker

    return Worker(tmp_path)


def test_worker_new_session_keeps_workspace(tmp_path: Path) -> None:
    """Главное требование: новая сессия — та же папка."""
    worker = _worker(tmp_path)
    try:
        first = worker.new_session("первая")["session_id"]

        second = worker.new_session("вторая")["session_id"]

        assert first != second
        assert worker.store.get_session(second)["workspace_id"] == "default"
        assert worker.store.active_session_id() == second
    finally:
        worker.store.close()


def test_worker_new_session_in_other_workspace(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        other = tmp_path.parent / "second-ws"
        other.mkdir(parents=True, exist_ok=True)
        workspace_id = worker.workspaces.add(str(other), name="второй").id

        result = worker.new_session("работа", workspace_id=workspace_id)

        assert result["ok"] is True
        # Сессия принадлежит новой папке, и папка стала активной.
        assert worker.store.get_session(result["session_id"])["workspace_id"] == workspace_id
        assert worker.workspaces.active_id == workspace_id
    finally:
        worker.store.close()
        import shutil
        shutil.rmtree(other, ignore_errors=True)


def test_worker_new_session_unknown_workspace(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        result = worker.new_session("x", workspace_id="нет-такого")
        assert result["ok"] is False
    finally:
        worker.store.close()


def test_worker_new_session_names_by_default(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        session_id = worker.new_session()["session_id"]
        assert worker.store.get_session(session_id)["name"]
    finally:
        worker.store.close()


def test_worker_switch_session_moves_workspace(tmp_path: Path) -> None:
    """Сессия живёт в папке, поэтому переключаемся вместе с ней."""
    worker = _worker(tmp_path)
    try:
        other = tmp_path.parent / "switch-ws"
        other.mkdir(parents=True, exist_ok=True)
        other_id = worker.workspaces.add(str(other), name="другой").id
        other_session = worker.new_session("там", workspace_id=other_id)["session_id"]

        result = worker.switch_session(other_session)

        assert result["ok"] is True
        assert worker.workspaces.active_id == other_id
        assert worker.store.active_session_id() == other_session
    finally:
        worker.store.close()
        import shutil
        shutil.rmtree(other, ignore_errors=True)


def test_worker_switch_unknown_session(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        assert worker.switch_session("нет")["ok"] is False
    finally:
        worker.store.close()


def test_worker_switch_session_with_missing_workspace(tmp_path: Path) -> None:
    """Сессия осталась, а папку удалили: сообщаем, а не переключаемся молча."""
    worker = _worker(tmp_path)
    try:
        other = tmp_path.parent / "vanishing-ws"
        other.mkdir(parents=True, exist_ok=True)
        other_id = worker.workspaces.add(str(other), name="исчезающая").id
        other_session = worker.new_session("x", workspace_id=other_id)["session_id"]
        import shutil
        shutil.rmtree(other, ignore_errors=True)
        worker.workspaces.remove(other_id)

        result = worker.switch_session(other_session)

        assert result["ok"] is False
        assert "пропала" in result["error"]
    finally:
        worker.store.close()


def test_worker_remove_active_session_picks_another(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        first = worker.new_session("первая")["session_id"]
        second = worker.new_session("вторая")["session_id"]

        result = worker.remove_session(second)

        assert result["ok"] is True
        assert worker.store.active_session_id() == first
    finally:
        worker.store.close()


def test_worker_cannot_remove_last_session(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        only = worker.new_session("единственная")["session_id"]

        result = worker.remove_session(only)

        assert result["ok"] is False
        assert "последнюю сессию" in result["error"]
        assert worker.store.get_session(only) is not None
    finally:
        worker.store.close()


def test_worker_remove_session_creates_one_if_all_gone(tmp_path: Path) -> None:
    """Страховка на случай базы без сессий: переписка должна на чём-то держаться.

    Сценарий недостижим через обычный интерфейс — хранилище не даёт удалить
    последнюю сессию папки, — поэтому состояние создаётся напрямую.
    """
    worker = _worker(tmp_path)
    try:
        worker.new_session("здесь")
        session_id = worker.store.active_session_id()
        worker.store._exec("DELETE FROM sessions WHERE id = ?", (session_id,))
        worker.store._exec(
            "DELETE FROM sessions WHERE workspace_id = 'default'"
        )
        # Снова сессия для удаления, но последняя — снять её нельзя.
        assert worker.remove_session(session_id)["ok"] is False

        # Теперь оставляем воркспейс совсем без сессий и зовём ensure.
        restored = worker.store.ensure_session("default")
        assert worker.store.get_session(restored)["workspace_id"] == "default"
    finally:
        worker.store.close()


def test_worker_remove_session_refuses_last_one(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        only = worker.new_session("единственная")["session_id"]

        result = worker.remove_session(only)

        assert result["ok"] is False
        assert worker.store.get_session(only) is not None
    finally:
        worker.store.close()


def test_worker_rename_session(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        session_id = worker.new_session("черновик")["session_id"]

        result = worker.rename_session(session_id, "чистовик")

        assert result["ok"] is True
        assert result["session"]["name"] == "чистовик"
    finally:
        worker.store.close()


def test_worker_sessions_lists_active_workspace(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        session_id = worker.new_session("работа")["session_id"]

        result = worker.sessions()

        assert result["active"] == session_id
        assert result["workspace_id"] == "default"
        assert session_id in [s["id"] for s in result["sessions"]]
    finally:
        worker.store.close()


def test_worker_enqueue_attaches_active_session(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        session_id = worker.new_session("работа")["session_id"]

        task_id = worker.enqueue("задача")["task_id"]

        assert worker.store.get_task(task_id)["session_id"] == session_id
    finally:
        worker.store.close()


def test_worker_enqueue_explicit_session(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        first = worker.new_session("первая")["session_id"]
        second = worker.new_session("вторая")["session_id"]

        task_id = worker.enqueue("задача", session_id=first)["task_id"]

        assert worker.store.get_task(task_id)["session_id"] == first
        # Активной осталась вторая: явный выбор задачи не переключает диалог.
        assert worker.store.active_session_id() == second
    finally:
        worker.store.close()


def test_worker_state_includes_session(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        session_id = worker.new_session("работа")["session_id"]

        state = worker.state()

        assert state["session"] == session_id
        assert session_id in [s["id"] for s in state["sessions"]]
    finally:
        worker.store.close()


def test_bootstrap_leaves_an_active_session(tmp_path: Path) -> None:
    """После старта активная сессия обязана быть, иначе интерфейс пустой.

    ensure_session только находит или создаёт сессию, но не выбирает её
    активной: без явного set_active_session свежая база оставалась с пустой
    активной сессией, а каждый перезапуск плодил новую в никуда.
    """
    import asyncio

    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        asyncio.run(worker._bootstrap())

        active = worker.store.active_session_id()
        assert active, "после старта нет активной сессии"
        assert worker.store.get_session(active)["workspace_id"] == "default"
    finally:
        worker.store.close()


def test_bootstrap_does_not_multiply_sessions(tmp_path: Path) -> None:
    """Перезапуск не должен плодить сессии: активная переиспользуется."""
    import asyncio

    from hub.worker import Worker

    first = Worker(tmp_path)
    try:
        asyncio.run(first._bootstrap())
        chosen = first.store.active_session_id()
        count = len(first.store.list_sessions())
    finally:
        first.store.close()

    second = Worker(tmp_path)
    try:
        asyncio.run(second._bootstrap())
        assert second.store.active_session_id() == chosen
        assert len(second.store.list_sessions()) == count
    finally:
        second.store.close()


def test_bootstrap_session_survives_broken_config(tmp_path: Path) -> None:
    """Битый конфиг шлюзов не должен оставлять интерфейс без сессии.

    Иначе при испорченном config/gateways.json пользователь не видел бы
    ничего и не смог бы понять, что чинить.
    """
    import asyncio

    from hub.worker import Worker

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "gateways.json").write_text(
        "{ сломанный json", encoding="utf-8")

    worker = Worker(tmp_path)
    try:
        asyncio.run(worker._bootstrap())

        # Ошибка загрузки на месте — её покажут в интерфейсе.
        assert worker.last_error
        assert worker.store.active_session_id()
    finally:
        worker.store.close()


def test_worker_session_history_returns_events(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        session_id = worker.new_session("работа")["session_id"]
        task_id = worker.enqueue("задача")["task_id"]
        worker.store.add_event({"type": "step", "text": "шаг"}, task_id=task_id)

        history = worker.session_history(session_id)

        assert history["ok"] is True
        assert [t["id"] for t in history["tasks"]] == [task_id]
        assert any(e.get("type") == "step" for e in history["events"])
    finally:
        worker.store.close()


def test_worker_session_history_unknown(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    try:
        assert worker.session_history("нет")["ok"] is False
    finally:
        worker.store.close()


def test_worker_session_history_ignores_other_sessions(tmp_path: Path) -> None:
    """История чужих сессий не подмешивается — иначе переписка путается."""
    worker = _worker(tmp_path)
    try:
        first = worker.new_session("первая")["session_id"]
        first_task = worker.enqueue("задача один", session_id=first)["task_id"]
        second = worker.new_session("вторая")["session_id"]
        second_task = worker.enqueue("задача два", session_id=second)["task_id"]

        history = worker.session_history(second)

        assert [t["id"] for t in history["tasks"]] == [second_task]
        assert first_task not in [t["id"] for t in history["tasks"]]
    finally:
        worker.store.close()


# ------------------------------------------------------------------- агент


def test_agent_deny_permission_tells_not_to_retry(tmp_path: Path) -> None:
    import asyncio

    from hub.agent import Agent, AgentConfig
    from hub.registry import Registry
    from hub.selector import Selector
    from hub.tiers import TierBook

    registry = Registry(gateways=[], models=[])
    selector = Selector(registry, TierBook({}))
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)
    agent = Agent(selector, guard, AgentConfig(base_dir=str(tmp_path)))
    agent.set_task("задача")
    agent.pending_permission = {"operation": "write_file", "path": "C:/outside.txt"}
    agent.pending_question = "надо?"

    asyncio.run(agent.deny_permission("C:/outside.txt"))

    assert agent.pending_permission is None
    assert agent.pending_question is None
    allowed, reason = guard.check_path("C:/outside.txt", writing=True)
    assert allowed is False
    assert is_permission_request(reason) is False
    refusals = [str(m.get("content")) for m in agent.messages
                if m.get("role") == "user" and "запретил" in str(m.get("content"))]
    assert refusals, "в диалог не добавлено сообщение об отказе"
    assert "C:/outside.txt" in refusals[0]


def test_agent_grant_permission_appends_message(tmp_path: Path) -> None:
    import asyncio

    from hub.agent import Agent, AgentConfig
    from hub.registry import FreeModel, Registry
    from hub.selector import Selector
    from hub.tiers import TierBook

    registry = Registry(
        gateways=[{"id": "groq", "label": "Groq", "base_url": "u",
                   "resolved_url": "u", "api_key": "", "needs_key": True,
                   "has_key": True, "free_models": [], "catalog": []}],
        models=[FreeModel("groq", "m", "static")],
    )
    selector = Selector(registry, TierBook({}))
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace(tmp_path, "ws", soft_boundary=True)
    agent = Agent(selector, guard, AgentConfig(base_dir=str(tmp_path)))
    # Диалог должен существовать: grant_permission дописывает в него ответ.
    agent.set_task("задача")

    agent.pending_permission = {"operation": "write_file", "path": "C:/outside.txt"}
    agent.pending_question = "надо?"

    asyncio.run(agent.grant_permission("C:/outside.txt"))

    assert agent.pending_permission is None
    assert agent.pending_question is None
    assert guard.check_path("C:/outside.txt", writing=True)[0] is True
    # Проверяем по структуре сообщения, а не по русской фразе: тест не должен
    # зависеть от кодировки файла на машине, где он запускается.
    granted_messages = [
        m for m in agent.messages
        if m.get("role") == "user" and str(m.get("content", "")).startswith(
            "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c"
        )
    ]
    assert granted_messages, "в диалог не добавлено сообщение о разрешении"
    assert "C:/outside.txt" in str(granted_messages[0]["content"])
