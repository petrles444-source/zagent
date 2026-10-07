"""Размышление не считается ответом.

Живой прогон 07.10.2026, задача «сделай аудит всего кода»: reasoning-модель
одиннадцать раз перебрала папки, на двенадцатом шаге отдала вслух план —
«We need to audit the code… Let's search for TODO or FIXME» — и цикл счёл
это финальным ответом. Задача получила статус «готово», `ok=True`, ноль
созданных файлов.

Это худший из исходов, потому что невидим: по журналу всё выглядит
сделанным. Критерий пользователя — «файл появился = работа сделана» — был
нарушен, и ничто в интерфейсе об этом не говорило.

Проверяется, что:
* размышление без ответа не завершает задачу успехом;
* одно требование ответа даёт модели chance ответить нормально;
* модель, правда держущая текст в поле размышления, после требования
  получает его и задача завершается;
* требование не превращается в бесконечный круг.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from hub.agent import SILENT_NUDGE_LIMIT, Agent, AgentConfig
from hub.autonomy import AccessLevel, Autonomy, Guard
from hub.selector import Selector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class _OnlyReasoning:
    """Модель, которая всегда говорит только в поле reasoning."""

    def __init__(self, reasoning: str, answer: str = "") -> None:
        self.reasoning = reasoning
        self.answer = answer
        self.calls = 0

    async def ask(self, messages, **kw: Any) -> dict[str, Any]:
        self.calls += 1
        # Первый раз — только размышление. Дальше — ответ, если он задан.
        if self.calls == 1 or not self.answer:
            return {"ok": True, "text": "", "reasoning": self.reasoning,
                    "model": "т/размышляющая", "duration_ms": 1, "status": "ok"}
        return {"ok": True, "text": self.answer, "reasoning": "",
                "model": "т/размышляющая", "duration_ms": 1, "status": "ok"}


def make_agent(tmp_path: Path, caller: Any, max_steps: int = 5) -> Agent:
    from hub.registry import Registry
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    selector = Selector(Registry(gateways=[], models=[]), TierBook({}))
    agent = Agent(selector, guard,
                  AgentConfig(max_steps=max_steps, base_dir=str(tmp_path)),
                  caller=caller)
    agent.set_task("Сделай аудит всего кода проекта")
    return agent


PLAN = ("We need to audit the code: find bugs. We have many files. "
        "Given time, we can search for obvious issues. "
        "Let's search for TODO or FIXME.")


# ============================================ главное: ложный успех невозможен


def test_размышление_не_завершает_задачу_успехом(tmp_path: Path) -> None:
    """Ровно тот случай, что случился в живом прогоне.

    Планирование вслух — это не ответ. Принимать его за ответ значит
    объявить задачу выполненной, не прочитав ни одного файла.
    """
    agent = make_agent(tmp_path, _OnlyReasoning(PLAN))

    result = asyncio.run(agent.run())

    assert result.get("ok") is not True, (
        f"размышление принято за ответ: {result.get('last')!r}"
    )
    assert agent.artifacts == [], "создано что-то при отсутствии работы"
    # И в журнале должен быть след требования ответа, а не «готово».
    flat = " ".join(str(s.text) for s in agent.steps)
    assert "размышл" in flat.lower(), flat[:300]


def test_модель_которая_думает_молча_не_даёт_готово(tmp_path: Path) -> None:
    """Планирование без ответа и без единого вызова инструмента."""
    agent = make_agent(tmp_path, _OnlyReasoning(
        "Сначала посмотрю структуру проекта, потом решу, с чего начать."))

    result = asyncio.run(agent.run())

    assert result.get("ok") is not True, "тишина вслед за планом стала успехом"


def test_агент_потребовал_ответ_а_не_просто_остановился(tmp_path: Path) -> None:
    """Требование должно уйти в диалог, иначе модель не сможет ответить."""
    caller = _OnlyReasoning(PLAN)
    agent = make_agent(tmp_path, caller)

    asyncio.run(agent.run())

    seen = " ".join(
        str(m.get("content")) for m in agent.messages
        if m.get("role") == "user")
    assert "Размышление не считается ответом" in seen, seen[-400:]


# ============================================ модель всё-таки ответила


def test_ответ_после_требования_принимается(tmp_path: Path) -> None:
    """Часть моделей правда держит ответ в поле размышления.

    Если она после требования его повторит — задача должна завершиться
    честно, с текстом. Иначе починка обошла бы половину моделей.
    """
    caller = _OnlyReasoning(PLAN, answer="Аудит сделан, отчёт в docs/audit.md.")
    agent = make_agent(tmp_path, caller)

    result = asyncio.run(agent.run())

    assert result.get("ok") is True, result
    assert result["last"] == "Аудит сделан, отчёт в docs/audit.md."
    assert caller.calls == 2, "ответ не потребовали"


# ==================================================== без бесконечного круга


def test_требований_не_больше_лимита(tmp_path: Path) -> None:
    """Молчание не должно крутить цикл до конца шагов."""
    caller = _OnlyReasoning(PLAN)
    agent = make_agent(tmp_path, caller)

    asyncio.run(agent.run())

    nudges = [s for s in agent.steps
              if "размышление не считается" in str(s.text).lower()]
    assert len(nudges) == SILENT_NUDGE_LIMIT, (
        f"требований {len(nudges)}, ожидалось {SILENT_NUDGE_LIMIT}"
    )
    assert len(agent.steps) <= SILENT_NUDGE_LIMIT + 3, len(agent.steps)


def test_счётчик_сбрасывается_между_задачами(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, _OnlyReasoning(PLAN))
    agent.silent_replies = 99

    agent._reset_cycle()

    assert agent.silent_replies == 0


# ============================================= обычный путь не сломан


def test_обычный_ответ_по_прежнему_работает(tmp_path: Path) -> None:
    """Починка не должна трогать нормальный путь."""

    class _Plain:
        def __init__(self) -> None:
            self.calls = 0

        async def ask(self, messages, **kw: Any) -> dict[str, Any]:
            self.calls += 1
            return {"ok": True, "text": "Всё проверено, замечаний нет.",
                    "reasoning": "", "model": "т/обычная",
                    "duration_ms": 1, "status": "ok"}

    agent = make_agent(tmp_path, _Plain())

    result = asyncio.run(agent.run())

    assert result.get("ok") is True, result
    assert agent.silent_replies == 0