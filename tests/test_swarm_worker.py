"""Субагенты на настоящем воркере: разбить, назначить, выполнить, собрать.

Тесты в `test_subagents.py` проверяют отдельные куски: разбор частей, выбор
модели, запреты, след. Здесь проверяется связка целиком, потому что разрыв
живётся именно на стыке — например, воркер звал `self._reset_cycle()` вместо
`agent._reset_cycle()`, и ошибка не выявлялась ни одним из кусковых тестов:
метода у воркера просто нет, и падение вылезало только на живой задаче.

Модели не вызываются: подставляется заглушка, которая отвечает заранее
заготовленным разбиением и коротким «готово».
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
from hub.tiers import TierBook  # noqa: E402

SPLIT = json.dumps({"parts": [
    {"title": "дизайн", "brief": "сверстай главную страницу",
     "files": ["index.html"]},
    {"title": "стили", "brief": "напиши стили страницы",
     "files": ["assets/style.css"]},
]}, ensure_ascii=False)


class FakeSelector:
    """Селектор с одной заведомо рабочей моделью."""

    class State:
        gateway, model = "a", "быстрая"
        avg_ms, last_status, cooldown_left = 400, "ok", 0

    def __init__(self) -> None:
        self.tierbook = TierBook.empty()
        self.states = {"a/быстрая": self.State()}
        self.require_vision = False
        self.registry = type("R", (), {"gateways": []})()

    def stats(self) -> dict[str, Any]:
        return {}


class FakeCaller:
    """Отвечает заготовленным текстом и запоминает, что ему сказали."""

    def __init__(self, script: list[str] | None = None) -> None:
        self.script = list(script or [])
        self.pinned: str | None = None
        self.asked: list[dict[str, Any]] = []

    async def ask(self, messages: list[dict], **kw: Any) -> dict[str, Any]:
        self.asked.append({"messages": messages, "kw": kw,
                           "pinned": self.pinned})
        text = self.script.pop(0) if self.script else "готово"
        return {"text": text, "tokens_in": 1, "tokens_out": 1,
                "duration_ms": 1, "status": 200, "raw": {}, "error": None,
                "reasoning": "", "cost": None, "limits": {}}


def _config(base: Path) -> AgentConfig:
    return AgentConfig(base_dir=str(base), access=AccessLevel.FULL,
                       autonomy=Autonomy.YOLO, max_steps=3)


def _candidate():
    from hub.assign import Candidate

    return [Candidate(ref="a/быстрая", gateway="a", model="быстрая", tier=1,
                      vision=True, tools=True, avg_ms=400, free_keys=1,
                      spare=10_000)]


@pytest.fixture()
def swarm(monkeypatch: pytest.MonkeyPatch):
    """Готовое окружение: воркер с одним кандидатом и заглушкой вместо сети.

    Отдаётся функцией, потому что у каждой проверки свой сценарий ответов
    модели и свой набор того, что надо посмотреть после прогона.
    """
    import hub.assign as assign_module

    monkeypatch.setattr(assign_module, "collect_candidates",
                        lambda selector, keyring: _candidate())

    made: dict[str, Any] = {}

    def start(tmp_path: Path, script: list[str],
              boom_part: int | None = None) -> dict[str, Any]:
        from hub.worker import Worker

        worker = Worker(tmp_path)
        worker.selector = FakeSelector()

        guard = make_guard(_config(tmp_path))
        guard.set_workspace(str(tmp_path), None)
        main = FakeCaller(script)
        agent = Agent(worker.selector, guard, _config(tmp_path), caller=main)

        # Воркер сам создаёт вызывающего для каждой части. Заглушка отвечает
        # заготовленным текстом и записывает, какую модель ей закрепили:
        # именно это и проверяется — выбор должен быть зафиксирован.
        import hub.worker as worker_module

        pinned: list[str | None] = []
        count = {"n": 0}

        class PartCaller(FakeCaller):
            def __init__(self) -> None:
                super().__init__(["сверстал главную", "написал стили"])

            def __setattr__(self, name: str, value: Any) -> None:
                if name == "pinned":
                    pinned.append(value)
                super().__setattr__(name, value)

        def factory(selector: Any, **kw: Any) -> PartCaller:
            caller = PartCaller()
            count["n"] += 1
            if boom_part == count["n"]:
                async def boom(*a: Any, **k: Any) -> dict[str, Any]:
                    raise RuntimeError("модель упала")
                caller.ask = boom  # type: ignore[method-assign]
            return caller

        monkeypatch.setattr(worker_module, "AutoCaller", factory)

        decider = FakeCaller([SPLIT])
        agent.set_task("сделай страницу")
        made.update(worker=worker, agent=agent, main=main, decider=decider,
                    pinned=pinned)
        return made

    yield start

    worker = made.get("worker")
    if worker is not None:
        worker.store.close()


def _run(env: dict[str, Any], task: str = "сделай страницу из двух файлов",
         wanted: int = 2) -> dict[str, Any]:
    return asyncio.run(env["worker"]._run_swarm(
        {"id": 1, "task": task}, env["agent"], _config(Path(env["agent"].config.base_dir)),
        wanted=wanted, decider=env["decider"]))


def test_разбитые_части_выполняются_и_собираются(swarm, tmp_path: Path) -> None:
    env = swarm(tmp_path, ["проверил, всё собрано"])
    result = _run(env)

    info = result.get("swarm")
    assert info is not None, "результат должен содержать сводку о частях"
    assert info["parts"] == 2
    assert info["ok"] == 2, info

    # Разбиение спрашивалось отдельно и отдельным промтом.
    split = env["decider"].asked
    assert len(split) == 1, split
    text = json.dumps(split[0]["messages"], ensure_ascii=False)
    assert "сделай страницу из двух файлов" in text
    # Разбиение решается один раз и на холодную: чем стабильнее ответ,
    # тем меньше шанс, что одна и та же задача разобьётся по-разному.
    assert split[0]["kw"].get("temperature") == 0.0, split[0]["kw"]


def test_разбиение_спрашивает_структуру(swarm, tmp_path: Path) -> None:
    """Модель должна знать, что от неё ждут: перечень частей с областями."""
    env = swarm(tmp_path, ["готово"])
    _run(env)
    text = json.dumps(env["decider"].asked[0]["messages"], ensure_ascii=False)
    assert "files" in text, text[:400]
    assert "brief" in text, text[:400]


def test_каждая_часть_получает_свои_файлы_и_запреты(swarm, tmp_path: Path) -> None:
    """Части не должны затирать друг друга: у каждой свои файлы."""
    env = swarm(tmp_path, ["проверил"])
    seen: list[Any] = []

    original = Agent.__init__

    def spy(self: Agent, *a: Any, **kw: Any) -> None:
        original(self, *a, **kw)
        seen.append(self.guard)

    patch = pytest.MonkeyPatch()
    patch.setattr(Agent, "__init__", spy)
    try:
        _run(env)
    finally:
        patch.undo()

    # Последний guard — главного агента, он собирает результат. Части идут
    # перед ним и у каждой свой guard с собственными границами.
    guards = [g for g in seen if g is not env["agent"].guard]
    assert len(guards) == 2, seen
    granted = [set(guard.granted_paths) for guard in guards]
    assert any(str(tmp_path / "index.html") in g for g in granted), granted
    # Части со стилями выдан конкретный файл, а не вся папка: выдать папку
    # — значит разрешить ей затирать работу соседки по соседним файлам.
    assert any(str(tmp_path / "assets" / "style.css") in g for g in granted), granted
    for guard in guards:
        assert guard.denied_paths, "часть без запрета затирает соседку"


def test_модель_части_закреплена(swarm, tmp_path: Path) -> None:
    """Выбранная модель пробуется первой, а не любая подряд.

    Закрепление — это и есть «осознанный выбор»: часть отдана этой модели
    не потому, что она первая в списке, а потому, что подошла. Дальше по
    кругу — только если у неё кончился лимит, и тогда работа продолжается
    с последнего шага, а не начинается заново.
    """
    env = swarm(tmp_path, ["проверил"])
    _run(env)
    chosen = [ref for ref in env["pinned"] if ref]
    assert chosen == ["a/быстрая", "a/быстрая"], env["pinned"]


def test_разбить_не_вышло_идёт_обычный_путь(swarm, tmp_path: Path) -> None:
    """Мусор вместо разбиения — не повод бросать задачу."""
    env = swarm(tmp_path, ["готово, всё сделал"])
    env["decider"].script = ["не знаю, как разбить"]
    result = _run(env, task="сделай страницу")

    assert result["ok"] is True, result
    assert "swarm" not in result, "разбиения не было — и роя не было"
    assert env["main"].asked, "обычный агент всё равно отработал"


def test_одна_часть_упала_остальные_доехали(swarm, tmp_path: Path) -> None:
    env = swarm(tmp_path, ["доделал упавшую часть сам"], boom_part=1)
    result = _run(env)

    info = result.get("swarm")
    assert info is not None
    assert info["parts"] == 2
    assert info["ok"] == 1, "одна часть упала, вторая отработала"


def test_сводка_доходит_до_главного_агента(swarm, tmp_path: Path) -> None:
    """Главный агент должен видеть, что сделали части, иначе он не проверит."""
    env = swarm(tmp_path, ["проверил, всё на месте"])
    _run(env)

    final = env["main"].asked[-1]
    text = json.dumps(final["messages"], ensure_ascii=False)
    assert "Части работы выполнены параллельно" in text
    assert "доделай сам" in text