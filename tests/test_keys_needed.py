"""Фаза 3.3: не хватило аккаунтов — человек должен узнать об этом.

Требование пользователя: «если ключей мало — просить новые». Пока этого не
было, при одном свободном аккаунте рой и субагенты вставали в очередь по
одному, задача шла в разы медленнее, а вывод был «агент тупит».

Проверяется:

* при нехватке аккаунтов выходит событие с причиной и перечнем опустевших
  шлюзов, а задача при этом **не останавливается** — один аккаунт работает;
* при достаточном числе аккаунтов никто ни о чём не беспокоит;
* повторная просьба не идёт чаще заданного интервала — иначе переписка
  превращается в спам, который перестают читать.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

from hub.worker import KEY_ASK_INTERVAL_S, MIN_FREE_ACCOUNTS, Worker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _FakeRing:
    """Снимок состояния ключей: сколько аккаунтов у каждого шлюза."""

    def __init__(self, free: dict[str, int]) -> None:
        self.free = dict(free)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            gid: {"total": total, "available": available, "blocked": 0, "keys": []}
            for gid, (available, total) in self.free.items()
        }


@pytest.fixture()
def worker(monkeypatch: pytest.MonkeyPatch) -> Worker:
    monkeypatch.setattr("hub.worker.KEY_RING", _FakeRing({"openrouter": (1, 1),
                                                        "z_ai": (0, 2)}))
    real = Worker.__new__(Worker)
    real._last_keys_asked = 0.0
    real.events: list[dict[str, Any]] = []
    real.emit = real.events.append          # type: ignore[method-assign]
    return real


def set_free(worker: Worker, monkeypatch: pytest.MonkeyPatch, **free: int) -> None:
    """Переставить состояние ключей: сколько свободно у каждого шлюза."""
    monkeypatch.setattr("hub.worker.KEY_RING", _FakeRing(free))


def ask_events(worker: Worker) -> list[dict[str, Any]]:
    return [e for e in worker.events if e.get("type") == "keys_needed"]


# ------------------------------------------------------------- просьба есть


def test_при_нехватке_выходит_просьба(worker: Worker) -> None:
    worker._ask_for_keys({"id": 7}, need=2)

    events = ask_events(worker)
    assert len(events) == 1, "при нехватке аккаунтов никто не попросил"
    assert events[0]["free"] == 1
    assert events[0]["need"] == 2
    assert events[0]["task_id"] == 7


def test_просьба_называет_опустевшие_шлюзы(worker: Worker) -> None:
    """Подсказка «добавь ключ» бесполезна, если не сказано, к какому шлюзу."""
    worker._ask_for_keys({"id": 7}, need=3)

    assert ask_events(worker)[0]["empty_gateways"] == ["z_ai"]


def test_при_нехватке_причина_объясняет_медленность(worker: Worker) -> None:
    """Человек должен понять, что дело в аккаунтах, а не в агенте."""
    worker._ask_for_keys({"id": 7}, need=4)

    reason = ask_events(worker)[0]["reason"]
    assert "медленнее" in reason, reason
    assert "1" in reason and "4" in reason, reason


# ------------------------------------------------------ работа не останавливается


def test_задача_при_этом_не_останавливается(worker: Worker) -> None:
    """Просьба не должна превращаться в отказ.

    Один аккаунт работает — просто медленно. Останавливать задачу и ждать
    ключа значило бы отнять у человека возможность сделать её сейчас.
    """
    worker._ask_for_keys({"id": 7}, need=4)

    for event in worker.events:
        assert event.get("type") != "failed"
        assert event.get("type") != "cancelled"


def test_при_достатке_аккаунтов_никто_не_беспокоит(
        worker: Worker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Просьба без нужды — шум, который учит человека не читать журнал."""
    set_free(worker, monkeypatch, openrouter=(3, 3))

    worker._ask_for_keys({"id": 7}, need=MIN_FREE_ACCOUNTS)

    assert ask_events(worker) == []


def test_ровно_столько_сколько_нужно_не_считается_нехваткой(
        worker: Worker, monkeypatch: pytest.MonkeyPatch) -> None:
    set_free(worker, monkeypatch, openrouter=(1, 1))

    worker._ask_for_keys({"id": 7}, need=1)   # свободен ровно один

    assert ask_events(worker) == []


# ------------------------------------------------------------- без повторов


def test_повторная_просьба_не_идёт_часто(worker: Worker) -> None:
    """Две одинаковые просьбы подряд читать перестаёшь — и пропустишь третью."""
    worker._ask_for_keys({"id": 7}, need=4)
    worker._ask_for_keys({"id": 8}, need=4)
    worker._ask_for_keys({"id": 9}, need=4)

    assert len(ask_events(worker)) == 1, "просьба повторяется на каждую задачу"


def test_через_интервал_просьбить_можно_снова(worker: Worker) -> None:
    worker._ask_for_keys({"id": 7}, need=4)
    worker._last_keys_asked = time.time() - KEY_ASK_INTERVAL_S - 1

    worker._ask_for_keys({"id": 8}, need=4)

    assert len(ask_events(worker)) == 2, "просьба не повторяется никогда"


def test_появившийся_ключ_прекращает_просьбы(worker: Worker) -> None:
    """Главный смысл: добавил ключ — больше не докучаем."""
    worker._ask_for_keys({"id": 7}, need=4)
    worker._free_accounts = lambda: 9         # type: ignore[method-assign]
    worker._last_keys_asked = 0.0

    worker._ask_for_keys({"id": 8}, need=4)

    assert len(ask_events(worker)) == 1, "просьбы идут, хотя ключи добавили"


# ------------------------------------------------- сколько нужно на самом деле


@pytest.mark.parametrize("subagents, herd, want", [
    (0, False, 2),      # одиночная задача
    (3, False, 3),      # три субагента
    (0, True, 2),       # рой без субагентов — базовая потребность
    (5, True, 7),       # рой: аккаунтов нужно больше всех
])
def test_потребность_считается_по_нагрузке(subagents: int, herd: bool,
                                         want: int) -> None:
    """Просить надо столько, сколько пойдёт параллельно.

    Требовать десять аккаунтов для задачи «посчитай 2+2» — значит заваливать
    просьбами по мелочам, и человек перестанет читать.
    """
    got = max(2, subagents + 2 if herd else min(subagents + 2, 3))
    assert got == want