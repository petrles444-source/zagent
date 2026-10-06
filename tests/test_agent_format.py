"""Нераспарсенный вызов инструмента больше не превращается в успех.

`parse_tool_calls` возвращал `[]` для всего, что не строгий JSON: одинарные
кавычки, питоновский словарь, висячая запятая. `_one_step` считал отсутствие
вызовов ответом словами, писал `done` и завершал задачу с `ok: True` — при том
что не был прочитан ни один файл.

Худший из исходов: тихий ложный успех. По журналу всё выглядит сделанным.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from hub.agent import (
    FORMAT_NUDGE_LIMIT,
    Agent,
    AgentConfig,
    _parse_calls,
    _single_to_double_quotes,
    looks_like_tool_call,
    parse_tool_calls,
)
from hub.autonomy import AccessLevel, Autonomy, Guard
from hub.select import Selector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# =============================================================== разбор


def test_строгий_json_разбирается() -> None:
    calls = parse_tool_calls('{"tool": "read_file", "args": {"path": "a.py"}}')
    assert calls == [{"tool": "read_file", "args": {"path": "a.py"}}]


def test_питоновский_словарь_разбирается() -> None:
    """Самая частая поломка: одинарные кавычки вместо JSON-кавычек."""
    calls = parse_tool_calls(
        "Сейчас прочитаю: {'tool': 'read_file', 'args': {'path': 'x.py'}}"
    )
    assert calls == [{"tool": "read_file", "args": {"path": "x.py"}}]


def test_висячая_запятая_лечится() -> None:
    calls = parse_tool_calls(
        '{"tool": "list_dir", "args": {"path": "src",},}'
    )
    assert calls and calls[0]["tool"] == "list_dir"


def test_true_false_в_python_литерале() -> None:
    """В JSON это true/false, в Python — True/False; ast ест оба."""
    calls = parse_tool_calls(
        "{'tool': 'write_file', 'args': {'path': 'a', 'text': 'b', 'flag': True}}"
    )
    assert calls and calls[0]["args"]["flag"] is True


def test_испорченный_формат_помечается() -> None:
    """Главное: поломка обязана быть видна, а не выглядеть как «нет вызовов»."""
    calls, broken = _parse_calls('{"tool": "read_file", "args": {,},}')
    assert calls == []
    assert broken, "испорченный фрагмент не замечен"


def test_нормальный_ответ_не_считается_поломкой() -> None:
    calls, broken = _parse_calls("Готово, всё сделал.")
    assert calls == [] and broken == [], "обычный текст не должен попадать в broken"


def test_текст_с_json_но_не_вызовом_не_поломка() -> None:
    """Словарик без ключа tool — просто словарик, а не испорченный вызов."""
    calls, broken = _parse_calls('{"name": "ivan", "age": 30}')
    assert calls == [] and broken == []


def test_похоже_на_вызов_без_json() -> None:
    assert looks_like_tool_call("{'tool': 'read_file'}")
    assert looks_like_tool_call('"tool": "read_file"')
    assert not looks_like_tool_call("Сделаю всё сам, без инструментов")
    assert not looks_like_tool_call("")


def test_кавычки_в_содержимом_не_портятся() -> None:
    """Апостроф внутри строки — часть текста, а не граница."""
    raw = """{'tool': 'write_file', 'args': {'path': 'a', 'text': "it's fine"}}"""
    calls = parse_tool_calls(raw)
    assert calls and calls[0]["args"]["text"] == "it's fine"


def test_экранированный_апостроф_становится_обычным() -> None:
    """Внутри двойных кавычек апостроф экранировать не нужно."""
    assert _single_to_double_quotes("{'a': 'don\\'t'}") == '{"a": "don\'t"}'.replace("\\'", "'")


def test_двойная_кавычка_в_одинарной_строке_экранируется() -> None:
    assert _single_to_double_quotes("{'a': 'say \"hi\"'}") == '{"a": "say \\"hi\\""}'


def test_замена_кавычек_даёт_разбираемый_json() -> None:
    import json

    out = _single_to_double_quotes("{'a': 'don\\'t', 'b': 'x'}")
    assert json.loads(out) == {"a": "don't", "b": "x"}


# =============================================================== агент


class _Scripted:
    """Модель, выдающая заранее заданные ответы по порядку."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[list[dict[str, Any]]] = []

    async def ask(self, messages, **kw: Any) -> dict[str, Any]:
        index = min(len(self.calls), len(self.answers) - 1)
        self.calls.append(list(messages))
        text = self.answers[index]
        return {"ok": True, "text": text, "model": "тест/модель",
                "duration_ms": 1, "status": "ok"}


def make_agent(tmp_path: Path, answers: list[str]):
    from hub.registry import Registry
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    selector = Selector(Registry(gateways=[], models=[]), TierBook({}))
    caller = _Scripted(answers)
    agent = Agent(selector, guard,
                  AgentConfig(max_steps=8, base_dir=str(tmp_path)),
                  caller=caller)
    agent.set_task("Сделай что-нибудь")
    return agent, caller


def run_agent(agent: Agent) -> dict[str, Any]:
    return asyncio.run(agent.run())


def test_поломка_формата_не_завершает_задачу_успехом(tmp_path: Path) -> None:
    """Самый важный тест: ложный успех больше невозможен."""
    agent, _ = make_agent(tmp_path, ["{'tool': 'read_file', 'args': }"])
    result = run_agent(agent)
    assert result.get("ok") is not True, f"задача объявлена успешной: {result}"
    # И в журнале должен быть след требования формата, а не «готово».
    texts = " ".join(str(s.text) for s in agent.steps).lower()
    assert "формат" in texts or "неверн" in texts, texts[:300]


def test_после_требования_формата_вызов_выполняется(tmp_path: Path) -> None:
    """Второй ответ корректный — и работа делается, а не «успех»."""
    (tmp_path / "файл.txt").write_text("данные", encoding="utf-8")
    agent, caller = make_agent(tmp_path, [
        "{'tool': 'read_file', 'args': }",           # поломка
        '{"tool": "read_file", "args": {"path": "файл.txt"}}',  # исправление
        "Готово, файл прочитан.",
    ])
    result = run_agent(agent)
    assert result.get("ok") is True, result
    # Модель получила требование формата.
    flat = " ".join(json.dumps(m, ensure_ascii=False) for m in caller.calls[1])
    assert "Только JSON" in flat or "повтори" in flat.lower(), flat[:400]


def test_формат_не_крутится_бесконечно(tmp_path: Path) -> None:
    """Модель не поняла — останавливаемся, а не жжём лимит шагов."""
    agent, _ = make_agent(tmp_path, ["{'tool': 'read_file', 'args': }"])
    result = run_agent(agent)
    assert result.get("ok") is not True
    assert agent.format_retries <= FORMAT_NUDGE_LIMIT + 1
    assert len(agent.steps) <= FORMAT_NUDGE_LIMIT + 3, len(agent.steps)


def test_обычный_ответ_завершает_задачу(tmp_path: Path) -> None:
    """Исправление не должно ломать обычный путь: слова без JSON — это финал."""
    agent, _ = make_agent(tmp_path, ["Всё сделано, файлы в папке src."])
    result = run_agent(agent)
    assert result.get("ok") is True, result
    assert agent.format_retries == 0


def test_счётчик_сбрасывается_между_задачами(tmp_path: Path) -> None:
    agent, _ = make_agent(tmp_path, ["{'tool': 'x', 'args': }"])
    agent.format_retries = FORMAT_NUDGE_LIMIT + 1
    agent._reset_cycle()
    assert agent.format_retries == 0