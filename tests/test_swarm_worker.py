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
from hub.subagents import denied_for_all, globs_for_all
from hub.swarm import slot_account  # noqa: E402
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


def _config(base: Path, steps: int = 3) -> AgentConfig:
    return AgentConfig(base_dir=str(base), access=AccessLevel.FULL,
                       autonomy=Autonomy.YOLO, max_steps=steps, max_tokens=1024)


def _agent(base: Path, worker: FakeWorker) -> Agent:
    guard = make_guard(_config(base))
    guard.set_workspace(str(base), None)
    agent = Agent(worker.selector, guard, _config(base))
    worker.agents.append(agent)
    return agent


def _parts(count: int = 3):
    data = json.loads(SPLIT)
    parts = data["parts"]
    # Нужно столько, сколько просят: имена и файлы у части обязаны быть свои.
    while len(parts) < count:
        i = len(parts)
        parts.append({"title": f"ещё {i}", "brief": f"сделай {i}",
                      "files": [f"extra{i}.html"]})
    data["parts"] = parts[:count]
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
        # Тот же расчёт, что и в планировщике: иначе проверка смотрела бы на
        # ведро, которое никто не открывал, и проходила бы вхолостую.
        account = slot_account(slot.gateway, slot.key)
        assert run.pacer.bucket(account).rate_per_min == 40, account


