"""Рой на настоящем воркере: запуск, подмена, промежуточная сборка.

Кусковые проверки в `test_swarm.py` смотрят план и правила. Здесь проверяется
связка: части действительно стартуют на разных аккаунтах, выбывшая часть
переезжает на резерв и продолжает с чекпоинта, а главный агент работает,
пока части ещё идут.

Модели не вызываются. Подставляется заглушка, которая пишет файл и падает
там, где нужно проверить подмену, — так видно всё поведение целиком и
проверка стоит ноль токенов.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.agent import Agent, AgentConfig, make_guard  # noqa: E402
from hub.autonomy import AccessLevel, Autonomy  # noqa: E402
from hub.keyring import KeyRing  # noqa: E402
from hub.subagents import parse_parts  # noqa: E402
from hub.swarm_run import SwarmRun  # noqa: E402

SPLIT = json.dumps({"parts": [
    {"title": "дизайн", "brief": "сверстай главную", "files": ["index.html"]},
    {"title": "стили", "brief": "напиши стили", "files": ["style.css"]},
    {"title": "скрипты", "brief": "добавь интерактив", "files": ["app.js"]},
]}, ensure_ascii=False)


class _State:
    gateway, model = "a", "модель"
    avg_ms, last_status, cooldown_left = 400, "ok", 0
    tier, fails = 1, 0


class _Book:
    def get(self, gateway: str, model: str) -> Any:
        class Spec:
            tier, vision, tools = 1, False, True
        return Spec()


class _Selector:
    tierbook = _Book()

    def __init__(self) -> None:
        self.states = {"a/модель": _State()}
        self.require_vision = False

    def stats(self) -> dict:
        return {}


class _Ring:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self.rpm = {k: 40 for k in keys}

    def available(self) -> list[str]:
        return list(self.keys)

    def quota_of(self, key: str) -> dict:
        return {}

    def spent_in_minute(self, key: str) -> int:
        return 0

    def rpm_of(self, key: str) -> int:
        return 40

    def is_blocked(self, key: str) -> bool:
        return False


class _KeyRing:
    def __init__(self, count: int = 4) -> None:
        self.ring_obj = _Ring([f"k{i}" for i in range(count)])

    def existing(self, gateway_id: str) -> _Ring:
        return self.ring_obj

    def ring(self, gateway_id: str, keys: list[str]) -> _Ring:
        return self.ring_obj

    def keys_of(self, gateway: dict) -> list[str]:
        return list(self.ring_obj.keys)

    def next_key(self, gateway: dict) -> str | None:
        return self.ring_obj.keys[0]

    def note_spent(self, gateway: dict, key: str) -> None:
        return None


class FakeWorker:
    """Минимальный воркер: воркеру нужны селектор, шлюзы и реестр ключей."""

    def __init__(self, tmp_path: Path) -> None:
        self.selector = _Selector()
        self.keyring = _KeyRing(4)
        self.gateways = [{"id": "a", "key_count": 4, "rpm_per_account": 40}]
        self.events: list[dict[str, Any]] = []
        self.agents: list[Agent] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _config(base: Path) -> AgentConfig:
    return AgentConfig(base_dir=str(base), access=AccessLevel.FULL,
                       autonomy=Autonomy.YOLO, max_steps=3, max_tokens=1024)


def _agent(base: Path, worker: FakeWorker) -> Agent:
    guard = make_guard(_config(base))
    guard.set_workspace(str(base), None)
    agent = Agent(worker.selector, guard, _config(base))
    worker.agents.append(agent)
    return agent


def _parts(count: int = 3):
    data = json.loads(SPLIT)
    data["parts"] = data["parts"][:count]
    return parse_parts(json.dumps(data, ensure_ascii=False))


def _run(worker: FakeWorker, base: Path, parts, *, stub: dict | None = None,
         fail_on: str = "", agent_behaviour=None):
    """Прогнать рой на заглушках."""
    main = _agent(base, worker)

    if stub is not None:
        stub["fail_on"] = fail_on

    if agent_behaviour is None:
        async def _plain() -> dict:
            return {"ok": True, "last": "готово"}
        agent_behaviour = _plain
    main.run = agent_behaviour  # type: ignore[assignment]

    async def run() -> dict[str, Any]:
        run_ = SwarmRun(worker=worker, agent=main, config=_config(base),
                        parts=parts, task={"id": 1, "task": "сделай страницу"},
                        task_context="сделай страницу")
        # Без разброса: тест проверяет логику, а не тайминги.
        import hub.swarm_run as mod
        mod.STAGGER_S = 0.0
        try:
            return await run_.run()
        finally:
            mod.STAGGER_S = 0.8
    return asyncio.run(run()), main


@pytest.fixture()
def model_stub(monkeypatch: pytest.MonkeyPatch):
    """Заглушка вместо агента части: пишет файл, а указанной части падает.

    Падает только первая попытка. Вторая — это уже подменённый рабочий на
    резервном аккаунте, и он обязан отработать, иначе проверка подмены
    ничего не значит.
    """
    state = {"fail_on": "", "calls": [], "failed_once": set()}

    def fake_agent(agent: Agent, messages, **kw):  # noqa: ANN001, ANN003
        state["calls"].append(agent.part or "")

        async def run() -> dict[str, Any]:
            name = agent.part or ""
            if name == state["fail_on"] and name not in state["failed_once"]:
                state["failed_once"].add(name)
                agent.checkpoint = {
                    "messages": [{"role": "system", "content": "с"},
                                 {"role": "user", "content": "часть"}],
                    "step": 2}
                return {"ok": False, "error": "429 лимит запросов", "steps": 2,
                        "last": "", "tools_used": [], "models_used": ["a/модель"]}
            agent.steps.append(
                type("S", (), {"tool": "write_file", "model": "a/модель"})())
            return {"ok": True, "last": "сделал", "steps": 3,
                    "tools_used": ["write_file"], "models_used": ["a/модель"]}

        agent.run = run
        return {"ok": True}

    monkeypatch.setattr(Agent, "set_task", lambda self, task: fake_agent(
        self, [{"role": "user", "content": task}]))
    return state


# =============================================================== запуск


def test_аккаунты_разные_у_разных_частей(tmp_path: Path,
                                        model_stub) -> None:
    """Главное правило роя: один аккаунт — одна часть.

    Ротация по кругу раздала бы двум частям один ключ, и они удвоили бы его
    темп до отказа по лимиту.
    """
    worker = FakeWorker(tmp_path)
    run = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                   config=_config(tmp_path), parts=_parts(3),
                   task={"id": 1, "task": "t"}, task_context="t")
    plan = run.build_plan()
    keys = [s.key for s in plan.workers if not s.free]
    assert len(keys) == len(set(keys)), keys
    assert len(keys) == 3, "три части на четырёх аккаунтах: три рабочих"
    assert len(plan.reserve) == 1, "четвёртый — резерв"


def test_все_части_выполнены(tmp_path: Path, model_stub) -> None:
    worker = FakeWorker(tmp_path)
    run_, _ = _run(worker, tmp_path, _parts(3), stub=model_stub)
    assert run_["parts"] == 3 and run_["ok"] == 3


def test_подмена_продолжает_с_чекпоинта(tmp_path: Path, model_stub) -> None:
    """Главное требование подмены: работа не начинается заново."""
    worker = FakeWorker(tmp_path)
    fail_on = _parts(3)[0].name
    run_, _ = _run(worker, tmp_path, _parts(3), stub=model_stub,
                   fail_on=fail_on)
    kinds = [e["type"] for e in worker.events]
    assert "swarm_handoff" in kinds, worker.events
    assert "swarm_resumed" in kinds, (
        "подменённый рабочий обязан продолжить с чекпоинта, а не заново")
    assert run_["ok"] == 3, "часть не выпала из задачи"


def test_подмена_берёт_аккаунт_из_резерва(tmp_path: Path, model_stub) -> None:
    worker = FakeWorker(tmp_path)
    fail_on = _parts(3)[0].name
    _run(worker, tmp_path, _parts(3), stub=model_stub, fail_on=fail_on)
    note = next(e for e in worker.events if e["type"] == "swarm_handoff")
    assert note["to"] and note["from"]
    assert note["to"] != note["from"], "перевод на тот же аккаунт — не подмена"


def test_событие_подмены_объясняет_причину(tmp_path: Path, model_stub) -> None:
    worker = FakeWorker(tmp_path)
    _run(worker, tmp_path, _parts(3), stub=model_stub,
         fail_on=_parts(3)[0].name)
    note = next(e for e in worker.events if e["type"] == "swarm_handoff")
    assert "429" in note["reason"] or "лимит" in note["reason"], note


def test_план_виден_в_событиях(tmp_path: Path, model_stub) -> None:
    """Человек должен видеть распределение аккаунтов, а не только «работает»."""
    worker = FakeWorker(tmp_path)
    _run(worker, tmp_path, _parts(3), stub=model_stub)
    plan = next(e for e in worker.events if e["type"] == "swarm_plan")
    assert len(plan["plan"]["workers"]) == 3
    assert len(plan["plan"]["reserve"]) == 1
    assert "резерв 1" in plan["plan"]["note"]


def test_итог_виден_в_событиях(tmp_path: Path, model_stub) -> None:
    worker = FakeWorker(tmp_path)
    _run(worker, tmp_path, _parts(3), stub=model_stub)
    done = next(e for e in worker.events if e["type"] == "swarm_done")
    assert done["ok"] == 3 and done["parts"] == 3
    assert done["reserve"] == 1


# =============================================================== темп


def test_темп_настроен_на_каждый_аккаунт(tmp_path: Path, model_stub) -> None:
    """Часть не должна обходить ограничитель: у каждого аккаунта своё ведро
    с его лимитом, иначе рой шлёт всё сразу."""
    worker = FakeWorker(tmp_path)
    run = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                   config=_config(tmp_path), parts=_parts(3),
                   task={"id": 1, "task": "t"}, task_context="t")
    plan = run.build_plan()
    for slot in plan.workers + plan.reserve:
        account = slot.gateway + ":" + slot.key[-8:]
        assert run.pacer.bucket(account).rate_per_min == 40, account


# =============================================================== сборка


def test_главный_агент_видит_невыполненные_части(tmp_path: Path,
                                                model_stub) -> None:
    """Сводка обязана различать «сделано» и «нет»: иначе задача объявляется
    выполненной, а часть файлов не написана."""
    worker = FakeWorker(tmp_path)
    parts = _parts(2)
    run_ = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                    config=_config(tmp_path), parts=parts,
                    task={"id": 1, "task": "t"}, task_context="t")
    run_.swarm = None
    from hub.pacer import Pacer
    from hub.swarm import Swarm
    run_.swarm = Swarm(plan=run_.build_plan(), pacer=run_.pacer)
    run_.swarm.mark_done(parts[0].name, "сверстал")
    run_.swarm.mark_failed(parts[1].name, "модель упала")
    text = run_.swarm.ready()
    assert "НЕ СДЕЛАНО" in text
    assert parts[1].name in text


def test_главный_агент_получает_промежуточный_результат(
        tmp_path: Path, model_stub) -> None:
    """Главный агент не простаивает, пока части идут."""
    worker = FakeWorker(tmp_path)
    parts = _parts(2)
    run_ = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                    config=_config(tmp_path), parts=parts,
                    task={"id": 1, "task": "t"}, task_context="t")
    plan = run_.build_plan()
    for slot, part in zip(plan.workers, parts):
        slot.taken_by = part.name
    run_.swarm.mark_done(parts[0].name, "первая готова")

    seen: list[str] = []
    main = run_.agent

    async def behaviour() -> dict[str, Any]:
        seen.append("\n".join(str(m.get("content")) for m in main.messages))
        return {"ok": True, "last": "жду остальное"}

    main.run = behaviour  # type: ignore[assignment]
    asyncio.run(run_.partial_round())
    assert seen, "главный агент не запускался"
    assert "первая готова" in seen[0], seen[0]
    assert parts[1].name in seen[0], "в сообщении должно быть и то, что в работе"
    assert "НУЖНО ЖДАТЬ" in seen[0], "главному оставлен выбор: ждать или нет"