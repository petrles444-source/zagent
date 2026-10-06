"""Субагенты: разбиение, выбор модели, блокировки, след работы.

Пять вещей, которые обязаны работать, и каждая проверяется отдельно:

* **разбиение** читается даже из неидеального ответа модели;
* **модель выбирается осознанно**, а не первой попавшейся, и причина
  записывается — иначе выбор невозможно ни проверить, ни оспорить;
* **аккаунт проверяется до выдачи части**, а не после: выдать часть из
  двадцати шагов аккаунту с тремя запросами значит потерять её на середине;
* **части не перетирают друг друга**, и маска не превращается в запрет на
  чужую работу внутри той же папки;
* **след работы виден**: промты, ответы, вызовы инструментов.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.assign import (  # noqa: E402
    REQUESTS_PER_STEP,
    Candidate,
    assign,
    assign_all,
    collect_candidates,
    estimated_requests,
    needs_tools,
    needs_vision,
)
from hub.autonomy import AccessLevel, Autonomy, Guard  # noqa: E402
from hub.keyring import KeyRing  # noqa: E402
from hub.subagents import (  # noqa: E402
    Part,
    PartResult,
    denied_for,
    denied_globs_for,
    parse_parts,
    run_parts,
    scope_paths,
    summary_for,
)


# =============================================================== разбиение


BACKTICK = "`" * 3


def test_разбирается_обычный_json() -> None:
    parts = parse_parts('{"parts": [{"title": "дизайн", "brief": "сверстай главную",'
                        ' "files": ["index.html"]}]}')
    assert [p.title for p in parts] == ["дизайн"]
    assert parts[0].files == ["index.html"]
    assert parts[0].name == "часть 1"


def test_разбирается_блок_json() -> None:
    parts = parse_parts(BACKTICK + 'json\n{"parts": [{"brief": "сделай a"}]}\n'
                        + BACKTICK)
    assert [p.brief for p in parts] == ["сделай a"]


def test_разбираются_русские_и_чужие_ключи() -> None:
    parts = parse_parts('{"части": [{"название": "стили", "задача": "напиши css",'
                        ' "пути": ["a.css"]}]}')
    assert [p.title for p in parts] == ["стили"]
    assert parts[0].files == ["a.css"]


def test_части_нумеруются_по_порядку() -> None:
    parts = parse_parts('{"parts": [{"brief": "a"}, {"brief": "b"}, {"brief": "c"}]}')
    assert [p.name for p in parts] == ["часть 1", "часть 2", "часть 3"]


def test_лимит_частей_соблюдается() -> None:
    body = '{"parts": [' + ", ".join('{"brief": "часть %d"}' % i
                                        for i in range(20)) + "]}"
    assert len(parse_parts(body, limit=4)) == 4


def test_мусор_не_принимается() -> None:
    for text in ("", "   ", "разбивать нечего", "[]", "{\"parts\": []}",
                 '{"parts": [{"title": "без задания"}]}'):
        assert parse_parts(text) == [], text


# =============================================================== области


def test_область_разворачивается() -> None:
    base = ROOT
    assert scope_paths(["index.html"], base) == [str((base / "index.html").resolve())]


def test_маска_даёт_корень() -> None:
    base = ROOT
    assert scope_paths(["assets/*.css"], base) == [str((base / "assets").resolve())]


def test_части_не_перетирают_друг_друга(tmp_path: Path) -> None:
    parts = [
        Part(title="дизайн", brief="сверстай", files=["index.html"]),
        Part(title="стили", brief="напиши css", files=["assets/style.css"]),
    ]
    assert denied_for(parts[0], parts, tmp_path) == \
        [str((tmp_path / "assets" / "style.css").resolve())]


def test_маска_не_запрещает_соседнюю_работу(tmp_path: Path) -> None:
    """Ключевой случай: стили и скрипты лежат в одной папке.

    Если маску `assets/*.css` свести к папке `assets`, часть со скриптами
    получит запрет на собственную работу и не сможет создать свой файл.
    """
    parts = [
        Part(title="стили", brief="css", files=["assets/*.css"]),
        Part(title="скрипты", brief="js", files=["assets/app.js"]),
    ]
    globs = denied_globs_for(parts[0], parts)
    # Маска — это чужая маска: у второй части путь обычный, не с маской.
    assert globs == [], globs
    denied = denied_for(parts[0], parts, tmp_path)
    assert denied == [str((tmp_path / "assets" / "app.js").resolve())], denied
    # Папка целиком в запрете не оказалась — иначе вторая часть не смогла бы
    # создать свой файл.
    assert all(not p.endswith("assets") for p in denied)


def test_чужая_маска_остаётся_маской(tmp_path: Path) -> None:
    """Маска `assets/*.css` у другой части не должна превращаться в папку."""
    parts = [
        Part(title="стили", brief="css", files=["assets/*.css"]),
        Part(title="скрипты", brief="js", files=["assets/*.js"]),
    ]
    globs = denied_globs_for(parts[1], parts)
    assert globs == ["assets/*.css"], globs
    denied = denied_for(parts[1], parts, tmp_path)
    assert all(not p.endswith("assets") for p in denied), denied


def test_запрет_по_маске_работает(tmp_path: Path) -> None:
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path)
    guard.set_workspace(tmp_path, "ws")
    guard.denied_globs = ["assets/*.css"]

    denied, _ = guard.check_path(str(tmp_path / "assets" / "style.css"), writing=True)
    allowed, _ = guard.check_path(str(tmp_path / "assets" / "app.js"), writing=True)
    assert denied is False, "свой стиль часть стили должна писать"
    assert allowed is True, "чужой файл внутри той же папки трогать нельзя"


def test_запрет_не_срабатывает_на_похожем_имени(tmp_path: Path) -> None:
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path)
    guard.set_workspace(tmp_path, "ws")
    guard.denied_globs = ["assets/*.css"]
    allowed, _ = guard.check_path(str(tmp_path / "assets" / "style.cssx"), writing=True)
    assert allowed is True


# =============================================================== выбор модели


def cand(ref: str, *, tier=1, ms=1000, vision=False, tools=True, keys=1,
         spare=None):
    return Candidate(ref=ref, gateway=ref.split("/", 1)[0],
                     model=ref.split("/", 1)[1], tier=tier, vision=vision,
                     tools=tools, avg_ms=ms, free_keys=keys, spare=spare)


def test_выбирается_быстрая_модель() -> None:
    """Медленная модель не должна выигрывать только потому, что её ранг выше."""
    pool = [
        cand("a/медленная", tier=1, ms=30000),
        cand("a/быстрая", tier=3, ms=400),
    ]
    got = assign(pool, Part(title="x", brief="сделай", files=["a.js"]))
    assert got is not None and got.ref == "a/быстрая", got


def test_причина_записывается() -> None:
    pool = [cand("a/x", tier=2, ms=800, keys=3, spare=100)]
    got = assign(pool, Part(title="x", brief="сделай", files=["a.js"]))
    assert got is not None
    assert "ранг 2" in got.why
    assert "0.80" in got.why
    assert "аккаунтов 3" in got.why
    assert "запас 100" in got.why


def test_модель_без_инструментов_не_берётся_для_кода() -> None:
    pool = [
        cand("a/без-инструментов", tier=1, ms=100, tools=False),
        cand("a/с-инструментами", tier=5, ms=2000),
    ]
    got = assign(pool, Part(title="x", brief="напиши код", files=["a.js"]))
    assert got is not None and got.ref == "a/с-инструментами"


def test_для_текста_инструменты_не_нужны() -> None:
    assert needs_tools("придумай названия разделов", []) is False
    assert needs_tools("напиши описание", ["index.html"]) is True


def test_картинке_нужно_зрение() -> None:
    pool = [
        cand("a/зрячая", tier=1, ms=9000, vision=True),
        cand("a/обычная", tier=1, ms=400),
    ]
    got = assign(pool, Part(title="картинка", brief="сделай блок по картинке",
                            files=["hero.png"]))
    assert got is not None and got.ref == "a/зрячая"


def test_по_описанию_зрение_не_нужно() -> None:
    assert needs_vision("сверстай главную по описанию", ["index.html"]) is False


def test_часть_не_выдаётся_без_запаса_запросов() -> None:
    """Лучше подождать, чем начать и бросить на середине."""
    pool = [cand("a/почти-пустая", tier=1, ms=300, spare=2)]
    got = assign(pool, Part(title="x", brief="сделай", files=["a.js"]))
    assert got is not None
    assert got.admitted is False
    assert "ждёт" in got.note


def test_нулевой_остаток_не_похож_на_неизвестный() -> None:
    """Аккаунт с нулём запросов — это не «сведений нет».

    Если их спутать, часть выдаётся аккаунту, который не выполнит ни одного
    запроса: агент стартует, упирается в лимит и теряет всё, что успел.
    """
    pool = [cand("a/нулевой", tier=1, ms=300, spare=0)]
    got = assign(pool, Part(title="x", brief="сделай", files=["a.js"]))
    assert got is not None and got.admitted is False, got

    unknown = [cand("a/неизвестный", tier=1, ms=300, spare=None)]
    allowed = assign(unknown, Part(title="x", brief="сделай", files=["a.js"]))
    assert allowed is not None and allowed.admitted is True, (
        "нет сведений — это не запрет: судим по карантину"
    )


def test_части_разводятся_по_моделям() -> None:
    pool = [cand(f"a/м{i}", tier=1, ms=500 + i * 100) for i in range(4)]
    parts = [Part(title=f"п{i}", brief=f"сделай {i}", files=[f"f{i}.js"])
             for i in range(4)]
    got = assign_all(pool, parts)
    assert len({g.ref for g in got if g}) == 4


def test_бюджет_аккаунта_не_превышается() -> None:
    """Четыре части на аккаунт со сотней запросов — это сто сорок обещаний.

    Лимит кончился бы на середине последней части, и её пришлось бы
    начинать заново. Поэтому бюджет расходуется по ходу назначения.
    """
    need = estimated_requests()
    pool = [cand("a/одна", tier=1, ms=400, spare=need * 2 + need // 2)]
    parts = [Part(title=f"код{i}", brief=f"напиши модуль {i}",
                  files=[f"m{i}.py"]) for i in range(3)]
    got = assign_all(pool, parts)
    assert [g.admitted for g in got] == [True, True, False], got


def test_тяжёлая_часть_получает_аккаунт_раньше_лёгкой() -> None:
    """Если аккаунт один и хватает только на одну часть, отдавать его надо
    той, которую пришлось бы дольше всего начинать заново.

    Лёгкую часть (придумать текст) главный агент доделает сам за пару шагов.
    """
    need = estimated_requests()
    pool = [cand("a/одна", tier=1, ms=400, spare=need)]
    parts = [
        Part(title="текст", brief="придумай названия разделов", files=[]),
        Part(title="код", brief="напиши модуль", files=["m.py"]),
    ]
    got = assign_all(pool, parts)
    by_title = {g and parts[i].title: g for i, g in enumerate(got)}
    assert by_title["код"].admitted is True
    assert by_title["текст"] is None or by_title["текст"].admitted is False


def test_оценка_запросов_разумна() -> None:
    assert REQUESTS_PER_STEP >= 2.0, "занизить опасно: аккаунт кончится в середине"
    assert estimated_requests(10) >= 20


def test_без_подходящих_моделей_не_выдаём() -> None:
    pool = [cand("a/зрячая", vision=True, tier=1)]
    got = assign(pool, Part(title="картинка", brief="по фото", files=["a.png"]))
    assert got is not None and got.ref == "a/зрячая"
    pool = [cand("a/обычная", tier=1)]
    got = assign(pool, Part(title="картинка", brief="по фото", files=["a.png"]))
    assert got is None


# =============================================================== след


class _FakeAgent:
    """Агент, который пишет файл и ведёт след."""

    def __init__(self, name: str = "", text: str = "готово", boom: bool = False):
        self.part = name
        self.messages: list[dict] = []
        self.trace_on = False
        self.artifacts: list[dict] = []
        self.text = text
        self.boom = boom
        self.prompts = 0

    def set_task(self, task: str) -> None:
        self.task = task
        self.messages = [{"role": "system", "content": "система"},
                         {"role": "user", "content": task}]

    async def rebuild_system_prompt(self) -> None:
        return None

    async def run(self) -> dict:
        if self.boom:
            raise RuntimeError("модель упала")
        self.prompts += 1
        return {"ok": True, "last": self.text, "models_used": ["тест/модель"],
                "steps": 2, "tokens": 10,
                "artifacts": [{"path": "out.txt"}],
                "trace": [{"n": 0, "tool": "write_file",
                           "args": {"path": "out.txt"}, "result": {"ok": True}}]}


def test_части_идут_параллельно() -> None:
    parts = [Part(title=f"п{i}", brief=f"сделай {i}", files=[f"f{i}"])
             for i in range(3)]
    made: list[str] = []

    def factory(part):
        made.append(part.name)
        return _FakeAgent(part.name)

    results = asyncio.run(run_parts(parts, base=ROOT, make_agent=factory,
                                    task_context="общая задача"))
    assert len(results) == 3
    assert all(r.ok for r in results)
    assert len(made) == 3


def test_одна_упавшая_часть_не_роняет_остальные() -> None:
    parts = [
        Part(title="хорошая", brief="a", files=["a"]),
        Part(title="плохая", brief="b", files=["b"]),
    ]
    state = {"n": 0}

    def factory(part):
        state["n"] += 1
        return _FakeAgent(part.name, boom=(state["n"] == 2))

    results = asyncio.run(run_parts(parts, base=ROOT, make_agent=factory,
                                    task_context="задача"))
    by_title = {r.part.title: r for r in results}
    assert by_title["хорошая"].ok is True
    assert by_title["плохая"].ok is False
    assert "RuntimeError" in by_title["плохая"].error


def test_часть_видит_исходную_задачу() -> None:
    """Без исходной задачи агент делает узкий кусок, не согласующийся с
    остальными, и не знает, что это часть общей работы."""
    seen: list[str] = []

    def factory(part):
        agent = _FakeAgent(part.name)
        original = agent.set_task

        def set_task(task: str) -> None:
            original(task)
            seen.append(task)
        agent.set_task = set_task
        return agent

    parts = [Part(title="стили", brief="напиши css", files=["a.css"])]
    asyncio.run(run_parts(parts, base=ROOT, make_agent=factory,
                          task_context="сделай многостраничный сайт"))
    assert "сделай многостраничный сайт" in seen[0]
    assert "напиши css" in seen[0]


def test_сводка_говорит_о_неудачных_частях() -> None:
    """Нельзя объявить задачу выполненной, если часть не выполнена."""
    good = PartResult(part=Part(title="стили", brief="css", files=["a.css"]),
                      ok=True, summary="сделал a.css")
    bad = PartResult(part=Part(title="скрипты", brief="js", files=["b.js"]),
                     ok=False, error="модель упала")
    text = summary_for([good, bad], ROOT)
    assert "НЕ ВЫПОЛНЕНО" in text
    assert "модель упала" in text
    assert "сделал a.css" in text


def test_в_сводке_есть_созданные_файлы() -> None:
    slot = PartResult(part=Part(title="дизайн", brief="x", files=["index.html"]),
                      ok=True, summary="сделал",
                      artifacts=[{"path": "index.html"}])
    assert "index.html" in summary_for([slot], ROOT)


# =============================================================== сбор следов


def test_след_агента_пишется_только_когда_включён() -> None:
    """Обычная задача не должна платить за то, что её след никто не смотрит."""
    from hub.agent import TRACE_LIMIT, Agent

    agent = Agent.__new__(Agent)
    agent.trace = []
    agent.trace_on = False
    agent.part = ""
    agent.on_event = None
    agent.messages = [{"role": "user", "content": "задача"}]
    asyncio.run(agent._trace_call(1, {"text": "ответ", "model": "м"}))
    assert agent.trace == [], "след пишется без запроса на него"

    agent.trace_on = True
    asyncio.run(agent._trace_call(1, {"text": "ответ", "model": "м",
                                     "tokens_in": 5, "tokens_out": 7,
                                     "duration_ms": 300}))
    assert len(agent.trace) == 1
    record = agent.trace[0]
    assert record["got"]["text"] == "ответ"
    assert record["got"]["model"] == "м"
    assert record["got"]["tokens_in"] == 5


def test_след_обрезается() -> None:
    """Полная история на пятидесятом шаге — это мегабайты в браузере."""
    from hub.agent import TRACE_LIMIT, Agent

    agent = Agent.__new__(Agent)
    agent.trace = []
    agent.trace_on = True
    agent.part = ""
    agent.on_event = None
    agent.messages = [{"role": "user", "content": "задача"}]

    async def fill() -> None:
        for _ in range(TRACE_LIMIT + 30):
            await agent._trace_call(1, {"text": "x", "model": "м"})
    asyncio.run(fill())
    assert len(agent.trace) <= TRACE_LIMIT


def test_шаг_и_инструмент_помечены_частью() -> None:
    """По журналу должно быть видно, чей это шаг."""
    from hub.agent import Agent

    agent = Agent.__new__(Agent)
    assert agent is not None
    # Метки попадают в события: без них шаги частей и главного агента
    # неразличимы, а выполняются они одновременно.
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parent.parent / "hub" / "agent.py").read_text(
        encoding="utf-8")
    assert '"sub": self.part' in src
    assert '"sub": self.part' in src.split("async def _step")[1][:600]


def test_остаток_лимита_запоминается() -> None:
    """Лимит должен быть известен ДО запроса, а не после 429."""
    ring = KeyRing(keys=["k1", "k2"])
    ring.note_quota("k1", {"requests_remaining": 2})
    ring.note_quota("k2", {"requests_remaining": 100})

    assert ring.capacity("k1", 20)[0] is False
    assert ring.capacity("k2", 20)[0] is True
    best, note = ring.best_key(20)
    assert best == "k2"
    assert "осталось" in note


def test_без_сведений_о_лимите_не_блокируем() -> None:
    """Провайдер не сообщает остаток — это не повод ничего не выдавать."""
    ring = KeyRing(keys=["k1"])
    assert ring.capacity("k1", 100)[0] is True
    assert ring.best_key(100)[0] == "k1"


def test_канадидаты_берутся_из_замеров() -> None:
    """Кандидатом может быть только модель, о которой что-то известно.

    У непроверенной модели нет ни задержки, ни истории отказов: поручать ей
    часть — значит проверять её на настоящей задаче, где цена ошибки в том,
    что часть не сделана.
    """
    from hub.tiers import TierBook

    class State:
        def __init__(self, gateway, model, ms, status, cooldown=0):
            self.gateway, self.model = gateway, model
            self.avg_ms, self.last_status = ms, status
            self.cooldown_left = cooldown

    class Selector:
        tierbook = TierBook.empty()
        states = {
            "a/проверенная": State("a", "проверенная", 500, "ok"),
            "a/непроверенная": State("a", "непроверенная", 0, ""),
            "a/в_карантине": State("a", "в_карантине", 400, "ok", cooldown=30),
            "a/упавшая": State("a", "упавшая", 400, "down"),
        }

    ring = KeyRing(keys=["k"])
    got = collect_candidates(Selector(), ring)
    refs = [c.ref for c in got]
    assert "a/непроверенная" not in refs, "непроверенной модели работа не даётся"
    assert "a/в_карантине" not in refs, "модель в карантине не кандидат"
    assert "a/упавшая" not in refs, "упавшая модель не кандидат"
    assert "a/проверенная" in refs, refs


def test_остаток_берется_из_заголовков() -> None:
    """Что провайдер сообщил об остатке — то и должно уйти в назначение."""
    from hub.tiers import TierBook

    ring = KeyRing(keys=["k1", "k2"])
    ring.note_quota("k1", {"requests_remaining": 5})
    ring.note_quota("k2", {"requests_remaining": 900})

    class Registry:
        def existing(self, gateway_id: str) -> KeyRing:
            return ring

    class State:
        gateway, model = "a", "модель"
        avg_ms, last_status, cooldown_left = 500, "ok", 0

    class Selector:
        tierbook = TierBook.empty()
        states = {"a/модель": State()}

    got = collect_candidates(Selector(), Registry())
    assert got, "модель с замерами обязана быть кандидатом"
    assert got[0].spare == 900, "берётся лучший аккаунт, а не худший"
    assert got[0].free_keys == 2


def test_остаток_считается_по_своему_расходу() -> None:
    """Провайдер остаток не сообщает — но лимит известен из документации.

    Так у NVIDIA: заголовков квоты нет, лимит 40 запросов в минуту на аккаунт
    есть. Без своего счётчика остаток узнаётся только после 429, а к тому
    моменту часть работы уже потеряна.
    """
    ring = KeyRing(keys=["k1", "k2"])
    ring.set_rpm(40)
    from hub.assign import _spare_requests

    class Registry:
        def existing(self, gateway_id: str) -> KeyRing:
            return ring

    assert _spare_requests(Registry(), "a") == 40, "в обоих аккаунтах полный запас"
    for _ in range(20):
        ring.note_spent("k1", 40)
    assert _spare_requests(Registry(), "a") == 40, "второй аккаунт ещё свободен"
    for _ in range(40):
        ring.note_spent("k1", 40)
    assert _spare_requests(Registry(), "a") == 40, "первый исчерпан, второй цел"
    for _ in range(40):
        ring.note_spent("k2", 40)
    assert _spare_requests(Registry(), "a") == 0, "оба аккаунта выбрали лимит"


def test_лимит_из_конфига_раздаётся_аккаунтам() -> None:
    from hub.keyring import KeyRegistry

    reg = KeyRegistry()
    gateway = {"id": "nvidia", "api_keys": ["k1", "k2", "k3"],
               "rpm_per_account": 40}
    reg.apply_limits([gateway])
    ring = reg.ring("nvidia", gateway["api_keys"])
    assert {ring.rpm_of(k) for k in ring.keys} == {40}, ring.rpm

    reg2 = KeyRegistry()
    reg2.apply_limits([{"id": "groq", "api_keys": ["g1"]}])
    assert not reg2.ring("groq", ["g1"]).rpm_of("g1"), (
        "без лимита в конфиге ничего не выдумываем"
    )


def test_смена_набора_ключей_не_сбрасывает_расход() -> None:
    """Добавление ключа не должно выглядеть как «аккаунты свежие»."""
    from hub.keyring import KeyRegistry

    reg = KeyRegistry()
    reg.apply_limits([{"id": "a", "api_keys": ["k1"], "rpm_per_account": 40}])
    reg.ring("a", ["k1"]).note_spent("k1", 40)
    ring = reg.ring("a", ["k1", "k2"])
    assert ring.spent_in_minute("k1") == 1, "расход сохранён при смене набора"
    assert ring.rpm_of("k2") == 40, (
        "новый ключ обязан знать лимит шлюза, иначе 429 будет только на нём"
    )