def test_часть_считается_сделанной_по_файлам(tmp_path: Path) -> None:
    """Вердикт с диска, а не от модели.

    Живой прогон 06.10.2026 вскрыл это: части создавали файлы, но не успевали
    сказать «готово» — кончался лимит шагов на последнем ответе. По отчёту
    они считались невыполненными, главный агент получал «НЕ СДЕЛАНО» по
    всем частям, а подмена уводила на резерв тех, кто уже закончил.
    """
    from hub.swarm_run import files_ready

    parts = parse_parts(json.dumps({"parts": [
        {"title": "страница", "brief": "сделай", "files": ["page1.html"]},
        {"title": "скрипты", "brief": "сделай", "files": ["src/*.js"]},
    ]}, ensure_ascii=False))
    assert files_ready(parts[0], tmp_path) == [], "пустая папка — не готово"

    (tmp_path / "page1.html").write_text("<h1>Привет</h1>", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("//", encoding="utf-8")
    assert files_ready(parts[0], tmp_path) == ["page1.html"]
    assert files_ready(parts[1], tmp_path) == ["src/app.js"]


def test_пустой_файл_не_считается_работой(tmp_path: Path) -> None:
    """Файл нулевой длины — это не результат: агент мог создать его и
    бросить на середине."""
    from hub.swarm_run import files_ready

    parts = parse_parts(json.dumps({"parts": [
        {"title": "страница", "brief": "сделай", "files": ["page1.html"]},
    ]}, ensure_ascii=False))
    (tmp_path / "page1.html").write_text("", encoding="utf-8")
    assert files_ready(parts[0], tmp_path) == []


def test_выполненная_часть_не_уходит_в_подмену(tmp_path: Path) -> None:
    """Часть, написавшая свои файлы, не должна переезжать на резервный
    аккаунт: работа уже сделана, второй заход её только испортит."""
    worker = FakeWorker(tmp_path)
    parts = _parts(2)
    by_name = {p.name: p for p in parts}

    def writes_then_no_finish(self: Agent, task: str) -> None:
        part = by_name.get(self.part or "")
        for rel in (part.files if part else ["нет.html"]):
            (tmp_path / rel).write_text("<h1>ок</h1>", encoding="utf-8")

        async def run() -> dict[str, Any]:
            # Модель не сказала «готово»: лимит шагов кончился на ответе.
            return {"ok": False, "last": "", "steps": 4, "tools_used": [],
                    "models_used": ["a/модель"]}

        self.run = run

    import hub.agent as agent_mod
    original = agent_mod.Agent.set_task
    agent_mod.Agent.set_task = writes_then_no_finish
    try:
        run_, _ = _run(worker, tmp_path, parts)
    finally:
        agent_mod.Agent.set_task = original

    assert run_["ok"] == 2, run_
    assert "swarm_handoff" not in [e["type"] for e in worker.events], (
        "готовая часть не должна подменяться")


def test_причина_отказа_берётся_из_шагов(tmp_path: Path,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Основной путь `Agent.run()` не отдаёт ключ `error` вовсе.

    Причина отказа живёт в шагах. Раньше рой читал только `outcome["error"]`,
    всегда получал пустоту, решал, что отказа аккаунта не было, и подмена не
    включалась ни разу — при живом прогоне это стоило трёх упавших частей.
    """
    worker = FakeWorker(tmp_path)

    def bad_key(agent: Agent, task: str) -> None:
        async def run() -> dict[str, Any]:
            step = type("S", (), {"tool": None, "model": "a/модель",
                                  "error": "401 неавторизован"})()
            agent.steps.append(step)
            # Ровно то, что отдаёт настоящий Agent.run().
            return {"ok": False, "steps": 1, "last": "", "tools_used": [],
                    "models_used": ["a/модель"]}

        agent.run = run

    monkeypatch.setattr(Agent, "set_task", bad_key)
    run_, _ = _run(worker, tmp_path, _parts(1))
    assert "swarm_handoff" in [e["type"] for e in worker.events], (
        "отказ аккаунта обязан приводить к подмене")

    note = next(e for e in worker.events if e["type"] == "swarm_handoff")
    assert "401" in note["reason"], note["reason"]


def test_причина_отказа_видна_в_результате_части(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Причина обязана попасть в отчёт: иначе в сводке «НЕ СДЕЛАНО» без
    объяснения, а человек гадает."""
    worker = FakeWorker(tmp_path)

    def no_access(agent: Agent, task: str) -> None:
        async def run() -> dict[str, Any]:
            agent.steps.append(type("S", (), {
                "tool": None, "model": "a/модель",
                "error": "все ключи провайдера в карантине по лимиту"})())
            return {"ok": False, "steps": 1, "last": "", "tools_used": [],
                    "models_used": ["a/модель"]}

        agent.run = run

    monkeypatch.setattr(Agent, "set_task", no_access)
    _run(worker, tmp_path, _parts(1))
    failed = [e for e in worker.events if e["type"] == "swarm_part_failed"]
    assert failed, worker.events
    assert "карантине" in failed[0]["error"], failed[0]["error"]


def _assembly_worker(tmp_path: Path) -> FakeWorker:
    """Воркер с настоящими методами сборки.

    Методы берутся у `Worker`, а не пишутся здесь: проверка должна ловить
    изменения настоящего кода, иначе она проверяет саму себя.
    """
    from hub.worker import Worker

    worker = FakeWorker(tmp_path)
    worker._run_with_images = Worker._run_with_images.__get__(worker)
    worker._attach_images = lambda agent, images: None
    return worker


def test_финальная_сборка_ограничена_шагами(tmp_path: Path) -> None:
    """Сборка не должна занимать столько места, сколько самая большая часть.

    Замер 06.10.2026 на шести страницах: из 44 запросов на прогон 30 сделали
    части, а 14 — главный агент после них. Время роя определяла не
    параллельная работа, а сборка: её запросы шли последовательно и стоили
    по 15–20 секунд.
    """
    from hub.worker import ASSEMBLY_STEPS, Worker

    worker = _assembly_worker(tmp_path)
    config = _config(tmp_path, steps=20)
    agent = _agent(tmp_path, worker)
    agent.messages = [{"role": "system", "content": "правила"}]

    seen: list[int] = []

    async def run() -> dict[str, Any]:
        # Агент читает лимит в каждом шаге — проверим, что он увидел урезанный.
        seen.append(config.max_steps)
        return {"ok": True, "last": "готово"}

    agent.run = run  # type: ignore[assignment]
    got = asyncio.run(
        Worker._assemble_briefly.__get__(worker)(agent, config, None))

    assert got["last"] == "готово"
    assert seen == [ASSEMBLY_STEPS], seen
    assert config.max_steps == 20, "после сборки бюджет обязан вернуться"


def test_взгляд_не_режет_бюджет_работающих_частей(tmp_path: Path) -> None:
    """Конфиг у главного агента общий со всеми частями роя.

    Промежуточный взгляд уменьшает лимит шагов главного агента, а `Agent.run()`
    читает его в каждом шаге. Если бы менялся общий объект, все живые части в
    этот момент получили бы лимит в два шага и оборвались на середине работы.
    """
    worker = _bench(tmp_path, 6)
    parts = _parts(4)
    config = _config(tmp_path, steps=20)
    run_ = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                    config=config, parts=parts,
                    task={"id": 1, "task": "t"}, task_context="t")

    from hub.swarm_run import PARTIAL_STEPS

    # У части должен быть свой конфиг, и он не должен быть тем же объектом.
    denied = denied_for_all(parts, Path(config.base_dir))
    globs = globs_for_all(parts)
    agent = run_.make_agent(parts[0], run_.build_plan().workers[0], 0,
                            denied, globs)
    assert agent.config is not config
    assert agent.config.max_steps == config.max_steps

    seen: list[int] = []

    async def behaviour() -> dict[str, Any]:
        seen.append(run_.agent.config.max_steps)
        return {"ok": True, "last": "посмотрел"}

    run_.agent.run = behaviour  # type: ignore[assignment]
    plan = run_.build_plan()
    for slot, part in zip(plan.workers, parts):
        slot.taken_by = part.name
    run_.swarm.mark_done(parts[0].name, "готово")

    asyncio.run(run_.partial_round())

    assert seen == [PARTIAL_STEPS], seen
    assert config.max_steps == 20, "бюджет задачи обязан остаться прежним"
    assert agent.config.max_steps == 20, (
        "часть не должна получить урезанный бюджет от промежуточного взгляда")


def test_бюджет_сборки_не_увеличивается(tmp_path: Path) -> None:
    """Потолок не должен поднимать бюджет: у задачи он и так может быть мал."""
    from hub.worker import ASSEMBLY_STEPS, Worker

    worker = _assembly_worker(tmp_path)
    config = _config(tmp_path, steps=2)
    agent = _agent(tmp_path, worker)
    seen: list[int] = []

    async def run() -> dict[str, Any]:
        seen.append(config.max_steps)
        return {"ok": True, "last": ""}

    agent.run = run  # type: ignore[assignment]
    asyncio.run(Worker._assemble_briefly.__get__(worker)(agent, config, None))
    assert seen == [2], f"бюджет задачи урезан — увеличивать нельзя: {seen}"
    assert ASSEMBLY_STEPS > 2, "потолок должен быть выше бюджета в тесте"


def _ready_run(tmp_path: Path, count: int = 4) -> tuple[Any, Any]:
    """Рой с готовыми частями: план собран, части отмечены сделанными."""
    worker = _bench(tmp_path, 8)
    parts = _parts(count)
    run = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                   config=_config(tmp_path, steps=20), parts=parts,
                   task={"id": 1, "task": "t"}, task_context="t")
    run.build_plan()
    for slot, part in zip(run.swarm.plan.workers, parts):
        slot.taken_by = part.name
        run.swarm.mark_done(part.name, "сделал")
        slot.taken_by = ""
    return worker, run


