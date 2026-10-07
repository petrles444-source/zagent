"""Названный в задаче результат обязан лежать на диске.

Живой прогон 07.10.2026, задача «напиши отчёт в файл docs/audit-live.md»:
агент составил развёрнутый отчёт и выдал его **текстом в переписке**.
`write_file` не вызывался ни разу, задача получила статус «готово» с
`ok=True`, а файла не существовало.

По критерию пользователя — «файл появился = работа сделана, пустой файл — не
работа» — это провал, который был виден как успех. Ничто механическое его не
ловило: журнал показывал двадцать шагов и заключение.

Проверяется, что:
* файл, который задача просит создать, требуется на диске;
* требование не срабатывает там, где создавать нечего;
* одно напоминание достаточно: у модели отчёт уже есть в истории;
* повтор без результата даёт честный отказ, а не «готово».
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from hub.agent import (
    DELIVERABLE_NUDGE_LIMIT,
    Agent,
    AgentConfig,
    required_deliverables,
)
from hub.autonomy import AccessLevel, Autonomy, Guard
from hub.selector import Selector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ======================================== что считается требуемым результатом


def test_отчёт_в_файл_требуется(tmp_path: Path) -> None:
    got = required_deliverables(
        "Напиши отчёт в файл docs/audit-live.md: по каждой находке файл, строка.",
        tmp_path,
    )
    assert got == ["docs/audit-live.md"], got


def test_файл_который_уже_есть_не_требуется(tmp_path: Path) -> None:
    """«Исправь в файле X» — файл уже есть, создавать нечего."""
    (tmp_path / "hub").mkdir()
    (tmp_path / "hub" / "agent.py").write_text("x = 1\n", encoding="utf-8")

    got = required_deliverables("исправь баг в файле hub/agent.py", tmp_path)

    assert got == [], got


def test_чтение_не_принимается_за_создание(tmp_path: Path) -> None:
    """«Прочитай README.md» создавать ничего не просит."""
    got = required_deliverables(
        "прочитай README.md и перескажи содержимое", tmp_path)
    assert got == [], got


def test_сравнение_файлов_ничего_не_требует(tmp_path: Path) -> None:
    """«Сравни a.py и b.py»: ни одного слова записи, значит и требования нет."""
    got = required_deliverables("сравни файлы a.py и b.py, скажи разницу", tmp_path)
    assert got == [], got


def test_просто_вопрос_ничего_не_требует(tmp_path: Path) -> None:
    got = required_deliverables("посчитай 2+2 и напиши результат", tmp_path)
    assert got == [], got


def test_таблица_в_csv_требуется(tmp_path: Path) -> None:
    got = required_deliverables("сохрани таблицу в data.csv", tmp_path)
    assert got == ["data.csv"], got


def test_пустой_файл_не_считается_сделанным(tmp_path: Path) -> None:
    """Пустой файл — не работа, как и его отсутствие."""
    target = tmp_path / "docs"
    target.mkdir()
    (target / "out.md").write_text("", encoding="utf-8")

    got = required_deliverables("напиши отчёт в файл docs/out.md", tmp_path)

    assert got == ["docs/out.md"], got


# ================================================= агент обязан файл создать


class _Scripted:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def ask(self, messages, **kw: Any) -> dict[str, Any]:
        index = min(self.calls, len(self.answers) - 1)
        self.calls += 1
        return {"ok": True, "text": self.answers[index], "reasoning": "",
                "model": "т/модель", "duration_ms": 1, "status": "ok"}


def make_agent(tmp_path: Path, answers: list[str], task: str,
               max_steps: int = 6) -> tuple[Agent, _Scripted]:
    from hub.registry import Registry
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    selector = Selector(Registry(gateways=[], models=[]), TierBook({}))
    caller = _Scripted(answers)
    agent = Agent(selector, guard,
                  AgentConfig(max_steps=max_steps, base_dir=str(tmp_path)),
                  caller=caller)
    agent.set_task(task)
    return agent, caller


TASK = "Сделай аудит кода и напиши отчёт в файл docs/report.md"


def test_ответ_без_файла_не_считается_готовым(tmp_path: Path) -> None:
    """Ровно то, что случилось в прогоне: отчёт есть в тексте, файла нет."""
    (tmp_path / "docs").mkdir()
    agent, _ = make_agent(tmp_path, [
        "Готово. Отчёт:\n\n## Найдено\n- баг в hub/agent.py",
    ], TASK)

    result = asyncio.run(agent.run())

    assert result.get("ok") is not True, (
        f"объявлено готово без файла: {str(result.get('last'))[:200]!r}"
    )
    assert not (tmp_path / "docs" / "report.md").exists()


def test_агенту_напомнили_про_отсутствующий_файл(tmp_path: Path) -> None:
    """Напоминание обязано дойти до модели, иначе ей нечего исправлять."""
    (tmp_path / "docs").mkdir()
    agent, caller = make_agent(tmp_path, [
        "Готово. Отчёт: всё хорошо.",
    ], TASK)

    asyncio.run(agent.run())

    seen = " ".join(str(m.get("content")) for m in agent.messages
                    if m.get("role") == "user")
    assert "docs/report.md" in seen, seen[-400:]
    assert "write_file" in seen, "не сказано, чем создать файл"
    assert caller.calls == 2, "модели не дали шанса создать файл"


def test_файл_создан_после_напоминания_задача_завершается(tmp_path: Path) -> None:
    """Модель записала файл — работа сдана, ложного отказа быть не должно."""
    (tmp_path / "docs").mkdir()

    class _Writing(_Scripted):
        async def ask(self, messages, **kw: Any) -> dict[str, Any]:
            out = await super().ask(messages, **kw)
            # Реагируем только на требование создать файл.
            if any("docs/report.md" in str(m.get("content"))
                   for m in messages if m.get("role") == "user"):
                docs = tmp_path / "docs"
                docs.mkdir(exist_ok=True)
                (docs / "report.md").write_text(
                    "## Отчёт\n- баг найден\n", encoding="utf-8")
            return out

    caller = _Writing([
        "Готово. Отчёт: всё хорошо.",
        "Отчёт записан в docs/report.md.",
    ])
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    from hub.registry import Registry
    from hub.tiers import TierBook

    agent = Agent(Selector(Registry(gateways=[], models=[]), TierBook({})), guard,
                  AgentConfig(max_steps=6, base_dir=str(tmp_path)),
                  caller=caller)
    agent.set_task(TASK)

    result = asyncio.run(agent.run())

    assert (tmp_path / "docs" / "report.md").exists()
    assert result.get("ok") is True, result


def test_напоминаний_не_больше_лимита(tmp_path: Path) -> None:
    """Модель, которая игнорирует требование, не должна крутить цикл."""
    (tmp_path / "docs").mkdir()
    agent, _ = make_agent(tmp_path, ["Готово, отчёт выше."], TASK)

    asyncio.run(agent.run())

    nudges = [s for s in agent.steps if "write_file" in str(s.text)]
    assert len(nudges) == DELIVERABLE_NUDGE_LIMIT, (
        f"напоминаний {len(nudges)}, ожидалось {DELIVERABLE_NUDGE_LIMIT}"
    )


def test_задача_без_файла_по_прежнему_завершается_успехом(tmp_path: Path) -> None:
    """Починка не должна ломать обычную задачу без требуемых файлов."""
    agent, _ = make_agent(tmp_path, ["Проверил: всё в порядке."],
                          "Проверь, что в проекте нет ошибок")

    result = asyncio.run(agent.run())

    assert result.get("ok") is True, result


def test_счётчик_напоминаний_сбрасывается_между_задачами(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    agent, _ = make_agent(tmp_path, ["Готово."], TASK)
    agent.deliverable_repeats = 99

    agent._reset_cycle()

    assert agent.deliverable_repeats == 0