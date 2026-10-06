"""Папки и сессии: то, что человек нажимает в интерфейсе.

Три поломки, из-за которых кнопки выглядели неработающими:

* `prompt()` подавляется во встроенных браузерах — «новая сессия» и «выбрать
  папку» молча ничего не делали, хотя на сервере всё работало;
* выбор папки требовал уже существующий каталог, и отказ читался как «ничего
  не произошло»;
* в панели не было видно текущего пути, поэтому непонятно было, куда вообще
  агент пишет.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.ui import UI_HTML  # noqa: E402


def script() -> str:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    _, _, rest = src.partition("</style>")
    return rest.partition("<script>")[2].partition("</script>")[0]


def test_скрипт_реально_извлекается() -> None:
    """Без этой проверки остальные тесты молча проверяли бы пустую строку."""
    body = script()
    assert len(body.splitlines()) > 100, f"извлеклось {len(body)} строк"


# =============================================================== диалоги


def test_нет_родных_prompt_и_confirm() -> None:
    """Родные вызовы блокируют страницу и подавляются частью браузеров."""
    body = script()
    for bad in ("prompt(", "confirm(", "alert("):
        offenders = [
            n for n, line in enumerate(body.splitlines(), start=1)
            if bad in line and not line.strip().startswith("//")
        ]
        assert not offenders, f"{bad} остался на строке {offenders}"


def test_свои_диалоги_есть() -> None:
    for name in ("function askText", "function askYes", "async function askFolder",
                 "function hideFileMenu"):
        assert name in script(), f"нет {name}"


def test_диалог_в_разметке() -> None:
    """Без контейнера диалога в DOM обработчики упадут при первом нажатии."""
    for element in ('id="dlg"', 'id="dlgInput"', 'id="dlgOk"',
                    'id="dlgCancel"', 'id="dlgTitle"', 'id="dlgText"'):
        assert element in UI_HTML, f"нет {element}"


def test_диалог_скрыт_по_умолчанию() -> None:
    assert 'id="dlg" hidden' in UI_HTML, "диалог не должен висеть поверх экрана"


# =============================================================== выбор папки


def test_кнопка_называет_что_делает() -> None:
    """«+ папка» ничего не говорило о том, что откроется выбор каталога."""
    assert "выбрать папку" in UI_HTML
    assert "+ папка" not in UI_HTML


def test_путь_показан_в_панели() -> None:
    body = script()
    assert "Сейчас здесь" in body, "не видно, где работает агент"
    assert "cur.path" in body, "путь активной папки не выводится"


def test_системный_выбор_папки() -> None:
    assert "showDirectoryPicker" in script()


def test_есть_запасной_ввод_пути() -> None:
    """Без showDirectoryPicker кнопка должна всё равно работать."""
    body = script()
    assert "askText" in body
    assert "showDirectoryPicker" in body
    # Обработчик отказа не должен ронять функцию.
    assert "AbortError" in body


# =============================================================== серверная часть


def test_создание_папки_при_добавлении(tmp_path: Path) -> None:
    """Папки может не быть: человек выбрал каталог, а его не создали.

    Отказ здесь читался как «кнопка не работает», поэтому добавление умеет
    создавать папку. Тест работает на временном корне: настоящий
    `config/workspaces.json` трогать нельзя, иначе состояние утекает между
    прогонами и второй запуск падает на «уже добавлен».
    """
    import pytest

    from hub.workspace import WorkspaceError, WorkspaceManager

    root = tmp_path / "проект"
    (root / "config").mkdir(parents=True)
    manager = WorkspaceManager(root)
    target = root / "новая-папка"

    with pytest.raises(WorkspaceError):
        manager.add(str(target), name="нет-такой")
    assert not target.exists(), "без create папка создаваться не должна"

    manager.add(str(target), name="создам-сам", create=True)
    assert target.is_dir(), "папка не создана"
    assert manager.get("создам-сам").path == str(target.resolve())


def test_describe_отдаёт_папку_проектов() -> None:
    from hub.workspace import WorkspaceManager

    info = WorkspaceManager(ROOT).describe()
    assert info["projects_dir"].endswith("projects")
    assert info["code_root"]


def test_self_edit_выключен_по_умолчанию(tmp_path: Path) -> None:
    """Правка своего кода включается руками, а не молча наследуется."""
    from hub.workspace import WorkspaceManager

    root = tmp_path / "проект"
    (root / "config").mkdir(parents=True)
    manager = WorkspaceManager(root)
    manager.update(manager.items[0].id, self_edit=True)

    for w in WorkspaceManager(root).items:
        assert w.self_edit is True or w.self_edit is False
    # А вот с нуля — всегда выключено.
    fresh = tmp_path / "чистый"
    (fresh / "config").mkdir(parents=True)
    assert all(not w.self_edit for w in WorkspaceManager(fresh).items)


def test_is_code_root_узнаёт_себя() -> None:
    from hub.workspace import Workspace

    here = Workspace(id="x", name="x", path=str(ROOT))
    assert here.is_code_root() is True
    other = Workspace(id="y", name="y", path=str(ROOT / "projects"))
    assert other.is_code_root() is False


def test_self_edit_сохраняется(tmp_path: Path) -> None:
    """Флаг обязан пережить перезапуск: иначе режим молча выключится."""
    from hub.workspace import WorkspaceManager

    root = tmp_path / "проект"
    (root / "config").mkdir(parents=True)
    manager = WorkspaceManager(root)
    first = manager.items[0].id

    manager.update(first, self_edit=True)
    assert WorkspaceManager(root).get(first).self_edit is True
    manager.update(first, self_edit=False)


def test_self_edit_доходит_до_промпта() -> None:
    from hub.agent import build_system_prompt
    from hub.autonomy import AccessLevel, Autonomy, Guard

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.NORMAL)
    plain = build_system_prompt(guard, None, workspace=str(ROOT))
    assert "РЕЖИМ РАЗРАБОТКИ" not in plain, "режим попал в обычный промпт"

    dev = build_system_prompt(guard, None, workspace=str(ROOT), self_edit=True)
    assert "РЕЖИМ РАЗРАБОТКИ" in dev
    assert "check_ui.py" in dev, "не сказано, чем проверять"


# =============================================================== сессии


def test_сессии_приходят_из_api() -> None:
    """Пустой ответ означает «ничего не создалось», а кнопка молчит."""
    from hub.worker import Worker
    from hub.store import Store
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(ROOT)
        worker = Worker(ROOT, store)
        try:
            worker.store = store
            before = len(store.list_sessions(worker.workspaces.active_id))
            r = worker.new_session("проверка")
            assert r["ok"] is True, r
            after = len(store.list_sessions(worker.workspaces.active_id))
            assert after == before + 1, f"сессий было {before}, стало {after}"
            assert worker.remove_session(r["session_id"])["ok"] is True
        finally:
            store.close()


def test_пересборка_промпта_меняет_режим() -> None:
    """Флаг ставится после set_task: без пересборки модель его не увидит."""
    from hub.agent import Agent, AgentConfig
    from hub.autonomy import AccessLevel, Autonomy, Guard
    from hub.registry import Registry
    from hub.select import Selector
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.NORMAL)
    agent = Agent(Selector(Registry(gateways=[], models=[]), TierBook({})), guard,
                  AgentConfig(base_dir=str(ROOT)))
    agent.set_task("задача")
    assert "РЕЖИМ РАЗРАБОТКИ" not in agent.messages[0]["content"]
    agent.self_edit = True
    agent.rebuild_system_prompt()
    assert "РЕЖИМ РАЗРАБОТКИ" in agent.messages[0]["content"]


def test_веб_разведка_доходит_до_промпта() -> None:
    """Флаг ставится после set_task: без пересборки модель его не увидит."""
    from hub.agent import Agent, AgentConfig
    from hub.autonomy import AccessLevel, Autonomy, Guard
    from hub.registry import Registry
    from hub.select import Selector
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.NORMAL)
    agent = Agent(Selector(Registry(gateways=[], models=[]), TierBook({})), guard,
                  AgentConfig(base_dir=str(ROOT)))
    agent.set_task("задача")
    content = agent.messages[0]["content"]
    assert "web_search" not in content, "поиск доступен без разведки"
    assert "ВЕБ-РАЗВЕДКА" not in content

    agent.web_research = True
    agent.rebuild_system_prompt()
    content = agent.messages[0]["content"]
    assert "ВЕБ-РАЗВЕДКА" in content
    assert "web_search" in content and "web_fetch" in content


def test_веб_разведка_объясняет_зачем_читать_страницу() -> None:
    """Без этого модель ищет один раз и отвечает по памяти."""
    from hub.agent import build_system_prompt
    from hub.autonomy import AccessLevel, Autonomy, Guard

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.NORMAL)
    web = build_system_prompt(guard, None, workspace=str(ROOT), web_research=True)
    assert "web_fetch" in web, "не сказано, что найденное надо открыть"
    assert "не выдумывай" in web, "не сказано, что делать с недоступным сайтом"


# =============================================================== результат задачи


def test_в_ответе_есть_ссылки_на_результат() -> None:
    """Пути текстом бесполезны: открывать приходилось вручную."""
    body = script()
    assert "function renderArtifacts" in body
    assert "openEntry" in body
    assert "target=\"_blank\"" in body, "нет открытия в браузере"


def test_артефакты_собираются_агентом() -> None:
    from hub.agent import Agent, AgentConfig
    from hub.autonomy import AccessLevel, Autonomy, Guard
    from hub.registry import Registry
    from hub.select import Selector
    from hub.tiers import TierBook
    from hub.tools import ToolResult

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO)
    agent = Agent(Selector(Registry(gateways=[], models=[]), TierBook({})), guard,
                  AgentConfig(base_dir=str(ROOT)))
    agent._note_artifact(
        "write_file", {"path": "calculator/index.html"},
        ToolResult(True, data={"path": "calculator/index.html"}),
    )
    assert agent.artifacts, "записанный файл не запомнился"
    assert agent.artifacts[0]["path"] == "calculator/index.html"


def test_успех_несёт_артефакты() -> None:
    body = script()
    assert "e.artifacts" in body, "ответ не показывает созданное"


# =============================================================== режимы работы


def test_у_режимов_нет_двух_setmode() -> None:
    """Одно имя — две функции, и вторая молча перетирает первую.

    Режим задачи и выбор модели оба звались `setMode`. Второе объявление
    выигрывало, и клик по карточке режима уходил в выбор модели с аргументом
    `plain`: кнопка выглядела нерабочей.
    """
    names = re.findall(r"(?:async\s+)?function\s+(\w+)\s*\(", script())
    repeats = sorted({n for n in names if names.count(n) > 1})
    assert not repeats, f"функция объявлена дважды: {repeats}"


def test_карточки_режима_вызывают_свою_функцию() -> None:
    body = script()
    assert "async function setTaskMode(" in body
    assert "onclick=\"setTaskMode(" in body
    # Переключатель выбора модели сохранён под своим именем.
    assert "async function setMode(m)" in body


def test_каждая_карточка_показывает_своё_состояние() -> None:
    """Раньше состояние бралось из позиции в массиве.

    «Субагенты» показывали флаг веб-разведки: карточка выглядела включённой,
    когда включали совсем другое.
    """
    body = script()
    pairs = re.findall(r"\['(\w+)', '(\w*)'\],", body)
    mapping = dict(pairs)
    assert mapping.get("subagents") == "subagents", mapping
    assert mapping.get("research") == "research", mapping
    assert mapping.get("plain") == "", mapping
    assert "swarm" in mapping, "нет режима «разведка + субагенты»"


def test_клик_по_режиму_не_закрывает_панель() -> None:
    """Иначе смену не видно: окно исчезает и кажется, что ничего не произошло."""
    body = script()
    tail = body.partition("async function setTaskMode(")[2]
    tail = tail.partition("\nasync function ")[0]
    assert "openModePick()" not in tail, "после смены режима панель закрывается"
    assert "renderModeCards()" in tail, "карточки не перерисовались"


def test_правка_своего_кода_скрыта_из_списка() -> None:
    """Режим оставлен в коде, но в меню его нет — включать пока нельзя."""
    body = script()
    listing = body.partition("const cards = [")[2].partition("].map")[0]
    assert "'selfdev'" not in listing, "правка своего кода снова в меню"
    assert "selfdev: {" in body, "описание режима удалено — вернуть нечем"


# =============================================================== режим «Авто»


def test_авто_включён_по_умолчанию() -> None:
    """Требование выбрать режим перед каждой задачей превращается либо в
    лишние секунды, либо в привычку жать «обычный» не глядя. Тогда режимы
    существуют, но никогда не включаются."""
    body = script()
    assert "let CUR_MODE = 'auto';" in body
    assert "auto: true" in body.split("const TASK_FLAGS")[1][:120]


def test_авто_в_меню_и_объясняется() -> None:
    body = script()
    assert "['auto', 'auto']" in body, "карточки «Авто» нет в списке"
    assert "function renderAutoNote" in body
    assert "AUTO_PICK" in body, "решение не показывается"


def test_авто_передаётся_на_сервер() -> None:
    body = script()
    assert "auto_mode: TASK_FLAGS.auto" in body


def test_решение_авто_показывается() -> None:
    """Без объяснения «Авто» выглядит как произвол, и его выключают."""
    body = script()
    assert "e.type === 'mode_chosen'" in body
    assert "AUTO_PICK = e" in body


def test_ручной_режим_снимает_авто() -> None:
    """Иначе «Авто» решал бы, а ручной флаг всё равно действовал бы."""
    body = script()
    tail = body.partition("async function setTaskMode(")[2]
    tail = tail.partition("\nasync function ")[0]
    assert tail.count("TASK_FLAGS.auto = false") >= 3, \
        "выбор ручного режима не снимает «Авто»"


def test_при_авто_отмечена_одна_карточка() -> None:
    """Раньше признак считался как «не субагенты и не разведка», и при
    «Авто» обычный режим тоже выглядел включённым: две галочки на одном
    невозможном выборе."""
    body = script()
    tail = body.partition("const cards = [")[2].partition("}.join")[0]
    assert "if (TASK_FLAGS.auto) return flag === 'auto';" in tail


# =============================================================== таймер пинга


def test_отсчёт_пинга_берётся_из_состояния() -> None:
    """Данные приходили только из события `ping_done`, и до первого пинга
    «следующая проверка через —» висело прочерком."""
    body = script()
    assert "if (S.ping)" in body, "состояние автопинга не читается"


def test_пустое_значение_обнуляет_счётчик() -> None:
    """Сервер отдаёт `next_in: null`, пока следующий пинг не запланирован.

    Сохранять прежнее значение нельзя: после одного пинга счётчик навсегда
    застревал на «0 с» и выглядел сломанным.
    """
    body = script()
    assert "PING.next_in = S.ping.next_in != null ? S.ping.next_in : null;" in body


def test_счётчик_уменьшается_при_свёрнутой_панели() -> None:
    """Раньше тик делал `return` до уменьшения: цифра замирала на том, что
    показал последний refresh, и отсчёт выглядел сломанным."""
    body = script()
    tick = body.partition("function tickPingCountdown(")[2]
    tick = tick.partition("\n}\n")[0]
    decrease = tick.index("PING.next_in = Math.max(0, PING.next_in - 1)")
    guard = tick.index("box.isConnected")
    assert decrease < guard, "счётчик уменьшается уже после проверки панели"


def test_идущий_пинг_не_показывает_ноль() -> None:
    body = script()
    assert "st.running ? 'идёт'" in body
    assert "'скоро'" in body, "до первого пинга показывать нечего"