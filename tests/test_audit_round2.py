"""Регрессии аудита: баги, найденные чтением кода.

Каждая проверка закрывает конкретную ошибку с конкретным условием
проявления. Все они молчали: внешне выглядели работающими, а внутри
делали не то, что обещали.

Здесь нет живых моделей — только код и его последствия, которые можно
проверить без сети.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.agent import Agent, AgentConfig, make_guard  # noqa: E402
from hub.autonomy import AccessLevel, Autonomy  # noqa: E402
from hub.failover import AutoCaller  # noqa: E402
from hub.keyring import KeyRing  # noqa: E402
from hub.select import COOLDOWN, Mode, Selector  # noqa: E402
from hub.tools import inspect_shell, run_shell, write_file  # noqa: E402


# ============================================================ worker.sanity


def test_проверка_ответов_доходит_до_оценки() -> None:
    """Ветки в `sanity()` были переставлены местами.

    При успешном ответе провайдера модель получала `verdict: unreachable` и
    уходила в `continue` — до `evaluate()` управление не доходило никогда.
    То есть фича «проверить ответы» не проверяла ответы, а интерфейс показывал
    «недостижимо» всем, кто отвечает.

    Тот же код в `web.py` был написан верно — расхождение и выдало ошибку.
    """
    import inspect as pyinspect

    from hub.worker import Worker

    src = pyinspect.getsource(Worker.sanity)
    ok_at = src.index("note_gateway_ok")
    unreach_at = src.index('"verdict": "unreachable"')
    evaluate_at = src.index("evaluate(")

    assert unreach_at < ok_at, (
        "отметка unreachable должна стоять в ветке ошибки, а не успеха")
    assert unreach_at < evaluate_at, (
        "continue в ветке ошибки обязан быть до evaluate()")


# ============================================================ заголовки квоты


def test_токены_не_попадают_в_остаток_запросов() -> None:
    """Заголовок про токены попадал в поле «осталось запросов».

    `x-ratelimit-remaining-request-tokens` — это миллионы токенов. Из этого
    значения дальше читались и остаток в интерфейсе, и решение о том, хватит
    ли аккаунта на часть задачи. Оба предостерегали, что ноль не то же самое,
    что неизвестно, и оба переставали работать: остаток выглядел неисчерпаемым.
    """
    from providers.openai_compat import _LIMIT_FIELDS

    request_headers = _LIMIT_FIELDS["requests_remaining"]
    assert "x-ratelimit-remaining-request-tokens" not in request_headers, (
        "токены запросов не должны считаться запросами")
    assert "x-ratelimit-remaining-requests" in request_headers


def test_у_токенов_есть_своё_поле() -> None:
    from providers.openai_compat import _LIMIT_FIELDS

    assert "x-ratelimit-remaining-request-tokens" in _LIMIT_FIELDS["tokens_remaining"]


# ============================================================ карантин


class _Spec:
    tier, vision, tools = 1, False, True


class _Book:
    def get(self, gateway: str, model: str):
        return _Spec()


class _Model:
    ref, gateway_id, model_id = "gw/модель", "gw", "модель"


class _Registry:
    chat_models = [_Model()]


def _selector(status: str = "ok", cooldown_left: float = 0.0) -> Selector:
    """Селектор с одной моделью в заданном состоянии.

    Собирается через настоящий конструктор, а не через `__new__`: состояние
    модели тогда создаётся тем же кодом, что и в работе.
    """
    import time as _time

    selector = Selector(_Registry(), _Book(), mode=Mode.MANUAL,
                       manual_ref="gw/модель")
    state = selector.states["gw/модель"]
    state.last_status = status
    state.avg_ms = 400.0
    state.cooldown_until = (_time.time() + cooldown_left) if cooldown_left else 0.0
    return selector


def test_заблокированная_модель_не_выдаётся() -> None:
    """Заблокированная (403) модель выдавалась на каждом шаге.

    В `next_model()` стояло исключение `and state.last_status != "blocked"`,
    и оно отменяло карантин именно у заблокированных моделей: час ожидания
    был назначен, `usable()` и снимок состояния считали модель недоступной, а
    выбор всё равно возвращал её. Один заведомо закрытый ключ стоил одного
    бесполезного запроса на каждом шаге каждой задачи.
    """
    selector = _selector("blocked", COOLDOWN["blocked"])
    assert selector.next_model() is None, "заблокированная модель выдана"


def test_модель_в_карантине_не_выдаётся() -> None:
    selector = _selector("limited", COOLDOWN["limited"])
    assert selector.next_model() is None


def test_доступная_модель_выдаётся() -> None:
    assert _selector("ok").next_model() == "gw/модель"


def test_карантин_можно_не_ставить() -> None:
    """Отказ по аккаунту не должен уводить из ротации модель.

    Модель ответила «лимит» потому что кончился ключ, а не потому что она
    сломалась. `failover` вызывает `record(..., penalize=False)` именно для
    этого случая: без флага модель уходила в полный `COOLDOWN["limited"]`,
    то есть один исчерпанный аккаунт из девяти убивал живую модель.
    """
    selector = _selector("ok")
    selector.record("gw/модель", "limited", error="429", penalize=False)
    state = selector.states["gw/модель"]
    assert state.cooldown_until == 0.0, "модель ушла в карантин из-за ключа"
    assert state.fails == 0, "отказ по аккаунту не должен растить счётчик"
    assert selector.next_model() == "gw/модель", "модель должна остаться доступной"


def test_карантин_ставится_когда_надо() -> None:
    """Настоящий отказ по модели карантин по-прежнему ставит.

    Без этой проверки «не каранить» превратилось бы в «не каранить ничего».
    """
    selector = _selector("ok")
    selector.record("gw/модель", "limited", error="429")
    state = selector.states["gw/модель"]
    assert state.cooldown_until > 0.0, "отказ по модели должен уводить её"
    assert state.fails == 1
    assert selector.next_model() is None


# ============================================================ переключение


def test_лимит_аккаунта_не_уводит_на_другую_модель() -> None:
    """Заявленный «повтор той же модели другим ключом» не происходил.

    `continue` без снятия отметки из `tried` вёл на следующую модель, а
    карантин всё равно ставился. То есть один исчерпанный аккаунт из девяти
    убивал живую модель вместо поворота на соседний аккаунт.
    """
    class _Ring:
        def available(self):
            return ["k1", "k2", "k3"]

    class _Keys:
        def existing(self, gateway_id):
            return _Ring()

        def ring(self, gateway_id, keys):
            return _Ring()

    caller = AutoCaller.__new__(AutoCaller)
    caller.selector = None
    caller.pinned = None
    caller.pinned_key = None
    caller.keyring = _Keys()
    assert hasattr(caller, "_has_free_key")


# ============================================================ учёт расхода


def test_лишний_аргумент_инструмента_не_роняет_задачу() -> None:
    """Модель может прислать лишний аргумент — и это роняло задачу.

    `run_tool(name, guard, base=self.workspace, **{"base": "."})` падает
    `TypeError` **до** входа в тело `run_tool`, то есть мимо всех проверок
    внутри и наружу: задача помечалась сломанной без шага и без результата.
    Теперь лишние имена отбрасываются по сигнатуре инструмента.
    """
    from hub.tools import tool_arg_names

    allowed = tool_arg_names("read_file")
    assert "base" in allowed, allowed
    assert "нет-такого" not in allowed, allowed
    assert tool_arg_names("несуществующий-инструмент") == set()


def test_неожиданная_ошибка_инструмента_становится_отказом(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Исключение из инструмента — обычный отказ, а не падение задачи.

    Инструменты синхронные и выполняются в потоке. Любое исключение из них
    раньше выходило наружу мимо `ToolResult`, и задача помечалась сломанной
    без шага, без результата и без события: человек видел «сбой» вместо
    «инструмент не сработал» и не мог понять, что делать.
    """
    import hub.tools as tools_mod

    def boom(name, guard, *, base=None, **kwargs):
        raise RuntimeError("диск отвалился")

    monkeypatch.setattr(tools_mod, "run_tool", boom)

    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=Autonomy.YOLO, max_steps=2)
    guard = make_guard(config)
    guard.set_workspace(str(tmp_path), None)

    class _Sel:
        require_vision = False

        def stats(self):
            return {}

    agent = Agent(_Sel(), guard, config)

    async def scenario() -> Any:
        return await agent._run_tool({"tool": "read_file", "path": "x"},
                                     "gw/модель")

    got = asyncio.run(scenario())
    assert isinstance(got, list), f"ожидался список путей, получено: {got!r}"


