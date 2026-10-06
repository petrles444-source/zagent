"""Рой агентов: темп, план, резерв, подмена, промежуточная сборка.

Проверяется то, что в рое легко сломать и трудно заметить: темп запросов,
распределение аккаунтов, поведение при отказе и то, что главный агент
работает, пока части ещё идут.

Живые модели не используются. Рой устроен так, что проверяется он целиком:
пять частей по два шага на заглушке дают то же распределение, тот же резерв
и ту же подмену, что и десять шагов настоящих, — но стоят ноль токенов.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.autochoose import Decision, Limits, apply_limits  # noqa: E402
from hub.pacer import (  # noqa: E402
    DEFAULT_RPM,
    Bucket,
    PacedCaller,
    Pacer,
)
from hub.subagents import Part, parse_parts  # noqa: E402
from hub.swarm import (  # noqa: E402
    DUTY,
    Plan,
    Slot,
    Swarm,
    build_slots,
    free_reserve,
    make_plan,
    slot_account,
)
from hub.swarm_run import HERD_SYSTEM, _worth_handoff  # noqa: E402


# =============================================================== ограничитель


def test_ведро_не_выше_лимита() -> None:
    """Ведро наполняется до предела, а не выше: иначе минута проходит за
    полминуты и аккаунт получает вдвое больше своего лимита."""
    b = Bucket(40)
    b.tokens = 40.0
    for _ in range(40):
        assert b.take_now() is True
    assert b.take_now() is False
    assert b.left() == 0


def test_на_старте_короткий_разбег() -> None:
    """Полное ведро на старте — это пачка из сорока запросов в секунду.

    Лимит при этом не превышен, но именно такая пачка выглядит как
    злоупотребление, а ради этого ограничитель и писался.
    """
    b = Bucket(40)
    assert b.left() <= 5, f"разбег {b.left()} запросов — слишком много"


def test_ведро_восполняется_со_временем() -> None:
    """За прошедшую минуту место вернулось — провайдер считает так же."""
    b = Bucket(60)
    b.tokens = 0.0
    b.last = time.monotonic() - 30.0
    assert b.take_now() is True
    assert 28 <= b.left() <= 30


def test_ожидание_не_выше_потолка() -> None:
    """При очень малой скорости ожидание считается минутами; ждать столько
    бессмысленно — темп всё равно упирается в провайдера."""
    b = Bucket(1)
    b.tokens = 0.0
    b.last = time.monotonic() - 0.01
    assert 0.0 < b.wait_seconds() <= 60.0


def test_разные_аккаунты_не_мешают_друг_другу() -> None:
    """Счётчик на аккаунт, а не на задачу: два аккаунта — две независимые
    минуты. Иначе один исчерпал бы лимит, а второй стоял бы впустую."""
    p = Pacer()
    b1 = p.bucket("gw:k1", 5)
    b2 = p.bucket("gw:k2", 5)
    for _ in range(10):
        b1.take_now()
    assert b1.left() == 0, "первый аккаунт исчерпан"
    assert b2.left() > 0, "второй аккаунт не должен страдать из-за первого"


def test_лимит_из_конфиста_меняет_ведро() -> None:
    """Лимит приходит из конфига после первого обращения: слот создаётся на
    разбиении, а rpm известен из gateways.json — порядок не гарантирован."""
    p = Pacer()
    p.bucket("gw:k1")           # создалось с лимитом по умолчанию
    p.set_rpm("gw:k1", 40)
    assert p.bucket("gw:k1").rate_per_min == 40


def test_вызывающий_ждёт_перед_каждым_запросом() -> None:
    """Ожидание на каждом запросе, а не один раз: иначе ограничитель
    превратился бы в задержку на старте.

    Запросов больше, чем короткий разбег: первые проходят сразу, дальше
    темп держится по лимиту — именно это и проверяется.
    """
    class Inner:
        def __init__(self) -> None:
            self.calls = 0

        async def ask(self, messages, **kw):  # noqa: ANN001, ANN003
            self.calls += 1
            return {"ok": True}

    async def scenario() -> tuple[int, float]:
        inner = Inner()
        pacer = Pacer()
        paced = PacedCaller(inner, pacer, "gw:k1", 120)
        started = time.perf_counter()
        for _ in range(10):
            await paced.ask([{"role": "user", "content": "x"}])
        return inner.calls, time.perf_counter() - started

    calls, elapsed = asyncio.run(scenario())
    assert calls == 10
    assert elapsed >= 2.0, (
        f"10 запросов при 120/мин (разбег 4) должны занять не меньше трёх "
        f"секунд, а заняли {elapsed:.2f}")


def test_закрепление_проходит_сквозь_обёртку() -> None:
    class Inner:
        pinned = None

    paced = PacedCaller(Inner(), Pacer(), "gw:k1")
    paced.pinned = "gw/модель"
    assert paced.inner.pinned == "gw/модель"


# =============================================================== слоты


class _State:
    def __init__(self, gateway: str, model: str, ms: int, status: str = "ok",
                 tier: int = 1) -> None:
        self.gateway, self.model = gateway, model
        self.avg_ms, self.last_status = ms, status
        self.tier, self.cooldown_left, self.fails = tier, 0, 0


class _Ring:
    def __init__(self, keys: list[str], blocked: list[str] | None = None) -> None:
        self.keys = keys
        self._blocked = set(blocked or ())

    def available(self) -> list[str]:
        return [k for k in self.keys if k not in self._blocked]


class _KeyRing:
    def __init__(self, rings: dict[str, _Ring]) -> None:
        self._rings = rings

    def existing(self, gateway_id: str) -> _Ring | None:
        return self._rings.get(gateway_id)


class _Spec:
    def __init__(self, tier: int = 1, vision: bool = False, tools: bool = True) -> None:
        self.tier, self.vision, self.tools = tier, vision, tools


class _Book:
    def get(self, gateway: str, model: str) -> _Spec:
        return _Spec(vision="vision" in model, tools="no-tools" not in model)


class _Selector:
    tierbook = _Book()

    def __init__(self, states: dict[str, _State]) -> None:
        self.states = states


def _gateways(*pairs: tuple[str, int, int]) -> list[dict]:
    """Шлюзы: (id, ключей, rpm)."""
    return [{"id": gid, "key_count": n, "rpm_per_account": rpm}
            for gid, n, rpm in pairs]


def _keyring(**counts: int) -> _KeyRing:
    return _KeyRing({gid: _Ring([f"k{i}" for i in range(n)])
                     for gid, n in counts.items()})


def test_слот_это_аккаунт_а_не_модель() -> None:
    """Главное правило: на аккаунт один слот, сколько бы моделей ни было.

    Раздать две модели на один ключ — значит два потребителя одного лимита,
    а не параллельная работа.
    """
    sel = _Selector({
        "a/модель-1": _State("a", "модель-1", 400),
        "a/модель-2": _State("a", "модель-2", 800),
    })
    slots = build_slots(sel, _gateways(("a", 1, 40)), _keyring(a=1))
    assert len(slots) == 1, slots
    assert slots[0].ref == "a/модель-1", "внутри шлюза берётся самая быстрая"


def test_модель_без_инструментов_не_берётся() -> None:
    """Часть, отданная такой модели, не сделает ничего, а аккаунт сгорит."""
    sel = _Selector({
        "a/быстрая-но-бесполезная": _State("a", "no-tools-x", 200),
        "a/годная": _State("a", "годная", 900),
    })
    slots = build_slots(sel, _gateways(("a", 1, 40)), _keyring(a=1))
    assert [s.ref for s in slots] == ["a/годная"], slots


def test_непроверенная_модель_не_кандидат() -> None:
    sel = _Selector({"a/без_замера": _State("a", "без_замера", 0, "")})
    assert build_slots(sel, _gateways(("a", 1, 40)), _keyring(a=1)) == []


def test_заблокированный_аккаунт_не_попадает_в_слоты() -> None:
    ring = _Ring(["k0", "k1"], blocked=["k0"])
    sel = _Selector({"a/модель": _State("a", "модель", 400)})
    slots = build_slots(sel, _gateways(("a", 2, 40)),
                        _KeyRing({"a": ring}))
    assert len(slots) == 1, "выбитый аккаунт в работу не берётся"


def test_лимит_из_конфига_доезжает_до_слота() -> None:
    sel = _Selector({"a/модель": _State("a", "модель", 400)})
    slots = build_slots(sel, _gateways(("a", 1, 40)), _keyring(a=1))
    assert slots[0].rpm == 40


# =============================================================== план


def _parts(n: int) -> list[Part]:
    return parse_parts(json.dumps({"parts": [
        {"title": f"часть {i}", "brief": f"сделай {i}", "files": [f"p{i}.html"]}
        for i in range(n)]}, ensure_ascii=False))


def test_резерв_остаётся_всегда() -> None:
    """Без резерва подменять выбывшего нечем, и первая потеря аккаунта
    останавливает часть."""
    slots = [Slot(gateway="a", key=f"k{i}", ref="a/м", model="м", tier=1,
                  avg_ms=400, vision=False, tools=True, rpm=40)
             for i in range(4)]
    plan = make_plan(slots, _parts(4))
    assert len(plan.workers) == 3, plan.note
    assert len(plan.reserve) == 1, plan.note


def test_доля_занятости_около_семидесяти_процентов() -> None:
    """Проверяется сама доля: 75% — это и есть заявленная «занятость
    мощности на 70–80%»."""
    slots = [Slot(gateway="a", key=f"k{i}", ref="a/м", model="м", tier=1,
                  avg_ms=400, vision=False, tools=True, rpm=40)
             for i in range(8)]
    plan = make_plan(slots, _parts(8))
    busy = sum(1 for s in plan.workers if not s.free)
    assert busy == 6, busy
    assert 0.70 <= busy / 8 <= 0.80, busy / 8


def test_частей_больше_чем_аккаунтов_лишние_ждут() -> None:
    """Лишние части ждут свободного аккаунта, а не встают на чужой ключ."""
    slots = [Slot(gateway="a", key="k0", ref="a/м", model="м", tier=1,
                  avg_ms=400, vision=False, tools=True, rpm=40)]
    plan = make_plan(slots, _parts(3))
    assert len(plan.unassigned) == 2, plan.unassigned


def test_часть_с_картинкой_получает_слот_со_зрением() -> None:
    """Иначе аккаунт сгорит впустую: модель не увидит файл."""
    slots = [
        Slot(gateway="a", key="k0", ref="a/обычная", model="обычная", tier=1,
             avg_ms=300, vision=False, tools=True, rpm=40),
        Slot(gateway="a", key="k1", ref="a/зрячая", model="vision-x", tier=1,
             avg_ms=900, vision=True, tools=True, rpm=40),
    ]
    parts = parse_parts(json.dumps({"parts": [
        {"title": "картинка", "brief": "сделай блок по картинке",
         "files": ["hero.png"]}]}, ensure_ascii=False))
    plan = make_plan(slots, parts, duty=1.0)
    assert plan.unassigned == [], plan.unassigned
    assert next(s for s in plan.workers if s.taken_by).vision is True


def test_пустой_план_не_падает() -> None:
    plan = make_plan([], _parts(2))
    assert plan.workers == [] and plan.unassigned


# =============================================================== подмена


def _slot(i: int, taken: str = "") -> Slot:
    return Slot(gateway="a", key=f"k{i}", ref="a/м", model="м", tier=1,
                avg_ms=400, vision=False, tools=True, rpm=40, taken_by=taken)


def test_подмена_берёт_аккаунт_из_резерва() -> None:
    plan = Plan(workers=[_slot(0, "часть 1")], reserve=[_slot(1)])
    swarm = Swarm(plan=plan, pacer=Pacer())
    fresh = swarm.handoff("часть 1", "429 лимит запросов")
    assert fresh is not None and fresh.key == "k1"
    assert fresh.taken_by == "часть 1"
    assert plan.workers[0].taken_by == "", "прежний слот освобождён"


def test_подмена_предпочитает_тот_же_шлюз() -> None:
    """Другой шлюз — это другая модель, а подмена должна чинить аккаунт, а не
    менять качество работы."""
    plan = Plan(workers=[_slot(0, "часть 1")],
                reserve=[_slot(1), _slot(2), _slot(3)])
    swarm = Swarm(plan=plan, pacer=Pacer())
    swarm.handoff("часть 1", "429")
    assert swarm.slot_of("часть 1").gateway == "a"


def test_без_резерва_подмены_нет() -> None:
    """Часть остаётся невыполненной, и это видно: лучше, чем гонять её по
    чужим аккаунтам и получать тот же отказ."""
    plan = Plan(workers=[_slot(0, "часть 1")], reserve=[])
    swarm = Swarm(plan=plan, pacer=Pacer())
    assert swarm.handoff("часть 1", "429") is None


def test_подмена_ограничена_двумя_разами() -> None:
    """Подменённый аккаунт тоже может оказаться выбит. Но три отказа подряд
    означают, что дело не в аккаунтах, и дальше крутиться бессмысленно."""
    plan = Plan(workers=[_slot(0, "часть 1")],
                reserve=[_slot(1), _slot(2), _slot(3)])
    swarm = Swarm(plan=plan, pacer=Pacer())
    first = swarm.handoff("часть 1", "429")
    second = swarm.handoff("часть 1", "429")
    assert first is not None and first.key == "k1"
    assert second is not None and second.key == "k2"
    assert swarm.handoff("часть 1", "429") is None


def test_подмена_событие_видно() -> None:
    """Человек должен видеть, что часть перевели, а не бросили."""
    events: list[dict[str, Any]] = []
    plan = Plan(workers=[_slot(0, "часть 1")], reserve=[_slot(1)])
    swarm = Swarm(plan=plan, pacer=Pacer(), emit=events.append)
    swarm.handoff("часть 1", "кончился лимит")
    kinds = [e["type"] for e in events]
    assert "swarm_handoff" in kinds, events
    note = next(e for e in events if e["type"] == "swarm_handoff")
    assert "кончился лимит" in note["reason"]


def test_подмена_стоит_того_только_при_отказе_аккаунта() -> None:
    """Модель, которая не вызвала инструмент, на другом аккаунте даст то же
    самое. Подменять тут — значит потратить резерв впустую."""
    assert _worth_handoff("429 лимит запросов")
    assert _worth_handoff("Таймаут модели")
    assert _worth_handoff("Ключ отклонён или доступ закрыт (403)")
    assert not _worth_handoff("model refused to call a tool")
    assert not _worth_handoff("Tool choice is none, but model called a tool")


# =============================================================== сборка


def test_сводка_разделяет_сделанное_и_нет() -> None:
    """Главный агент должен различать «сделано» и «не сделано» — иначе он
    объявит задачу выполненной."""
    plan = Plan(workers=[_slot(0, "часть 1"), _slot(1, "часть 2")])
    swarm = Swarm(plan=plan, pacer=Pacer())
    swarm.mark_done("часть 1", "сверстал главную")
    swarm.mark_failed("часть 2", "модель упала")
    text = swarm.ready()
    assert "часть 1: сделано" in text
    assert "часть 2: НЕ СДЕЛАНО" in text
    assert swarm.pending() == [], "обе части больше не в работе"


def test_в_работе_остаётся_то_что_не_готово() -> None:
    plan = Plan(workers=[_slot(0, "часть 1"), _slot(1, "часть 2")])
    swarm = Swarm(plan=plan, pacer=Pacer())
    swarm.mark_done("часть 1", "ок")
    assert swarm.pending() == ["часть 2"]


def test_промпт_роя_требует_независимые_части() -> None:
    """Зависимые части в рою работать не могут: все стартуют сразу, и та,
    которой нужен чужой результат, будет ждать в конце."""
    assert "не должны зависеть" in HERD_SYSTEM
    assert "Общие файлы" in HERD_SYSTEM


def test_режим_роя_не_включается_без_аккаунтов() -> None:
    """Четыре аккаунта — минимум: три рабочих и резерв. Меньше и «рой»
    превращается в очередь."""
    decision = Decision(herd=True, reason="много независимых страниц")
    out = apply_limits(decision, Limits(free_accounts=3, max_steps=40))
    assert out.herd is False
    assert "аккаунтов мало" in out.reason


def test_режим_роя_не_включается_при_коротком_лимите_шагов() -> None:
    """Рабочий всё равно не успеет закончить часть, и рой даст брошенную
    работу вместо результата."""
    out = apply_limits(Decision(herd=True),
                       Limits(free_accounts=10, max_steps=6))
    assert out.herd is False


def test_режим_роя_выключается_с_субагентами() -> None:
    """Смешивать два режима в одном прогоне — значит получить ни то ни другое."""
    out = apply_limits(Decision(herd=True),
                       Limits(free_accounts=10, allow_subagents=False))
    assert out.herd is False and out.subagents == 0


def test_решение_роя_разбирается_из_ответа_модели() -> None:
    from hub.autochoose import parse_decision

    got = parse_decision('{"web_research": false, "subagents": 0, '
                         '"herd": true, "reason": "10 независимых страниц"}')
    assert got is not None and got.herd is True


def test_режим_роя_назван_своим_именем() -> None:
    assert Decision(herd=True).mode == "рой"
    assert Decision(herd=True, web_research=True).mode == "рой + разведка"
    assert "herd" in Decision(herd=True).to_dict()