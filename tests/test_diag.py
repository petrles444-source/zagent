"""Сборщик ошибок: journal ошибок, который не врёт и не течёт.

Проверяется ровно то, что этот файл может испортить:

* **тишина вместо записи.** Сборщик, который не смог записать, обязан это
  показать счётчиком `lost` — иначе человек увидит «ошибок 0» при
  неисправном диске, то есть ровно то ложное впечатление, ради
  устранения которого всё и затевалось;
* **ключ в журнале.** В текст исключения попадает URL шлюза, а у части
  шлюзов секрет живёт прямо в адресе; ошибка, которая пишет ключ на диск,
  — новая утечка. Ключ заводится по-настоящему и ищется в готовом файле;
* **журнал на полю.** Кольцо должно резать начало, а не расти вечно, и
  первая обрезанная строка обязана выбрасываться: половина JSON в начале
  файла делает журнал нечитаемым ровно в тот момент, когда он понадобился;
* **битая строка.** Запись могла оборваться на середине — одна такая
  строка не должна прятать остальные.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub import diag as diag_mod
from hub.diag import Diag


@pytest.fixture()
def collector(tmp_path: Path) -> Diag:
    """Сборщик на временной папке — свой на тест, чтобы не мешать другим."""
    return Diag(tmp_path)


# ------------------------------------------------------------------ запись

def test_ошибка_пишется_строкой_json(collector: Diag) -> None:
    collector.note("emit_store", ValueError("база закрыта"), event="step")
    lines = collector.path.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["scope"] == "emit_store"
    assert row["type"] == "ValueError"
    assert row["error"] == "база закрыта"
    assert row["event"] == "step"
    assert row["at"] > 0, "время записи не проставлено"


def test_журнал_живёт_рядом_с_базой(collector: Diag) -> None:
    """В `web-state/`, а не в корне: рабочие данные должны быть вместе."""
    assert collector.path is not None
    assert collector.path.name == "diag.jsonl"
    assert collector.path.parent.name == "web-state"


def test_трейс_пишется_только_по_запросу(collector: Diag) -> None:
    """Трейс большой, а нужен в одном случае из ста."""
    collector.note("без", RuntimeError("ошибка"))
    assert "trace" not in collector.recent()[0]

    try:
        raise RuntimeError("подробная ошибка")
    except RuntimeError as exc:
        collector.note("с", exc, trace=True)
    row = collector.recent()[0]
    assert "подробная ошибка" in row["trace"]


# ---------------------------------------------------------------- тишина

def test_сборщик_не_умеет_сломать_программу(tmp_path: Path) -> None:
    """Ошибка внутри обработчика не имеет права уйти наружу.

    Диагностика, которая роняет программу, хуже отсутствия диагностики:
    она ломает ровно тот момент, который человек пытается расследовать.
    """
    # Путь, куда писать нельзя: файл вместо папки.
    blocked = tmp_path / "blocked"
    blocked.write_text("не папка", encoding="utf-8")
    bad = Diag(blocked / "web-state")
    bad.note("с", ValueError("что-то"))  # не должно бросить
    assert bad.lost == 1, "потерянная запись обязана учитываться"


def test_без_корня_записи_считаются_потерянными() -> None:
    """До старта воркера папка установки неизвестна — и это видно."""
    empty = Diag(None)
    empty.note("что-то", ValueError("x"))
    assert empty.lost == 1
    assert empty.recent() == []


def test_счётчик_потерянных_виден_в_сводке(collector: Diag) -> None:
    stats = collector.stats()
    assert stats["count"] == 0
    assert stats["lost"] == 0
    assert stats["path"].endswith("diag.jsonl")

    collector.note("место", ValueError("x"))
    assert collector.stats()["count"] == 1


# ----------------------------------------------------------------- ключи

def test_ключ_из_секретов_не_попадает_в_журнал(tmp_path: Path) -> None:
    """Самая дорогая ошибка этого инструмента — записать ключ на диск."""
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "secrets.local.json").write_text(
        '{"openrouter": ["sk-or-v1-НАСТОЯЩИЙКЛЮЧ0123456789"]}',
        encoding="utf-8",
    )
    coll = Diag(tmp_path)
    coll.note("http", RuntimeError(
        "не отвечает https://openrouter.ai/api/v1/v1/chat/completions"
        "?key=sk-or-v1-НАСТОЯЩИЙКЛЮЧ0123456789"), trace=True)

    text = coll.path.read_text(encoding="utf-8")
    assert "НАСТОЯЩИЙКЛЮЧ" not in text, "ключ утёк в журнал"
    assert "sk-or-v1" not in text
    assert "***" in text, "вместо ключа должен быть маркер"


# ---------------------------------------------------------------- кольцо

def test_журнал_обрезается_а_не_растёт(tmp_path: Path) -> None:
    """Кольцо: начало уходит, конец остаётся."""
    coll = Diag(tmp_path, keep_bytes=2048)
    for i in range(200):
        coll.note("поток", ValueError(f"ошибка номер {i}"))

    size = coll.path.stat().st_size
    assert size <= coll.keep_bytes, f"журнал вырос до {size} при лимите 2048"

    recent = coll.recent(limit=5)
    # recent() отдаёт новые первыми, поэтому свежая запись — в начале.
    assert recent[0]["error"].endswith("ошибка номер 199"), recent[0]["error"]


def test_после_обрезки_каждая_строка_читается(tmp_path: Path) -> None:
    """Обрезка посередине JSON не должна ломать чтение журнала."""
    coll = Diag(tmp_path, keep_bytes=2048)
    for i in range(120):
        coll.note("поток", ValueError(f"ошибка номер {i} " + "х" * 40))

    rows = coll.recent(limit=1000)
    bad = [r for r in rows if r.get("error") == "битая строка журнала"]
    assert not bad, "после обрезки осталась нечитаемая строка"


def test_битая_строка_не_прячет_остальные(collector: Diag) -> None:
    """Запись могла оборваться — журнал обязан быть полезным и после этого."""
    collector.note("до", ValueError("нормальная"))
    with collector.path.open("a", encoding="utf-8") as handle:
        handle.write('{"scope": "оборвана", "err')
    collector.note("после", ValueError("тоже нормальная"))

    rows = collector.recent()
    errors = [r.get("error") for r in rows]
    assert "нормальная" in errors
    assert "тоже нормальная" in errors
    assert "битая строка журнала" in errors


# --------------------------------------------------------------- чтение

def test_recent_отдаёт_новые_первыми(collector: Diag) -> None:
    for i in range(5):
        collector.note("поток", ValueError(f"{i}"))
    rows = collector.recent()
    assert rows[0]["error"] == "4"
    assert rows[-1]["error"] == "0"


def test_recent_уважает_лимит(collector: Diag) -> None:
    for i in range(50):
        collector.note("поток", ValueError(f"{i}"))
    assert len(collector.recent(limit=7)) == 7


def test_очистка_стирает_файл_но_не_счётчики(collector: Diag) -> None:
    collector.note("место", ValueError("x"))
    collector.clear()
    assert collector.recent() == []
    assert collector.stats()["count"] == 1, "счётчик про текущий запуск"


# ------------------------------------------------------- подключение к коду

def test_воркер_настраивает_сборщик(tmp_path: Path) -> None:
    """До старта воркера журнала нет; после — есть, и путь верный."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert diag_mod.DIAG.root == tmp_path
        diag_mod.note("проверка", ValueError("запись дошла"))
        assert (tmp_path / "web-state" / "diag.jsonl").exists()
    finally:
        worker.store.close()


def test_ошибка_журнала_попадает_в_сборщик(tmp_path: Path) -> None:
    """Главная скрытая поломка: emit глотал исключение базы молча.

    Теперь этот случай обязан оставлять след — иначе событие просто
    исчезает, а «в интерфейсе пусто» неотличимо от «интерфейс сломался».
    """
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        def broken(*a, **kw):
            raise RuntimeError("база недоступна")

        worker.store.add_event = broken  # type: ignore[method-assign]
        worker.emit({"type": "step", "task_id": 1})

        rows = diag_mod.DIAG.recent()
        assert rows, "событие пропало без следа"
        assert rows[0]["scope"] == "emit_store"
        assert "база недоступна" in rows[0]["error"]
    finally:
        worker.store.close()


def test_упавший_подписчик_тоже_оставляет_след(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        def bad(_event: dict) -> None:
            raise ValueError("сокет закрыт")

        worker.subscribe(bad)
        worker.emit({"type": "step", "task_id": 2})

        scopes = [r.get("scope") for r in diag_mod.DIAG.recent()]
        assert "emit_subscriber" in scopes
    finally:
        worker.store.close()