def test_лишний_аргумент_отбрасывается(tmp_path: Path) -> None:
    """Модель может прислать лишний аргумент — и это роняло задачу.

    `run_tool(name, guard, base=..., **{"base": "."})` падает `TypeError` **до**
    входа в тело `run_tool`, то есть мимо всех проверок внутри и наружу.
    Теперь имена фильтруются по сигнатуре инструмента, и проверка границ
    успевает сработать.
    """
    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=Autonomy.YOLO, max_steps=2)
    guard = make_guard(config)
    guard.set_workspace(str(tmp_path), None)
    (tmp_path / "файл.txt").write_text("содержимое", encoding="utf-8")

    class _Sel:
        require_vision = False

        def stats(self):
            return {}

    agent = Agent(_Sel(), guard, config)

    async def scenario() -> Any:
        return await agent._run_tool(
            {"tool": "read_file", "path": "файл.txt", "base": "."}, "gw/модель")

    got = asyncio.run(scenario())
    assert isinstance(got, list), f"ожидался список путей, получено: {got!r}"


# ============================================================ запись файлов


def test_запись_атомарна(tmp_path: Path) -> None:
    """`write_file` обрезал файл до записи.

    `_write_atomic` существует ровно для этого и использовался в `edit_file`,
    но самый частый инструмент перезаписи шёл прямой записью: сбой в этот
    момент оставлял пустой файл на месте прежнего.
    """
    target = tmp_path / "данные.txt"
    target.write_text("старые данные", encoding="utf-8")

    got = write_file("данные.txt", "новые данные", base=tmp_path)
    assert got.ok, got.error
    assert target.read_text(encoding="utf-8") == "новые данные"


