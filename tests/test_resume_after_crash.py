"""Краш процесса больше не убивает задачу — Волна 2 п.9.

До правки воркер при старте помечал все running-задачи failed: полчаса
работы пропадали из-за одного рестарта. Теперь чекпоинт дописывается в
базу после каждого шага, а старт поднимает задачу обратно в очередь —
один раз, чтобы крэш-петля не сжигала квоту.

Проверяется всё: три исхода восстановления, сама запись чекпоинта,
передача его от агента воркеру и то, что стартовый код вообще зовёт
восстановление (иначе остальное лежало бы мёртвым грузом).
"""

from __future__ import annotations

import inspect
from pathlib import Path

from hub.agent import Agent, AgentConfig, make_guard
from hub.autonomy import AccessLevel, Autonomy
from hub.worker import RESTART_LIMIT, Worker

CHECKPOINT = {
    "messages": [
        {"role": "system", "content": "ты ассистент"},
        {"role": "user", "content": "сделай отчёт"},
    ],
    "step": 3,
    "plan": "написать отчёт",
}


def add_running(worker: Worker, payload: dict) -> int:
    """Положить задачу в базу так, будто процесс на ней упал."""
    task_id = worker.store.add_task("сделай отчёт", payload=payload)
    worker.store.update_task(task_id, status="running", started_at=1.0)
    return task_id


def test_задача_с_чекпоинтом_возвращается_в_очередь(tmp_path: Path) -> None:
    worker = Worker(tmp_path)
    seen: list[dict] = []
    worker.subscribe(seen.append)
    task_id = add_running(worker, {
        "checkpoint": CHECKPOINT,
        # Одношаговые флаги уже применены до краха — их нельзя проигрывать
        # второй раз, иначе ответ человека попадёт в диалог дважды.
        "resume_answer": "да, делай",
        "approve_plan": True,
        "extra_steps": 10,
    })

    worker._recover_interrupted(worker.store.get_task(task_id))
    task = worker.store.get_task(task_id)

    assert task["status"] == "queued"
    payload = task["payload"]
    assert payload["restart_attempts"] == 1
    assert payload["checkpoint"] == CHECKPOINT
    assert "resume_answer" not in payload
    assert "approve_plan" not in payload
    # То, что не относится к продолжению, остаётся на месте.
    assert payload["extra_steps"] == 10
    assert any(e["type"] == "restarted_after_crash" for e in seen), \
        "в интерфейс не ушло событие о возобновлении"


def test_второй_краш_задачу_уже_не_поднимает(tmp_path: Path) -> None:
    """Петля «упал — поднялся — упал» обязана оборваться по лимиту."""
    worker = Worker(tmp_path)
    task_id = add_running(worker, {
        "checkpoint": CHECKPOINT,
        "restart_attempts": RESTART_LIMIT,
    })

    worker._recover_interrupted(worker.store.get_task(task_id))
    task = worker.store.get_task(task_id)

    assert task["status"] == "failed"
    assert task["error"] == "прервано при перезапуске"
    assert task["finished_at"], "время завершения не проставлено"


def test_без_чекпоинта_возобновлять_нечего(tmp_path: Path) -> None:
    worker = Worker(tmp_path)
    task_id = add_running(worker, {})

    worker._recover_interrupted(worker.store.get_task(task_id))
    task = worker.store.get_task(task_id)

    assert task["status"] == "failed"
    assert task["error"] == "прервано при перезапуске"


def test_отмена_пришедшая_до_краша_уважается(tmp_path: Path) -> None:
    """Отмена ставит флаг в payload; краш не должен её отменять."""
    worker = Worker(tmp_path)
    task_id = add_running(worker, {"checkpoint": CHECKPOINT, "cancel": True})

    worker._recover_interrupted(worker.store.get_task(task_id))
    task = worker.store.get_task(task_id)

    assert task["status"] == "cancelled"
    # Возобновлять не начали: счётчик попыток не тронут.
    assert "restart_attempts" not in task["payload"]


# ------------------------------------------------------- запись чекпоинта


def test_чекпоинт_доезжает_до_базы_и_не_теряет_чужие_правки(tmp_path: Path) -> None:
    worker = Worker(tmp_path)
    task_id = add_running(worker, {"images": ["data:image/png;base64,AAA"]})

    worker._store_checkpoint(task_id, CHECKPOINT)
    payload = worker.store.get_task(task_id)["payload"]

    assert payload["checkpoint"]["step"] == 3
    # Payload перечитан из базы: данные, добавленные после старта, целы.
    assert payload["images"] == ["data:image/png;base64,AAA"]


def test_запись_чекпоинта_к_исчезнувшей_задаче_не_падает(tmp_path: Path) -> None:
    """Задачу могли закрыть, пока писался чекпоинт, — гонка на границе."""
    worker = Worker(tmp_path)
    worker._store_checkpoint(999, CHECKPOINT)  # не должно упасть


# ----------------------------------------------------- передача от агента


def make_agent(tmp_path: Path) -> Agent:
    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=Autonomy.NORMAL)
    guard = make_guard(config)
    guard.set_workspace(str(tmp_path), None)

    class _Sel:
        require_vision = False

        def stats(self) -> dict:
            return {}

    return Agent(_Sel(), guard, config)


def test_агент_отдаёт_чекпоинт_после_каждого_сохранения(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    saved: list[dict] = []
    agent.on_checkpoint = saved.append

    agent.set_task("сделай отчёт")
    agent.save_checkpoint()

    assert len(saved) == 1
    assert saved[0]["messages"][1]["content"] == "сделай отчёт"
    assert saved[0] is agent.checkpoint, "отдан не тот объект, что сохранён"


def test_сломанный_слушатель_не_роняет_сохранение(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)

    def boom(_ck: dict) -> None:
        raise RuntimeError("база недоступна")

    agent.on_checkpoint = boom
    agent.set_task("сделай отчёт")
    agent.save_checkpoint()  # не должно упасть

    assert agent.checkpoint["step"] == 0


# ---------------------------------------------------------- стартовый код


def test_воркер_подписывает_агента_на_чекпоинт() -> None:
    """Мост между агентом и базой: без него обе половины живут отдельно.

    Поведенчески этот вызов прогнать нельзя, не запуская настоящую задачу
    с сетью, поэтому проверяется источник метода, который агента создаёт:
    подпись обязана стоять именно там, где агент собирается под задачу.
    """
    source = inspect.getsource(Worker._execute)
    assert "agent.on_checkpoint" in source
    assert "self._store_checkpoint" in source


def test_стартовый_код_зовёт_восстановление() -> None:
    """Иначе всё вышеперечисленное лежало бы мёртвым грузом."""
    source = inspect.getsource(Worker._bootstrap)
    assert "self._recover_interrupted(task)" in source
    # Решение о судьбе задачи делает восстановление, а не старт напрямую:
    # строка с провалом живёт только в _recover_interrupted.
    assert "прервано при перезапуске" not in source
