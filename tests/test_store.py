"""Тесты хранилища состояния и фонового воркера.

Хранилище проверяется на временном каталоге: сеть не нужна, ответы моделей
подставляются заглушкой.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from hub.store import Store


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    instance = Store(tmp_path)
    yield instance
    instance.close()


# ------------------------------------------------------------------ модели


def test_save_and_load_models(store: Store) -> None:
    states = {
        "groq/a": _state("groq/a", last_status="ok", avg_ms=500.0, ok_count=3),
        "groq/b": _state("groq/b", last_status="limited", cooldown_until=time.time() + 300),
    }
    store.save_models(states)

    loaded = store.load_models()

    assert set(loaded) == {"groq/a", "groq/b"}
    assert loaded["groq/a"]["status"] == "ok"
    assert loaded["groq/a"]["avg_ms"] == 500.0
    assert loaded["groq/b"]["status"] == "limited"


def test_save_models_is_upsert(store: Store) -> None:
    store.save_models({"groq/a": _state("groq/a", last_status="unknown")})
    store.save_models({"groq/a": _state("groq/a", last_status="ok", ok_count=1)})

    loaded = store.load_models()
    assert len(loaded) == 1
    assert loaded["groq/a"]["status"] == "ok"


def test_touch_models_keeps_others(store: Store) -> None:
    store.save_models({
        "a": _state("a", last_status="ok"),
        "b": _state("b", last_status="ok"),
    })
    store.touch_models("a", "limited", cooldown_until=time.time() + 60, fails=1)

    loaded = store.load_models()
    assert loaded["a"]["status"] == "limited"
    assert loaded["b"]["status"] == "ok"


def test_touch_models_creates_missing(store: Store) -> None:
    store.touch_models("new/model", "ok", ok_count=1)
    assert store.load_models()["new/model"]["status"] == "ok"


# ------------------------------------------------------------------- пробы


def test_probes_roundtrip(store: Store) -> None:
    store.save_probes({"a": {"status": "ok", "duration_ms": 120}})

    loaded = store.load_probes()
    assert loaded["a"]["status"] == "ok"
    assert loaded["a"]["duration_ms"] == 120


def test_probes_respect_max_age(store: Store) -> None:
    store.save_probes({"a": {"status": "ok"}})
    # max_age=0 отбрасывает всё, что сохранено секунду назад.
    assert store.load_probes(max_age=0) == {}


def test_probes_empty_save_is_noop(store: Store) -> None:
    store.save_probes({})
    assert store.load_probes() == {}


def test_sanity_roundtrip(store: Store) -> None:
    store.save_sanity({"a": {"score": 0.8, "verdict": "usable"}})
    loaded = store.load_sanity()

    assert loaded["a"]["verdict"] == "usable"
    assert loaded["a"]["score"] == 0.8


# ------------------------------------------------------------------ задачи


def test_add_task_returns_id(store: Store) -> None:
    task_id = store.add_task("создай файл")
    assert isinstance(task_id, int)
    assert store.get_task(task_id)["task"] == "создай файл"


def test_new_task_is_queued(store: Store) -> None:
    store.add_task("задача")
    assert store.list_tasks()[0]["status"] == "queued"


def test_next_queued_respects_priority(store: Store) -> None:
    store.add_task("низкий приоритет", priority=9)
    store.add_task("высокий приоритет", priority=1)

    assert store.next_queued_task()["task"] == "высокий приоритет"


def test_next_queued_respects_age(store: Store) -> None:
    store.add_task("первая", priority=5)
    store.add_task("вторая", priority=5)

    assert store.next_queued_task()["task"] == "первая"


def test_next_queued_returns_none_when_empty(store: Store) -> None:
    assert store.next_queued_task() is None


def test_claim_task_marks_running(store: Store) -> None:
    task_id = store.add_task("задача")
    store.claim_task(task_id)

    assert store.get_task(task_id)["status"] == "running"


def test_claim_twice_raises(store: Store) -> None:
    task_id = store.add_task("задача")
    store.claim_task(task_id)

    with pytest.raises(RuntimeError, match="уже выполняется"):
        store.claim_task(task_id)


def test_update_task_fields(store: Store) -> None:
    task_id = store.add_task("задача")
    store.update_task(task_id, status="done", steps=5, models="groq/a,groq/b")

    task = store.get_task(task_id)
    assert task["status"] == "done"
    assert task["steps"] == 5
    assert task["models"] == ["groq/a", "groq/b"]


def test_update_task_ignores_unknown_field(store: Store) -> None:
    task_id = store.add_task("задача")
    store.update_task(task_id, nonsense="x")  # не должно сломаться
    assert store.get_task(task_id)["status"] == "queued"


def test_task_payload_roundtrip(store: Store) -> None:
    task_id = store.add_task("задача", payload={"plan_only": True, "checkpoint": {"a": 1}})

    payload = store.get_task(task_id)["payload"]
    assert payload["plan_only"] is True
    assert payload["checkpoint"] == {"a": 1}


def test_cancel_queued_task(store: Store) -> None:
    task_id = store.add_task("задача")
    assert store.cancel_task(task_id) is True
    assert store.get_task(task_id)["status"] == "cancelled"


def test_cancel_running_task_sets_flag(store: Store) -> None:
    task_id = store.add_task("задача")
    store.claim_task(task_id)

    assert store.cancel_task(task_id) is True
    # Статус остаётся running: воркер доработает текущий шаг и сам переведёт.
    assert store.get_task(task_id)["status"] == "running"
    assert store.get_task(task_id)["payload"]["cancel"] is True


def test_cancel_finished_task_returns_false(store: Store) -> None:
    task_id = store.add_task("задача")
    store.update_task(task_id, status="done")

    assert store.cancel_task(task_id) is False


def test_list_tasks_filter_by_status(store: Store) -> None:
    done_id = store.add_task("готово")
    store.update_task(done_id, status="done")
    store.add_task("в очереди")

    queued = store.list_tasks(status="queued")
    assert len(queued) == 1
    assert queued[0]["task"] == "в очереди"


def test_task_counts(store: Store) -> None:
    a = store.add_task("а")
    b = store.add_task("б")
    store.update_task(a, status="done")
    store.update_task(b, status="running")

    counts = store.task_counts()
    assert counts == {"done": 1, "running": 1}


# ----------------------------------------------------------------- события


def test_event_ids_increase(store: Store) -> None:
    first = store.add_event({"type": "step"})
    second = store.add_event({"type": "step"})

    assert second > first


def test_events_since_returns_new_only(store: Store) -> None:
    first = store.add_event({"type": "one"})
    store.add_event({"type": "two"})

    events = store.events_since(first)
    assert len(events) == 1
    assert events[0]["type"] == "two"


def test_events_carry_id(store: Store) -> None:
    event_id = store.add_event({"type": "step"})
    assert store.events_since(0)[0]["id"] == event_id


def test_events_filter_by_task(store: Store) -> None:
    store.add_event({"type": "a", "task_id": 1})
    store.add_event({"type": "b", "task_id": 2})
    store.add_event({"type": "global"})

    events = store.events_since(0, task_id=2)
    assert len(events) == 1
    assert events[0]["type"] == "b"


def test_last_event_id(store: Store) -> None:
    assert store.last_event_id() == 0
    event_id = store.add_event({"type": "step"})
    assert store.last_event_id() == event_id


def test_trim_events_keeps_recent(store: Store) -> None:
    for index in range(50):
        store.add_event({"type": "step", "n": index})

    store.trim_events(keep=10)
    assert len(store.events_since(0, limit=200)) == 10


def test_events_survive_non_json_payload(store: Store) -> None:
    store.add_event({"type": "x", "obj": object()})
    # Не должно бросать: payload сериализуется через default=str.
    assert store.events_since(0)[0]["type"] == "x"


# -------------------------------------------------------------------- meta


def test_meta_roundtrip(store: Store) -> None:
    store.set_meta("mode", "manual")
    assert store.get_meta("mode") == "manual"


def test_meta_overwrite(store: Store) -> None:
    store.set_meta("mode", "auto")
    store.set_meta("mode", "manual")
    assert store.get_meta("mode") == "manual"


def test_meta_default(store: Store) -> None:
    assert store.get_meta("missing", "fallback") == "fallback"


def test_stats_reports_path(store: Store) -> None:
    store.add_task("задача")
    stats = store.stats()

    assert stats["tasks"]["queued"] == 1
    assert stats["path"].endswith("zagent.db")


# --------------------------------------------------------- восстановление


def test_state_survives_restart(tmp_path: Path) -> None:
    """Главное свойство: перезапуск не теряет карантины и очередь."""
    first = Store(tmp_path)
    first.save_models({"groq/a": _state("groq/a", last_status="limited", fails=2)})
    first.save_probes({"groq/a": {"status": "limited", "duration_ms": 0}})
    task_id = first.add_task("важная задача", payload={"plan_only": True})
    first.close()

    second = Store(tmp_path)
    models = second.load_models()
    tasks = second.list_tasks()

    assert models["groq/a"]["status"] == "limited"
    assert models["groq/a"]["fails"] == 2
    assert tasks[0]["id"] == task_id
    assert tasks[0]["payload"]["plan_only"] is True
    second.close()


def test_store_creates_directory(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "path"
    instance = Store(nested)
    try:
        # Store сам создаёт <root>/web-state/ и кладёт туда базу.
        assert (nested / "web-state" / "zagent.db").is_file()
    finally:
        instance.close()


def test_context_manager_closes(tmp_path: Path) -> None:
    with Store(tmp_path) as instance:
        instance.add_task("задача")
    # Повторное открытие должно увидеть задачу.
    with Store(tmp_path) as second:
        assert len(second.list_tasks()) == 1


# --------------------------------------------------------- режим журнала


def test_база_создаётся_в_режиме_wal(store: Store) -> None:
    """WAL включается при создании базы и виден в сводке.

    Режим journal_mode=WAL записывается в заголовок файла, поэтому его
    проверяет и новое подключение: настройка должна переживать перезапуск,
    а не действовать только внутри текущего процесса.
    """
    import sqlite3

    assert store.journal_mode == "wal", store.journal_mode
    assert store.stats()["journal_mode"] == "wal"

    side = sqlite3.connect(str(store.path))
    try:
        row = side.execute("PRAGMA journal_mode").fetchone()
        assert str(row[0]).lower() == "wal", row
    finally:
        side.close()


def test_читатель_не_блокирует_писателя(store: Store) -> None:
    """Главное свойство WAL: чтение из HTTP-потока не держит запись воркера.

    До WAL база была в rollback-режиме, и второй процесс получал
    `database is locked` на первой же записи, пока первый что-то читал.
    Проверка идёт через два отдельных подключения к файлу Store, потому что
    внутри самого Store запросы сериализует один RLock и конфликта не видно.
    """
    import sqlite3

    store.add_task("задача")

    reader = sqlite3.connect(str(store.path))
    writer = sqlite3.connect(str(store.path))
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM tasks").fetchall()

        # Короткое ожидание специально: в rollback-режиме запись здесь
        # упрётся в блокировку, и тест должен это показать сразу, а не
        # висеть пять секунд положенного busy_timeout.
        writer.execute("PRAGMA busy_timeout=200")
        writer.execute("INSERT INTO meta (key, value) VALUES ('from_writer', '1')")
        writer.commit()
        reader.rollback()

        # meta хранит JSON, поэтому '1' читается как число.
        assert store.get_meta("from_writer") == 1
    finally:
        reader.close()
        writer.close()


def test_старая_база_переводится_в_wal_при_открытии(tmp_path: Path) -> None:
    """Существующая база переводится в WAL при следующем открытии.

    Обновление не должно требовать от пользователя удалять состояние:
    файл базы лежит в web-state/ и переживает версии программы.
    """
    import sqlite3

    state = tmp_path / "web-state"
    state.mkdir(parents=True)
    legacy = sqlite3.connect(str(state / "zagent.db"))
    legacy.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    # meta хранит JSON: строка лежит в кавычках, иначе get_meta её не прочитает.
    legacy.execute("INSERT INTO meta (key, value) VALUES ('старое', '\"значение\"')")
    legacy.commit()
    mode = str(legacy.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    legacy.close()
    assert mode != "wal", "тест должен начинаться с базы не в WAL"

    store = Store(tmp_path)
    try:
        assert store.journal_mode == "wal"
        assert store.get_meta("старое") == "значение"
    finally:
        store.close()


# ------------------------------------------------------------- воркер: очередь


def test_worker_config_roundtrip() -> None:
    from hub.autonomy import AccessLevel, Autonomy, Escalation
    from hub.worker import WorkerConfig

    original = WorkerConfig(
        access=AccessLevel.FULL, autonomy=Autonomy.STRICT,
        escalation=Escalation.ON, base_dir="C:/work", max_steps=7,
        prefer_speed=True, require_vision=True,
    )
    restored = WorkerConfig.from_dict(original.to_dict())

    assert restored.access is AccessLevel.FULL
    assert restored.autonomy is Autonomy.STRICT
    assert restored.escalation is Escalation.ON
    assert restored.base_dir == "C:/work"
    assert restored.max_steps == 7
    assert restored.prefer_speed is True
    assert restored.require_vision is True


def test_worker_config_from_empty() -> None:
    from hub.worker import WorkerConfig

    config = WorkerConfig.from_dict(None)
    assert config.max_steps == 40


def test_worker_config_to_agent_config() -> None:
    from hub.autonomy import AccessLevel
    from hub.worker import WorkerConfig

    config = WorkerConfig(access=AccessLevel.READ, max_steps=3)
    agent_config = config.to_agent_config()

    assert agent_config.max_steps == 3
    assert agent_config.base_dir


def test_worker_enqueue_returns_id(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        result = worker.enqueue("задача")
        assert result["ok"] is True
        assert worker.store.get_task(result["task_id"])["status"] == "queued"
    finally:
        worker.store.close()


def test_флаг_веб_разведки_доходит_до_задачи(tmp_path: Path) -> None:
    """Флаг режима обязан пережить путь от запроса до агента.

    Он проходит через четыре слоя (`/api/tasks` → payload → агент →
    системный промпт), и потеряться может на любом: агент без флага просто
    не получает инструментов и тихо отвечает по памяти.
    """
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        result = worker.enqueue("задача", payload={"web_research": True})
        assert result["ok"] is True
        payload = worker.store.get_task(result["task_id"]).get("payload") or {}
        assert payload.get("web_research") is True, payload
    finally:
        worker.store.close()


def test_состояние_содержит_автопинг(tmp_path: Path) -> None:
    """Отсчёт «следующая проверка через» брался только из события по
    завершении пинга, а до него висел прочерком минуту после запуска."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        ping = worker.state().get("ping")
        assert isinstance(ping, dict), "в состоянии нет сведений об автопинге"
        for field in ("running", "interval", "next_in", "last"):
            assert field in ping, f"в ping нет поля {field}"
    finally:
        worker.store.close()