def test_части_делятся_между_проверяющими_поровну() -> None:
    """Ровно: неравная делёжка означает, что один проверяющий сидит вдвое
    дольше, а время роя определяет самый долгий."""
    from hub.swarm_run import _split_evenly

    batches = _split_evenly(list(range(7)), 3)
    assert [len(b) for b in batches] == [3, 2, 2], batches
    assert sorted(x for b in batches for x in b) == list(range(7))


def test_деление_не_оставляет_пустых_групп() -> None:
    """Пустая группа — это проверяющий, которому нечего делать, но запрос он
    всё равно сделает."""
    from hub.swarm_run import _split_evenly

    assert [len(b) for b in _split_evenly([1], 3)] == [1]
    assert _split_evenly([], 3) == []


def test_вердикт_берётся_по_имени_части() -> None:
    """Проверяющий отвечает построчно, и вердикт достаётся своей части, а не
    первой попавшейся строке."""
    from hub.swarm_run import _verdict_for

    parts = _parts(2)
    text = ("проверил\n"
            f"{parts[0].name}: ГОТОВО — файл есть\n"
            f"{parts[1].name}: ПРОБЛЕМА — файл пустой\n")
    assert _verdict_for(text, parts[0]).startswith(f"{parts[0].name}: ГОТОВО")
    assert _verdict_for(text, parts[1]).startswith(f"{parts[1].name}: ПРОБЛЕМА")


