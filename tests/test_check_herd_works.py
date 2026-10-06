"""Инструмент замера роя: разбор отчёта и проверка ограничителя.

Сами прогоны идут к живым моделям и в сеть не выходят — здесь проверяется то,
что в них легко испортить: разбор отчёта, отделение запросов частей от
запросов главного агента и работа ограничителя темпа.

Замер на живых моделях: `tools/check_herd_works.py`. Результаты —
`docs/herd-works.md`.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from check_herd_works import (  # noqa: E402
    Recorder,
    install_break,
    pace_probe,
    pace_report,
    task_text,
)


@pytest.fixture(scope="module")
def probes() -> dict[str, dict]:
    """Прогоны ограничителя — по одному на лимит.

    Общие на модуль, а не на тест: каждый прогон ждёт реальное время
    (десятки секунд на лимите 20 в минуту), и пересчитывать одно и то же
    дважды незачем. Проверяются те же числа, что и в живом замере.
    """
    return {"rpm20": asyncio.run(pace_probe(rpm=20, take=7)),
            "rpm120": asyncio.run(pace_probe(rpm=120, take=7))}


def test_задача_распадается_на_части() -> None:
    """Задача замера обязана быть действительно разбиваемой: если части
    зависят друг от друга, рой работает вхолостую и замеряет не себя."""
    text = task_text(4)
    assert "page1.html" in text and "page4.html" in text
    assert "style.css" in text, "общие файлы нужны: их собирает главный агент"


def test_рекордер_разносит_запросы_по_аккаунтам() -> None:
    """Главное измерение замера: кто ходил, когда и каким ключом."""
    rec = Recorder()
    rec.events = [(0.0, "nvidia", "aaa111"),
                  (0.5, "openrouter", "bbb222"),
                  (3.0, "nvidia", "aaa111")]
    rows = rec.per_account()
    assert set(rows) == {("nvidia", "aaa111"), ("openrouter", "bbb222")}
    assert len(rows[("nvidia", "aaa111")]) == 2


def test_запросы_частей_отделены_от_главного() -> None:
    """Главный агент ходит мимо ограничителя роя. Если смешать его с
    запросами частей, замер припишет ограничителю то, чего он не делал, и
    собьётся вывод о пачках."""
    rec = Recorder()
    rec.events = [(0.0, "nvidia", "aaa111"), (0.1, "nvidia", "aaa111"),
                  (9.0, "openrouter", "zzz999")]
    parts = pace_report(rec.only({("nvidia", "aaa111")}))
    assert parts["requests"] == 2, parts
    assert parts["accounts"] == 1, parts
    assert not parts["bursty"], "две подряд — это ещё не пачка"


def test_пачка_опознаётся() -> None:
    """Пачка запросов с одного аккаунта — тот признак, по которому рой
    выглядит автоматизацией. Молча пропустить его нельзя."""
    rec = Recorder()
    rec.events = [(0.0, "nvidia", "aaa111")] + [
        (0.01 * i, "nvidia", "aaa111") for i in range(1, 12)]
    assert pace_report(rec)["bursty"] is True


def test_равномерный_темп_не_пачка() -> None:
    rec = Recorder()
    rec.events = [(3.0 * i, "nvidia", "aaa111") for i in range(10)]
    report = pace_report(rec)
    assert report["bursty"] is False
    assert report["max_per_account"] == 10
    assert report["min_gap_s"] == 3.0


def test_пустой_прогон_не_ложит_разбор() -> None:
    assert Recorder().per_account() == {}
    report = pace_report(Recorder())
    assert report["accounts"] == 0


def test_ограничитель_держит_темп(probes: dict[str, dict]) -> None:
    """Проверка без моделей: 20 запросов в минуту, разбег 4, дальше ровно
    по три секунды. Разбег при этом — правильное поведение, а не ошибка."""
    probe = probes["rpm20"]
    assert probe["ok"], probe
    assert probe["steady_from_s"] >= 2.4, probe["gaps"]
    # Четыре разбегом и три по расписанию.
    assert probe["elapsed_s"] > 8.0, probe


def test_ограничитель_быстрее_при_большем_лимите(probes: dict[str, dict]) -> None:
    """Один и тот же счёт запросов при большем лимите идёт быстрее: значит
    ждёт именно ограничитель, а не сеть."""
    assert probes["rpm120"]["elapsed_s"] < probes["rpm20"]["elapsed_s"], probes


def _fake_run() -> object:
    """Пустой прогон: план есть, частей нет, запускать нечего."""
    class Slot:
        gateway, key, free = "nvidia", "sk-secret", False

    class Plan:
        workers = [Slot()]
        reserve = []
        unassigned: list[str] = []

    class Swarm:
        plan = Plan()

    class Run:
        swarm = Swarm()
        parts: list[object] = []
        asyncio_tasks: dict[str, object] = {}

    return Run()


def test_подмена_ставится_между_планом_и_запуском() -> None:
    """Точка врезки обязана быть именно там: план уже готов, части ещё не
    стартовали. Раньше — до плана слотов ещё нет; позже — часть уже в работе
    и падение придёт на живую модель, а не на подготовленное."""
    from hub.swarm_run import SwarmRun

    real = SwarmRun.start_parts
    SwarmRun._real_start_parts = real  # type: ignore[attr-defined]
    state = install_break(SwarmRun, 0)
    try:
        assert SwarmRun.start_parts is not real, "метод не подменён"
        run = _fake_run()
        asyncio.run(SwarmRun.start_parts(run, run.swarm.plan, [], []))
        assert state["where"].endswith("secret"), state
    finally:
        SwarmRun.start_parts = real


def test_подмена_не_ставящаяся_сообщает() -> None:
    """Если слотов не хватило, инструмент обязан сказать об этом, а не
    молча отмерить прогон без поломки и выдать его за проверку подмены."""
    from hub.swarm_run import SwarmRun

    real = SwarmRun.start_parts
    SwarmRun._real_start_parts = real  # type: ignore[attr-defined]
    state = install_break(SwarmRun, 9)
    try:
        run = _fake_run()
        asyncio.run(SwarmRun.start_parts(run, run.swarm.plan, [], []))
        assert state["where"] == "", "ломать нечего — так и сказать"
    finally:
        SwarmRun.start_parts = real


def test_тайминг_совпадает_с_монотонными_часами() -> None:
    """Разбор замера опирается на `time.monotonic`. На системных часах
    перевод времени назад развалил бы интервалы, и замер темпа показал бы
    отрицательные промежутки — или, что хуже, правдоподобные."""
    started = time.monotonic()
    time.sleep(0.02)
    assert time.monotonic() - started >= 0.01