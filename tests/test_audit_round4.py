"""Фаза 1 аудита: агент обязан отвечать и не перечитывать один файл.

Живой прогон 06.10.2026 (задачи 64 и 66) разложился на четыре причины
«сбоя» без единого слова по делу:

1. окно чтения не подсказывало `offset` — модель считала обрезку концом
   файла и перечитывала `hub/agent.py` шесть раз подряд;
2. один и тот же вызов не останавливал ни кто: шаги и токены горели впустую;
3. бюджет был предупреждением в события, а не стопом;
4. исчерпание шагов давало `finished=False` → «failed» без ответа.

Здесь проверяется, что каждая из четырёх закрыта, что отказ остаётся
честным (самодельный отчёт — не успех), и что обычный путь задачи без
проблем не изменился.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from hub.agent import (
    REPEAT_NUDGE,
    TOKEN_BUDGET_PER_STEP,
    Agent,
    AgentConfig,
    _content_brief,
    big_task_guide,
)
from hub.autonomy import AccessLevel, Autonomy, Guard
from hub.select import Selector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _Scripted:
    """Модель с заданными ответами и заданным расходом токенов."""

    def __init__(self, answers: list[str], tokens_out: int = 10) -> None:
        self.answers = list(answers)
        self.tokens_out = tokens_out
        self.calls: list[list[dict[str, Any]]] = []

    async def ask(self, messages, **kw: Any) -> dict[str, Any]:
        index = min(len(self.calls), len(self.answers) - 1)
        self.calls.append(list(messages))
        return {
            "ok": True,
            "text": self.answers[index],
            "model": "тест/модель",
            "duration_ms": 1,
            "status": "ok",
            "tokens_in": 0,
            "tokens_out": self.tokens_out,
        }


def make_agent(tmp_path: Path, answers: list[str], *, max_steps: int = 8,
               tokens_out: int = 10) -> tuple[Agent, _Scripted]:
    from hub.registry import Registry
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    selector = Selector(Registry(gateways=[], models=[]), TierBook({}))
    caller = _Scripted(answers, tokens_out=tokens_out)
    agent = Agent(selector, guard,
                  AgentConfig(max_steps=max_steps, base_dir=str(tmp_path)),
                  caller=caller)
    agent.set_task("Сделай что-нибудь")
    return agent, caller


def run_agent(agent: Agent) -> dict[str, Any]:
    return asyncio.run(agent.run())


def last_ask(caller: _Scripted, index: int = -1) -> str:
    """Всё, что модель увидела на одном вызове, одной строкой."""
    return " ".join(json.dumps(m, ensure_ascii=False)
                    for m in caller.calls[index])


# ======================================================= окно чтения


def test_окно_чтения_показывает_offset_для_продолжения() -> None:
    """Обрезка окна больше не выглядит концом файла.

    Раньше модель получала 4000 символов без объяснений и, не зная про
    `offset`, читала тот же файл заново — так горели шаги на живом прогоне.
    """
    line = "x" * 79
    content = "\n".join([line] * 101) + "\n"
    assert len(content) > 8000, "проверка должна обрезаться окном"

    brief = _content_brief({"content": content, "offset": 0, "lines": 500,
                            "truncated": True, "path": "a.py"})

    assert "offset=100" in brief, brief[-300:]
    assert "строки 1–100 из 500" in brief
    assert brief.startswith(content[:8000]), "содержимое порезано неверно"


def test_короткий_файл_отдаётся_без_лишних_подсказок() -> None:
    data = {"content": "привет\nмир\n", "offset": 0, "lines": 2,
            "truncated": False}
    assert _content_brief(data) == "привет\nмир\n"


def test_подсказка_когда_показано_всё_окно_но_файл_дальше() -> None:
    """Окно показано целиком, а файла ещё много: «осталось 0» врало бы."""
    data = {"content": "a\nb\n", "offset": 10, "lines": 50,
            "truncated": True}
    brief = _content_brief(data)

    assert "offset=12" in brief, brief
    assert "строки 11–12 из 50" in brief
    assert "осталось 0" not in brief


def test_модель_реально_получает_подсказку_о_offset(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text(
        ("\n".join(["z" * 79] * 500)) + "\n", encoding="utf-8")
    agent, caller = make_agent(tmp_path, [
        '{"tool": "read_file", "args": {"path": "big.txt"}}',
        "Готово.",
    ])
    run_agent(agent)

    seen = last_ask(caller, 1)
    assert "Результат read_file" in seen, seen[:300]
    assert "offset=" in seen, seen[:400]


# ======================================================= зацикливание


def test_один_и_тот_же_вызов_останавливается_а_не_жжёт_шаги(tmp_path: Path) -> None:
    """Пять одинаковых вызовов подряд — это цикл, а не упорство."""
    (tmp_path / "a.txt").write_text("содержимое", encoding="utf-8")
    call = '{"tool": "read_file", "args": {"path": "a.txt"}}'
    agent, caller = make_agent(tmp_path, [call], max_steps=10)

    result = run_agent(agent)

    reads = sum(1 for s in agent.steps if s.tool == "read_file")
    assert reads == REPEAT_NUDGE, \
        f"файл перечитан {reads} раз вместо {REPEAT_NUDGE}"
    # Отчёт собрали мы, а не ответила модель — значит, это не «сделано».
    assert result.get("ok") is not True, result
    assert "повторён" in result["last"], result["last"]
    assert "повторён" in (result.get("stopped_by") or "")
    # Нудж модели действительно уходил, а не просто считался в памяти.
    flat = " ".join(last_ask(caller, i) for i in range(2, 4))
    assert "Не повторяй его" in flat, flat[:400]


def test_счётчик_повторов_сбрасывается_после_записи(tmp_path: Path) -> None:
    """Чтение после правки — проверка, а не дубль."""
    (tmp_path / "a.txt").write_text("до", encoding="utf-8")
    agent, caller = make_agent(tmp_path, [
        '{"tool": "read_file", "args": {"path": "a.txt"}}',
        '{"tool": "edit_file", "args": {"path": "a.txt", "old": "до", "new": "после"}}',
        '{"tool": "read_file", "args": {"path": "a.txt"}}',
        "Проверил: текст заменён.",
    ])
    result = run_agent(agent)

    assert result.get("ok") is True, result
    reads = sum(1 for s in agent.steps if s.tool == "read_file")
    assert reads == 2, "проверка после записи посчиталась циклом"
    assert not [s for s in agent.steps if "уже выполнялся" in str(s.text)], \
        "чтение после правки получило нудж про зацикливание"


# ======================================================= бюджет


def test_бюджет_растёт_вместе_с_лимитом_шагов(tmp_path: Path) -> None:
    """Жёсткие 60 000 кончились на четвёртом чтении — это не бюджет."""
    agent, _ = make_agent(tmp_path, ["Готово"], max_steps=40)
    limit = agent._budget_limit()
    configured = AgentConfig().token_budget

    assert limit == max(configured, 40 * TOKEN_BUDGET_PER_STEP)
    assert limit > configured, "60 000 на 40 шагов — снова четвёртое чтение"


def test_ноль_бюджета_по_прежнему_значит_без_лимита(tmp_path: Path) -> None:
    from hub.registry import Registry
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    selector = Selector(Registry(gateways=[], models=[]), TierBook({}))
    agent = Agent(selector, guard,
                  AgentConfig(max_steps=40, base_dir=str(tmp_path),
                              token_budget=0),
                  caller=_Scripted(["Готово"]))

    assert agent._budget_limit() == 0


def test_исчерпанный_бюджет_требует_итог_а_не_читает_дальше(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("данные", encoding="utf-8")
    call = '{"tool": "read_file", "args": {"path": "a.txt"}}'
    agent, caller = make_agent(
        tmp_path,
        [call, "Итог: файл прочитан, данных достаточно."],
        max_steps=6, tokens_out=70_000,
    )

    result = run_agent(agent)

    assert result.get("ok") is True, result
    assert not [s for s in agent.steps if s.tool], \
        "инструмент выполнился при исчерпанном бюджете"
    assert "бюджет" in (result.get("stopped_by") or "")
    assert "итоговый ответ" in last_ask(caller, 1).lower(), last_ask(caller, 1)[:400]


def test_упряя_модель_при_бюджете_получает_отчёт_а_не_пустой_сбой(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("данные", encoding="utf-8")
    call = '{"tool": "read_file", "args": {"path": "a.txt"}}'
    agent, _ = make_agent(tmp_path, [call], max_steps=8, tokens_out=70_000)

    result = run_agent(agent)

    assert result.get("ok") is not True, "самодельный отчёт — не успех"
    assert result["last"], "задача умерла без ответа"
    assert "Работа остановлена" in result["last"], result["last"]
    assert "бюджет" in (result.get("stopped_by") or "")


# ======================================================= лимит шагов


def test_лимит_шагов_даёт_итоговый_ответ_а_не_сбой(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("а", encoding="utf-8")
    (tmp_path / "b.txt").write_text("б", encoding="utf-8")
    agent, _ = make_agent(tmp_path, [
        '{"tool": "read_file", "args": {"path": "a.txt"}}',
        '{"tool": "read_file", "args": {"path": "b.txt"}}',
        "Итог: прочитал оба файла.",
    ], max_steps=2)

    result = run_agent(agent)

    assert result.get("ok") is True, result
    assert "Итог" in result["last"], result["last"]
    assert (result.get("stopped_by") or "").startswith("лимит шагов")


def test_лимит_шагов_с_продолжением_вызовов_даёт_отчёт(tmp_path: Path) -> None:
    """Модель снова зовёт инструмент — отчёт собираем сами, но без пустоты."""
    (tmp_path / "a.txt").write_text("а", encoding="utf-8")
    agent, _ = make_agent(tmp_path, [
        '{"tool": "read_file", "args": {"path": "a.txt"}}',
    ], max_steps=1)

    result = run_agent(agent)

    assert result.get("ok") is not True, "работа не подтверждена моделью"
    assert result["last"], "задача умерла без ответа"
    assert "Работа остановлена" in result["last"], result["last"]
    assert "лимит шагов" in (result.get("stopped_by") or "")


# ================================================= встроенный промт


def test_инструкция_большой_задачи_включается_для_обхода() -> None:
    guide = big_task_guide("Сделай аудит всего проекта zagent")

    assert "ПОРЯДОК РАБОТЫ" in guide
    assert "offset" in guide
    assert "search_text" in guide


def test_обычная_задача_не_платит_за_чужую_инструкцию() -> None:
    assert big_task_guide("переименуй переменную total в count") == ""
    assert big_task_guide("прочитай файл notes.txt") == ""
    assert big_task_guide("") == ""


def test_инструкция_живёт_в_системном_промпте(tmp_path: Path) -> None:
    agent, _ = make_agent(tmp_path, ["Готово"])

    agent.set_task("сделай аудит всего проекта")
    assert "БОЛЬШАЯ ЗАДАЧА" in agent.messages[0]["content"]

    agent.rebuild_system_prompt()
    assert "БОЛЬШАЯ ЗАДАЧА" in agent.messages[0]["content"]

    agent.set_task("скажи привет")
    assert "БОЛЬШАЯ ЗАДАЧА" not in agent.messages[0]["content"]


# ======================================================= сброс и обычный путь


def test_стопы_прошлой_задачи_не_стопят_новую(tmp_path: Path) -> None:
    agent, _ = make_agent(tmp_path, ["Готово"])
    agent.repeat_counts = {"read_file:a.txt": 99}
    agent.wrap_up = 5
    agent.budget_exceeded = True
    agent.stop_reason = "бюджет задачи исчерпан"

    agent._reset_cycle()

    assert agent.repeat_counts == {}
    assert agent.wrap_up == 0
    assert agent.budget_exceeded is False
    assert agent.stop_reason == ""


def test_обычная_задача_без_проблем_идёт_как_раньше(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("привет", encoding="utf-8")
    agent, _ = make_agent(tmp_path, [
        '{"tool": "read_file", "args": {"path": "a.txt"}}',
        "Готово, файл прочитан.",
    ])

    result = run_agent(agent)

    assert result.get("ok") is True, result
    assert result.get("stopped_by") == "", "остановка там, где её не было"
    assert sum(1 for s in agent.steps if s.tool == "read_file") == 1