def test_вердикт_читается_списком_с_нумерацией() -> None:
    """Модель могла завернуть ответ в список — нумерация и звёздочки не должны
    ломать разбор, если имена на месте."""
    from hub.swarm_run import _verdict_for

    parts = _parts(2)
    text = (f"- **{parts[0].name}**: ГОТОВО\n"
            f"  - {parts[1].name}: ПРОБЛЕМА — нет файла\n")
    assert "ГОТОВО" in _verdict_for(text, parts[0])
    assert "ПРОБЛЕМА" in _verdict_for(text, parts[1])


def test_неизвестный_вердикт_не_становится_готовым() -> None:
    """Ложное «ГОТОВО» хуже отсутствия вердикта: сборщик решит, что часть в
    порядке, и не посмотрит её. Поэтому неизвестное остаётся неизвестным."""
    from hub.swarm_run import _verdict_for

    parts = _parts(1)
    got = _verdict_for("ну вроде нормально", parts[0])
    assert not got.startswith("ГОТОВО"), got
    assert "не проверено" in got, got


def test_пустой_ответ_проверяющего_разбирается() -> None:
    from hub.swarm_run import _verdict_for

    parts = _parts(1)
    assert "не проверено" in _verdict_for("", parts[0])
    assert "не проверено" in _verdict_for("   \n  ", parts[0])