def test_worker_pause_and_resume(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert worker.pause()["paused"] is True
        assert worker.paused is True
        assert worker.resume()["paused"] is False
    finally:
        worker.store.close()


def test_worker_cancel_without_task(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert worker.cancel(999)["ok"] is False
    finally:
        worker.store.close()


def test_worker_answer_requires_asking_state(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        task_id = worker.store.add_task("задача")
        result = worker.answer(task_id, "ответ")
        assert result["ok"] is False
        assert "queued" in result["error"]

        worker.store.update_task(task_id, status="asking")
        assert worker.answer(task_id, "ответ")["ok"] is True
        assert worker.store.get_task(task_id)["status"] == "queued"
    finally:
        worker.store.close()


def test_worker_answer_stores_checkpoint(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        task_id = worker.store.add_task(
            "задача", payload={"checkpoint": {"messages": [{"role": "user", "content": "x"}]}}
        )
        worker.store.update_task(task_id, status="asking")

        worker.answer(task_id, "давай так")

        payload = worker.store.get_task(task_id)["payload"]
        assert payload["resume_answer"] == "давай так"
        assert payload["checkpoint"]["messages"]
    finally:
        worker.store.close()


def test_worker_subscribe_receives_events(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    received: list[dict] = []
    try:
        unsubscribe = worker.subscribe(received.append)
        worker.emit({"type": "test", "n": 1})
        unsubscribe()
        worker.emit({"type": "test", "n": 2})

        assert len(received) == 1
        assert received[0]["n"] == 1
    finally:
        worker.store.close()


def test_worker_events_persisted(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        worker.emit({"type": "step", "text": "привет"})
        events = worker.store.events_since(0)
        assert events[0]["text"] == "привет"
    finally:
        worker.store.close()


def test_worker_configure_persists(tmp_path: Path) -> None:
    from hub.autonomy import AccessLevel
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        worker.configure(access=3, max_steps=11)
        assert worker.store.get_meta("config")["max_steps"] == 11

        # Новый воркер на том же каталоге должен подхватить настройки.
        second = Worker(tmp_path)
        try:
            assert second.config.max_steps == 11
            assert second.config.access is AccessLevel.FULL
        finally:
            second.store.close()
    finally:
        worker.store.close()


def _state(ref: str, **kw) -> object:
    """Заглушка ModelState: у воркера нужен только набор полей."""
    from hub.selector import ModelState

    gateway, _, model = ref.partition("/")
    return ModelState(ref=ref, gateway=gateway, model=model or ref, **kw)