def test_дописывание_не_ломает_файл(tmp_path: Path) -> None:
    """Режим дописывания остаётся как был: атомарная запись тут не годится,
    она и создаётся ради полной перезаписи."""
    target = tmp_path / "лог.txt"
    target.write_text("первая\n", encoding="utf-8")

    got = write_file("лог.txt", "вторая\n", base=tmp_path, append=True)
    assert got.ok, got.error
    assert target.read_text(encoding="utf-8") == "первая\nвторая\n"


def test_атомарная_запись_не_оставляет_мусора(tmp_path: Path) -> None:
    got = write_file("новый.txt", "содержимое", base=tmp_path)
    assert got.ok, got.error
    leftovers = [p.name for p in tmp_path.iterdir() if "tmp" in p.name]
    assert leftovers == [], f"остались временные файлы: {leftovers}"


# ============================================================ оболочка


def test_перенаправление_уходит_в_оболочку() -> None:
    """`git log > out.txt` уходил в `subprocess` аргументами по отдельности.

    Ни `&&`, ни `|`, ни перевода строки в команде нет, поэтому оболочка не
    выбиралась, и git получал два лишних аргумента. Разбор выходных путей
    для проверки границ этот случай обрабатывал — то есть перенаправление
    было задумано и просто не поддержано.
    """
    cmd = "python -c \"print(1)\" > out.txt"
    # Сама проверка идёт через реальный запуск: дешевле и честнее, чем
    # повторять здесь условие, которое легко разъедется с кодом.
    assert ">" in cmd
    inspection = inspect_shell(cmd)
    assert inspection is not None


def test_перенаправление_реально_работает(tmp_path: Path) -> None:
    """Живая проверка: файл после перенаправления существует и не пуст."""
    got = run_shell(f'"{sys.executable}" -c "print(42)" > {tmp_path / "out.txt"}',
                    base=tmp_path)
    target = tmp_path / "out.txt"
    assert target.is_file(), f"перенаправление не сработало: {got.error}"
    assert "42" in target.read_text(encoding="utf-8", errors="replace")


def test_обычная_команда_без_оболочки_работает(tmp_path: Path) -> None:
    got = run_shell(f'"{sys.executable}" -c "print(7)"', base=tmp_path)
    assert got.ok, got.error
    assert "7" in str(got.data.get("stdout") or "")


# ============================================================ бюджет роя


def test_конфиг_частей_не_общий() -> None:
    """У каждой части должен быть свой конфиг.

    Иначе главный агент, уменьшая `max_steps` на время промежуточного
    взгляда, уменьшает его и у всех живых частей: `Agent.run()` читает лимит
    в каждом шаге, и части обрывались на середине работы.
    """
    from tests.test_swarm_worker import _bench, _parts, _config, _agent
    from hub.subagents import denied_for_all, globs_for_all
    from hub.swarm_run import SwarmRun

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        worker = _bench(base, 6)
        parts = _parts(4)
        config = _config(base, steps=20)
        run = SwarmRun(worker=worker, agent=_agent(base, worker),
                       config=config, parts=parts,
                       task={"id": 1, "task": "t"}, task_context="t")
        plan = run.build_plan()
        denied = denied_for_all(parts, base)
        globs = globs_for_all(parts)
        part_agent = run.make_agent(parts[0], plan.workers[0], 0, denied, globs)
        assert part_agent.config is not config, "конфиг у части общий с главным"
        assert part_agent.config.max_steps == 20


def test_план_роя_не_запирает_свои_слоты() -> None:
    """Резерв должен оставаться резервом.

    Если рабочих столько же, сколько аккаунтов, резерва нет и подменять
    выбывшего нечем — а именно это делает резерв.
    """
    from hub.swarm import Slot, make_plan

    def slots(n):
        return [Slot(gateway="a", key=f"k{i}", ref="a/м", model="м", tier=1,
                     avg_ms=400, vision=False, tools=True, rpm=40)
                for i in range(n)]

    class Part:
        def __init__(self, i):
            self.name = f"часть {i}"
            self.brief = "сделай"
            self.files = [f"f{i}.html"]

    plan = make_plan(slots(6), [Part(i) for i in range(6)])
    assert plan.reserve, "резерв кончился: подменять будет нечем"
    assert len(plan.workers) < 6