"""Регрессии аудита: подтверждения, карантины, рой и интерфейс.

Каждая проверка закрывает ошибку, найденную чтением кода. Часть из них
молчала годами: снаружи всё выглядело работающим.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.agent import Agent, AgentConfig, make_guard  # noqa: E402
from hub.autonomy import AccessLevel, Autonomy  # noqa: E402
from hub.keyring import KeyRing  # noqa: E402
from hub.tools import run_tool  # noqa: E402


# ====================================================== подтверждения


class _Sel:
    require_vision = False

    def stats(self) -> dict:
        return {}


def _agent(tmp_path: Path, autonomy: Autonomy) -> Agent:
    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=autonomy)
    guard = make_guard(config)
    guard.set_workspace(str(tmp_path), None)
    return Agent(_Sel(), guard, config)


def _calls(tmp_path: Path, autonomy: Autonomy, call: dict) -> tuple[bool, bool]:
    """(задался вопрос, инструмент выполнен) для одного вызова."""
    import hub.agent as agent_mod

    ran: list[str] = []

    def stub(name, guard, *, base=None, **kwargs):
        ran.append(name)
        return agent_mod.ToolResult(True, data={})

    original = agent_mod.run_tool
    agent_mod.run_tool = stub
    try:
        agent = _agent(tmp_path, autonomy)

        async def scenario() -> bool:
            await agent._run_tool(call, "gw/м")
            return agent.pending_question is not None

        asked = asyncio.run(scenario())
        return asked, bool(ran)
    finally:
        agent_mod.run_tool = original


def test_опасная_команда_спрашивает(tmp_path: Path) -> None:
    """Список опасных команд разбирался и попадал в `meta` — и на этом всё.

    `rm -rf`, `format`, `git reset --hard` выполнялись при полном доступе без
    вопроса. Список, который ничего не проверяет, — украшение.
    """
    asked, ran = _calls(tmp_path, Autonomy.NORMAL,
                        {"tool": "run_shell", "args": {"command": "rm -rf /"}})
    assert asked is True, "опасная команда выполнена без вопроса"
    assert ran is False, "инструмент выполнился, хотя должен был спросить"


def test_обычная_команда_не_спрашивает(tmp_path: Path) -> None:
    asked, ran = _calls(tmp_path, Autonomy.NORMAL,
                        {"tool": "run_shell", "args": {"command": "git status"}})
    assert asked is False, "обычная команда не должна требовать подтверждения"
    assert ran is True


def test_обычный_режим_спрашивает_перед_правкой(tmp_path: Path) -> None:
    """`Autonomy.NORMAL` обещал подтверждение и не делал ничего.

    `needs_confirmation` вызывался только из тестов, то есть режимы
    `normal` и `strict` выглядели включёнными и были пустыми.
    """
    asked, ran = _calls(tmp_path, Autonomy.NORMAL,
                        {"tool": "write_file",
                         "args": {"path": "a.txt", "content": "x"}})
    assert asked is True, "запись без подтверждения в обычном режиме"
    assert ran is False


def test_строгий_режим_спрашивает_даже_на_чтение(tmp_path: Path) -> None:
    asked, _ = _calls(tmp_path, Autonomy.STRICT,
                      {"tool": "read_file", "args": {"path": "a.txt"}})
    assert asked is True


def test_делай_сам_не_спрашивает_ни_о_чём(tmp_path: Path) -> None:
    for call in ({"tool": "run_shell",
                     "args": {"command": "rm -rf /"}},
                 {"tool": "write_file",
                  "args": {"path": "a.txt", "content": "x"}},
                 {"tool": "read_file", "args": {"path": "a.txt"}}):
        asked, ran = _calls(tmp_path, Autonomy.YOLO, call)
        assert asked is False, f"YOLO спросил: {call}"
        assert ran is True, f"YOLO не выполнил: {call}"


def test_подтверждённое_не_спрашивает_повторно(tmp_path: Path) -> None:
    """Подтверждение запоминается, иначе режим превращается в диалог на
    каждый шаг."""
    agent = _agent(tmp_path, Autonomy.NORMAL)
    assert agent.guard.needs_confirmation("write", "a.txt") is True
    agent.guard.confirm("write", "a.txt")
    assert agent.guard.needs_confirmation("write", "a.txt") is False


def test_разрешение_переживает_перезапуск_задачи(tmp_path: Path) -> None:
    """Ответ на запрос приходит отдельным запросом и продолжает задачу **с
    чекпоинта**.

    Значит, ждущий запрос и уже вынесенные решения обязаны пережить
    перезапуск. Без этого человек жал «Разрешить», задача перезапускалась,
    разрешение терялось, и агент задавал тот же вопрос снова — до конца шагов.
    """
    import json

    call = {"tool": "write_file", "args": {"path": "a.txt", "content": "x"}}

    async def спросить() -> dict[str, Any]:
        agent = _agent(tmp_path, Autonomy.NORMAL)
        agent.messages = [{"role": "system", "content": "с"},
                          {"role": "user", "content": "у"}]
        ran: list[str] = []
        import hub.agent as agent_mod

        original = agent_mod.run_tool
        agent_mod.run_tool = lambda name, guard, *, base=None, **kw: (
            ran.append(name) or agent_mod.ToolResult(True, data={}))
        try:
            await agent._run_tool(call, "gw/м")
            assert agent.pending_question is not None
            agent.save_checkpoint()
        finally:
            agent_mod.run_tool = original
        # Чекпоинт идёт в хранилище задач, то есть через JSON.
        return json.loads(json.dumps(agent.checkpoint, ensure_ascii=False))

    checkpoint = asyncio.run(спросить())

    async def ответить() -> tuple[bool, bool]:
        agent = _agent(tmp_path, Autonomy.NORMAL)
        ran: list[str] = []
        import hub.agent as agent_mod

        original = agent_mod.run_tool
        agent_mod.run_tool = lambda name, guard, *, base=None, **kw: (
            ran.append(name) or agent_mod.ToolResult(True, data={}))
        try:
            restored = agent.restore_checkpoint(checkpoint)
            assert restored is True
            await agent.grant_permission("a.txt")
            ran.clear()
            await agent._run_tool(call, "gw/м")
            return agent.pending_question is None, bool(ran)
        finally:
            agent_mod.run_tool = original

    без_повтора, выполнил = asyncio.run(ответить())
    assert без_повтора is True, "вопрос повторился после перезапуска"
    assert выполнил is True, "после разрешения инструмент не выполнился"


def test_отказ_тоже_переживает_перезапуск(tmp_path: Path) -> None:
    """Отказ, потерянный при перезапуске, возвращал вопрос по кругу."""
    import json

    call = {"tool": "write_file", "args": {"path": "b.txt", "content": "x"}}

    async def спросить() -> dict[str, Any]:
        agent = _agent(tmp_path, Autonomy.NORMAL)
        agent.messages = [{"role": "system", "content": "с"},
                          {"role": "user", "content": "у"}]
        import hub.agent as agent_mod

        original = agent_mod.run_tool
        agent_mod.run_tool = lambda name, guard, *, base=None, **kw: (
            agent_mod.ToolResult(True, data={}))
        try:
            await agent._run_tool(call, "gw/м")
            agent.save_checkpoint()
        finally:
            agent_mod.run_tool = original
        return json.loads(json.dumps(agent.checkpoint, ensure_ascii=False))

    checkpoint = asyncio.run(спросить())

    async def ответить() -> tuple[bool, bool]:
        agent = _agent(tmp_path, Autonomy.NORMAL)
        ran: list[str] = []
        import hub.agent as agent_mod

        original = agent_mod.run_tool
        agent_mod.run_tool = lambda name, guard, *, base=None, **kw: (
            ran.append(name) or agent_mod.ToolResult(True, data={}))
        try:
            agent.restore_checkpoint(checkpoint)
            await agent.deny_permission("b.txt")
            ran.clear()
            await agent._run_tool(call, "gw/м")
            return agent.pending_question is None, bool(ran)
        finally:
            agent_mod.run_tool = original

    без_вопроса, не_выполнен = asyncio.run(ответить())
    assert без_вопроса is True, "после отказа вопрос вернулся"
    assert не_выполнен is False, "запрещённый инструмент выполнился"


def test_разрешение_и_отказ_помнятся_в_самом_агенте(tmp_path: Path) -> None:
    """Ответ дошёл до агента — и работа продолжается без новых вопросов."""
    async def сценарий() -> tuple[bool, bool]:
        import hub.agent as agent_mod

        ran: list[str] = []
        original = agent_mod.run_tool
        agent_mod.run_tool = lambda name, guard, *, base=None, **kw: (
            ran.append(name) or agent_mod.ToolResult(True, data={}))
        try:
            call = {"tool": "write_file", "args": {"path": "a.txt",
                                                  "content": "x"}}
            a = _agent(tmp_path, Autonomy.NORMAL)
            await a._run_tool(call, "gw/м")
            await a.grant_permission("a.txt")
            ran.clear()
            await a._run_tool(call, "gw/м")
            без_повтора = a.pending_question is None

            b = _agent(tmp_path, Autonomy.NORMAL)
            other = {"tool": "write_file", "args": {"path": "b.txt",
                                                    "content": "x"}}
            await b._run_tool(other, "gw/м")
            await b.deny_permission("b.txt")
            ran.clear()
            await b._run_tool(other, "gw/м")
            return без_повтора, bool(ran)
        finally:
            agent_mod.run_tool = original

    без_повтора, не_выполнен = asyncio.run(сценарий())
    assert без_повтора is True, "после «Разрешить» вопрос повторился"
    assert не_выполнен is False, "после «Отклонить» инструмент выполнился"


def test_часть_роя_не_спрашивает(tmp_path: Path) -> None:
    """Часть роя не может получить ответ: `SwarmRun` ждёт части через
    `gather`, а вопрос задачи не закрывает вопрос части. Рой встал бы на
    первой записи. Разрешение на работу части — утверждённый план."""
    import hub.agent as agent_mod

    ran: list[str] = []
    original = agent_mod.run_tool
    agent_mod.run_tool = lambda name, guard, *, base=None, **kw: (
        ran.append(name) or agent_mod.ToolResult(True, data={}))
    try:
        agent = _agent(tmp_path, Autonomy.NORMAL)
        agent.part = "часть 1"

        async def сценарий() -> bool:
            await agent._run_tool(
                {"tool": "write_file", "args": {"path": "a.txt",
                                               "content": "x"}}, "gw/м")
            return agent.pending_question is None

        не_спросил = asyncio.run(сценарий())
    finally:
        agent_mod.run_tool = original
    assert не_спросил is True
    assert bool(ran) is True


def test_стенд_не_спрашивает() -> None:
    """Стенд автоматический: ответа ждать некому, и агент останавливался
    намертво.

    Раньше это не проявлялось только потому, что режим `NORMAL` не делал
    ровно ничего. Стоило включить подтверждение по-настоящему — и каждый
    замер на стенде зависал на первой записи.
    """
    runner = (ROOT / "bench" / "runner.py").read_text(encoding="utf-8")
    assert "autonomy=Autonomy.YOLO" in runner, (
        "стенд запускает агента с подтверждениями и зависает")


# ====================================================== кольцо ключей


def test_свой_расход_уменьшает_известный_остаток() -> None:
    """Остаток из заголовков перестаёт быть вечным.

    Раньше `note_spent` писал только своё скользящее окно, а остаток в
    `quota` не трогал: провайдер, присылающий остаток не на каждый ответ,
    давал «48 осталось» навсегда, и части выдавались на несуществующую квоту.
    """
    ring = KeyRing(["k1"])
    ring.note_quota("k1", {"requests_remaining": 10})
    assert ring.quota_of("k1").get("requests_remaining") == 10
    ring.note_spent("k1")
    assert ring.quota_of("k1").get("requests_remaining") == 9
    ring.note_spent("k1")
    assert ring.quota_of("k1").get("requests_remaining") == 8


def test_слова_в_ошибке_не_убивают_аккаунт_на_неделю() -> None:
    """Подстрока `invalid` в тексте 400/404/500 отправляла рабочий аккаунт в
    семидневный карантин с причиной «401»."""
    ring = KeyRing(["k1"])
    ring.note_error("k1", "400 invalid_request_error: max_tokens too large")
    assert ring.is_blocked("k1") is False, (
        "рабочий аккаунт выбит навсегда из-за слова в тексте ошибки")
    ring.note_error("k2", "401 Unauthorized")
    assert ring.is_blocked("k2") is True


def test_все_ключи_в_карантине_не_выдаются() -> None:
    """Регистр возвращал «лучшего из худших», и каждый хоп тратил запрос на
    заведомо выбитый ключ — то есть ровно то, ради чего карантин и нужен.

    Теперь возвращается `None`, и вызывающий пишет «все ключи в карантине».
    """
    from hub.keyring import KeyRegistry

    registry = KeyRegistry()
    gateway = {"id": "gw", "api_keys": ["k1", "k2"]}
    ring = registry.ring("gw", gateway["api_keys"])
    ring.penalize("k1", seconds=3600, why="429")
    ring.penalize("k2", seconds=3600, why="429")
    assert registry.next_key(gateway) is None


def test_свободный_ключ_выдаётся() -> None:
    from hub.keyring import KeyRegistry

    registry = KeyRegistry()
    gateway = {"id": "gw", "api_keys": ["k1", "k2"]}
    ring = registry.ring("gw", gateway["api_keys"])
    ring.penalize("k1", seconds=3600, why="429")
    assert registry.next_key(gateway) in ("k2", "k1")


# ====================================================== рой


def test_аккаунты_с_одинаковым_хвостом_не_делят_ведро() -> None:
    """Два ключа с одинаковыми последними восемью символами делили одно ведро
    ограничителя и удваивали темп друг друга."""
    from hub.swarm import slot_account

    assert slot_account("gw", "abcdefghZZ") != slot_account("gw", "12345678ZZ")
    assert slot_account("gw", "abcdefghZZ") != slot_account("другая", "abcdefghZZ")


def test_отпечаток_устойчив_к_перезапуску() -> None:
    """Иначе накопленный расход обнулялся бы при каждом пуске программы."""
    from hub.swarm import slot_account

    assert slot_account("gw", "sk-or-v1-секрет") == slot_account(
        "gw", "sk-or-v1-секрет")


def test_часть_без_аккаунта_попадает_в_отчёт() -> None:
    """Такая часть просто не стартовала и исчезала из отчёта: задача
    «разбита на 10 частей, сделано 4» выглядела как «разбита неудачно»."""
    from hub.swarm import Slot, Swarm

    class _Reg:
        def ring(self, gateway_id, keys):
            return None

    slot = Slot(gateway="gw", key="k1", ref="gw/м", model="м", tier=1,
                avg_ms=400, vision=False, tools=True, rpm=40)
    plan = type("P", (), {"workers": [], "reserve": [], "unassigned": []})()
    swarm = Swarm(plan=plan, pacer=None)
    assert swarm.pending() == []


def test_чужой_файл_не_считается_сделанной_работой() -> None:
    """Воркспейс переиспользуется: файл от прошлой задачи засчитывался
    провалившейся части, и она объявлялась выполненной с пустым отчётом."""
    import os
    import tempfile

    from hub.swarm_run import files_ready

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        page = base / "page1.html"

        class Part:
            name = "часть"
            brief = "сделай"
            files = ["page1.html"]

        # Файл от прошлой задачи: время изменения у него — час назад.
        # Просто `write_text` не годится: он ставит «сейчас», и такой файл
        # свежим и **должен** считаться — проверка прошла бы не по той
        # причине, по которой написана.
        page.write_text("старое", encoding="utf-8")
        old_mtime = time.time() - 3600
        os.utime(page, (old_mtime, old_mtime))

        assert files_ready(Part(), base, since=time.time()) == [], (
            "файл от прошлой задачи засчитан как работа этой части")
        assert files_ready(Part(), base, since=old_mtime) == ["page1.html"]

        # Свежий файл — работа этой части.
        page.write_text("новое", encoding="utf-8")
        assert files_ready(Part(), base, since=old_mtime) == ["page1.html"]


def test_после_подмены_часть_остаётся_в_работе() -> None:
    """`pending()` смотрел только на рабочие слоты, и после подмены часть
    выпадала из «ещё в работе» — промежуточный взгляд показывал не всё."""
    from hub.swarm import Plan, Slot, Swarm

    def slot(i: int, taken: str = "") -> Slot:
        return Slot(gateway="gw", key=f"k{i}", ref="gw/м", model="м", tier=1,
                    avg_ms=400, vision=False, tools=True, rpm=40,
                    taken_by=taken)

    swarm = Swarm(plan=Plan(workers=[slot(0, "часть 1")], reserve=[slot(1)]),
                  pacer=None)
    assert swarm.pending() == ["часть 1"]
    swarm.handoff("часть 1", "429")
    assert swarm.pending() == ["часть 1"], "после подмены часть пропала"


# ====================================================== разведка


def test_редирект_на_внутренний_адрес_запрещён() -> None:
    """`check_url` запрещал читать внутреннюю сеть, и это обходилось одним
    редиректом: публичный сайт отвечает 302 на `127.0.0.1`, httpx следует
    за ним молча."""
    import inspect

    from hub.research import _client

    assert inspect.getsource(_client).count("follow_redirects=True") == 0, (
        "клиент по-прежнему следует за редиректами сам")


def test_сниппеты_не_приклеиваются_к_следующему() -> None:
    """Описание лежит в ссылке после заголовка, а результат закрывался на
    `</a>` заголовка — то есть раньше, чем описание прочитано. Следующий
    результат получал чужое описание."""
    from hub.research import _Results

    html = (
        '<a class="result__a" href="https://example.com/1">Первый</a>'
        '<a class="result__snippet" href="#">Описание ПЕРВОГО</a>'
        '<a class="result__a" href="https://example.com/2">Второй</a>'
        '<a class="result__snippet" href="#">Описание ВТОРОГО</a>'
    )
    parser = _Results()
    parser.feed(html)
    parser.close()
    got = {h.title: h.snippet for h in parser.hits}
    assert got.get("Первый") == "Описание ПЕРВОГО", got
    assert got.get("Второй") == "Описание ВТОРОГО", got


# ====================================================== стенд


def test_проверка_стенда_запускает_процесс() -> None:
    """Окружение проверки собиралось как в POSIX: без `SystemRoot`, `TEMP` и
    прочих переменных, которых Windows требует для запуска процесса. То есть
    проверки `tests_pass` и `command_succeeds` не могли проходить на основной
    платформе проекта."""
    from bench.checks import _run
    from bench.sandbox import _sandbox_env

    env = _sandbox_env(Path(tempfile_root()))
    assert "PATH" in env
    if sys.platform.startswith("win"):
        assert "SystemRoot" in env or "SYSTEMROOT" in env, sorted(env)
        assert "TEMP" in env, sorted(env)


def tempfile_root() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp())


# ====================================================== интерфейс


def test_интерфейс_переносит_данные_в_атрибуты() -> None:
    """Значения в `onclick` ломали разметку.

    `esc()` превращает апостроф в `&#39;`, а HTML-парсер декодирует
    сущности **до** компиляции JavaScript, так что `&#39;` снова становится
    `'` и рвёт строку. Перевод строки `esc()` не трогает вовсе, а содержимое
    файла и текст инструкции многострочные — кнопки «копировать» не работали
    ни разу.
    """
    ui = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    assert "function copyAttr(" in ui, "помощник для чтения из атрибута нет"
    assert "data-copy=" in ui, "данные не переносятся в атрибут"
    assert "onclick=\"copy('${esc(r.content" not in ui, (
        "содержимое файла всё ещё вставляется прямо в обработчик")
    assert "onclick=\"copy('${esc(e.instruction)" not in ui, (
        "текст инструкции всё ещё вставляется прямо в обработчик")


def test_вкладка_очереди_достижима() -> None:
    """Кнопки «одобрить план» и «ответить» рисуются в `#p-queue`, а кнопки
    вкладки у неё не было: секция скрыта, пока на ней нет `.on`, а `ltab()`
    ставит `.on` только по имени нажатой вкладки. Задача в статусе `asking`
    висела до перезапуска."""
    ui = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    assert 'data-p="queue"' in ui, "вкладки очереди нет"
    assert 'id="p-queue"' in ui, "секции очереди нет"


def test_пинг_недоступных_шлёт_список() -> None:
    """Кнопка обещала перепроверить недоступные модели, а отправляла пустой
    запрос — то есть пинговала весь реестр, и рапортовала «из N недоступных»."""
    ui = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    assert "refs: dead.map" in ui, "список недоступных не уходит на сервер"


def test_прямой_замер_не_считается_сделанным_по_замеру_с_vpn() -> None:
    ui = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    assert "summary.measured || 0) > 0) GEO.directDone" not in ui, (
        "прямым замером считается любой замер, включая с VPN")
    assert "mode === 'direct'" in ui, "прямой замер не отличается от замера с VPN"