def test_проверка_идёт_несколькими_агентами(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяющих несколько, и у каждого свой аккаунт: иначе они делят один
    лимит и идут по очереди, а весь смысл был в параллельности."""
    worker, run = _ready_run(tmp_path, 6)
    used: list[str] = []
    real_make = SwarmRun.make_checker

    def spy(self: Any, slot: Any) -> Agent:
        used.append(slot.key)
        return real_make(self, slot)

    monkeypatch.setattr(SwarmRun, "make_checker", spy)

    async def fake_run(self: Any) -> dict[str, Any]:
        return {"ok": True, "last": "ок"}

    monkeypatch.setattr(Agent, "run", fake_run)
    verdicts = asyncio.run(run.verify())

    assert len(used) == 3, f"проверяющих должно быть три, а их {len(used)}"
    assert len(set(used)) == len(used), f"аккаунт один на всех: {used}"
    assert len(verdicts) == 6, verdicts


def test_проверяющий_не_имеет_прав_на_запись(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка не имеет права чинить. Иначе проверяющий поправит молча, и в
    отчёте будет «всё хорошо», а правки не будет нигде."""
    worker, run = _ready_run(tmp_path, 4)
    levels: list[Any] = []
    real_make = SwarmRun.make_checker

    def spy(self: Any, slot: Any) -> Agent:
        agent = real_make(self, slot)
        levels.append(agent.config.access)
        return agent

    monkeypatch.setattr(SwarmRun, "make_checker", spy)

    async def fake_run(self: Any) -> dict[str, Any]:
        return {"ok": True, "last": "ок"}

    monkeypatch.setattr(Agent, "run", fake_run)
    asyncio.run(run.verify())

    assert levels, "проверяющие не созданы"
    assert all(level.name == "READ" for level in levels), levels


def test_проверка_пропускается_на_малом_числе_частей(tmp_path: Path) -> None:
    """Одну-две части дешевле посмотреть сборщику: поднимать проверяющих
    дороже, чем проверять."""
    worker, run = _ready_run(tmp_path, 2)
    assert asyncio.run(run.verify()) == {}


def test_проверка_пропускается_без_свободных_аккаунтов(
        tmp_path: Path) -> None:
    """Проверять нечем — все аккаунты в работе. Проверка не должна залезать на
    чужой ключ: это тот же отказ по лимиту, ради которого есть резерв."""
    worker, run = _ready_run(tmp_path, 4)
    for slot in run.swarm.plan.workers:
        slot.taken_by = "занято"
    assert asyncio.run(run.verify()) == {}


def test_упавшая_проверка_не_прячет_часть(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверка сорвалась — часть не считается проверенной. Иначе в сводке будет
    «проверено», а на деле никто ничего не смотрел."""
    worker, run = _ready_run(tmp_path, 4)

    async def boom(self: Any) -> dict[str, Any]:
        raise RuntimeError("провайдер молчит")

    monkeypatch.setattr(Agent, "run", boom)
    verdicts = asyncio.run(run.verify())
    assert verdicts, "вердикты всё равно должны быть"
    for text in verdicts.values():
        assert not text.startswith("ГОТОВО"), text
        assert "проверка не прошла" in text, text


def test_событие_проверки_видно(tmp_path: Path,
                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Человек должен видеть, что проверяли и сколько нашли проблем."""
    worker, run = _ready_run(tmp_path, 4)

    async def with_problem(self: Any) -> dict[str, Any]:
        return {"ok": True, "last": "ПРОБЛЕМА — файла нет"}

    monkeypatch.setattr(Agent, "run", with_problem)
    asyncio.run(run.verify())
    note = next(e for e in worker.events if e["type"] == "swarm_verified")
    assert note["checked"] == 4, note
    assert note["problems"], note


def test_сборщик_видит_проблемы_проверяющих(tmp_path: Path) -> None:
    """Вердикт обязан дойти до сборщика: иначе проверка работает вхолостую и
    ровно та треть времени, которую она должна была сэкономить, уходит обратно
    на перечитывание."""
    from hub.worker import Worker

    worker = _assembly_worker(tmp_path)
    worker._assemble_briefly = Worker._assemble_briefly.__get__(worker)
    seen: list[str] = []
    agent = _agent(tmp_path, worker)

    async def behaviour() -> dict[str, Any]:
        seen.append(" ".join(str(m.get("content")) for m in agent.messages))
        return {"ok": True, "last": "ответ"}

    agent.run = behaviour  # type: ignore[assignment]

    got = {"ok": True, "tools": ["write_file"], "summary": "сверстал",
           "error": "", "steps": 3}
    fake = type("Run", (), {
        "swarm": type("S", (), {"handoffs": {}})(),
        "results": {"часть 1": got},
        "verdicts": {"часть 1": "часть 1: ПРОБЛЕМА — файл пустой"},
    })()
    asyncio.run(Worker._assemble.__get__(worker)(
        agent, _config(tmp_path, steps=20), "задача", fake, None))

    assert seen, "сборщик не запустился"
    assert "ПРОБЛЕМА" in seen[0], seen[0][:300]
    assert "проверяющие" in seen[0].lower(), seen[0][:300]


def test_вердикт_опознаётся_с_именем_части() -> None:
    """Ошибка была на этом месте: вердикт приходит с именем части впереди, а
    разбор смотрел на начало строки. Любая проблема объявлялась «проверка не
    удалась» — сборщик получал неверную причину и шёл чинить не то."""
    from hub.swarm_run import _mark_of

    assert _mark_of("часть 1: ПРОБЛЕМА — файл пустой") == "ПРОБЛЕМА"
    assert _mark_of("часть 1: ГОТОВО — всё на месте") == "ГОТОВО"
    assert _mark_of("ПРОБЛЕМА") == "ПРОБЛЕМА"
    assert _mark_of("не проверено: пустой ответ") == ""
    assert _mark_of("") == ""


def test_сборщик_получает_верную_причину(tmp_path: Path) -> None:
    """Проблема должна быть названа проблемой, а не «проверка не удалась»."""
    from hub.worker import Worker

    worker = _assembly_worker(tmp_path)
    worker._assemble_briefly = Worker._assemble_briefly.__get__(worker)
    seen: list[str] = []
    agent = _agent(tmp_path, worker)

    async def behaviour() -> dict[str, Any]:
        seen.append(" ".join(str(m.get("content")) for m in agent.messages))
        return {"ok": True, "last": "ответ"}

    agent.run = behaviour  # type: ignore[assignment]
    got = {"ok": True, "tools": ["write_file"], "summary": "сверстал",
           "error": "", "steps": 3}
    fake = type("Run", (), {
        "swarm": type("S", (), {"handoffs": {}})(),
        "results": {"часть 1": got},
        "verdicts": {"часть 1": "часть 1: ПРОБЛЕМА — файл пустой"},
    })()
    asyncio.run(Worker._assemble.__get__(worker)(
        agent, _config(tmp_path, steps=20), "задача", fake, None))

    assert "нашли проблемы" in seen[0].lower(), seen[0][:300]
    assert "проверить не удалось" not in seen[0].lower(), seen[0][:300]


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


def _bench(tmp_path: Path, keys: int = 6) -> FakeWorker:
    """Воркер на нужное число аккаунтов: слотов столько, сколько частей,
    иначе часть остаётся без слота и до промежуточного взгляда не доживает."""
    worker = FakeWorker(tmp_path)
    worker.keyring = _KeyRing(keys)
    worker.gateways = [{"id": "a", "key_count": keys, "rpm_per_account": 40}]
    return worker


def test_главный_агент_получает_промежуточный_результат(
        tmp_path: Path, model_stub) -> None:
    """Главный агент не простаивает, пока части идут."""
    worker = _bench(tmp_path, 6)
    parts = _parts(4)
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


def test_перед_финальной_сборкой_взгляд_не_делается(tmp_path: Path,
                                                 model_stub) -> None:
    """Когда почти всё готово, взгляд не нужен: финальная сборка получит всё
    и через минуту. Взгляд сейчас только тратит запросы — замер 06.10.2026
    показал, что на коротких частях эти обходы дороже работы."""
    worker = FakeWorker(tmp_path)
    parts = _parts(3)
    run_ = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                    config=_config(tmp_path), parts=parts,
                    task={"id": 1, "task": "t"}, task_context="t")
    plan = run_.build_plan()
    for slot, part in zip(plan.workers, parts):
        slot.taken_by = part.name
    for part in parts[:-1]:
        run_.swarm.mark_done(part.name, "готово")

    ran: list[str] = []

    async def behaviour() -> dict[str, Any]:
        ran.append("да")
        return {"ok": True, "last": ""}

    run_.agent.run = behaviour  # type: ignore[assignment]
    asyncio.run(run_.partial_round())
    assert ran == [], "перед финальной сборкой промежуточный заход лишний"


def test_промежуточный_взгляд_ограничен_шагами(tmp_path: Path,
                                            model_stub) -> None:
    """Взгляд между делом не должен разойтись на полноценный заход по задаче."""
    worker = _bench(tmp_path, 6)
    parts = _parts(4)
    config = _config(tmp_path, steps=3)
    run_ = SwarmRun(worker=worker, agent=_agent(tmp_path, worker),
                    config=config, parts=parts,
                    task={"id": 1, "task": "t"}, task_context="t")
    plan = run_.build_plan()
    for slot, part in zip(plan.workers, parts):
        slot.taken_by = part.name
    run_.swarm.mark_done(parts[0].name, "готово")

    from hub.swarm_run import PARTIAL_STEPS

    async def behaviour() -> dict[str, Any]:
        # Агент читает лимит в каждом шаге — проверим, что он увидел урезанный.
        return {"ok": True, "last": str(run_.agent.config.max_steps)}

    run_.agent.run = behaviour  # type: ignore[assignment]
    note = asyncio.run(run_.partial_round())
    assert note == str(PARTIAL_STEPS), note
    assert run_.agent.config.max_steps == 3, "после взгляда бюджет обязан вернуться"
    assert run_.config.max_steps == 3, (
        "конфиг задачи не должен меняться: он общий с частями роя")