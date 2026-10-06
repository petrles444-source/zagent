"""Проверка записанного файла не должна ругаться на рабочие файлы.

Три поломки, которые выглядели как «агент всё сломал», а на деле ничего
сломано не было:

* BOM в начале файла — метка кодировки, а не содержимое. ast.parse и json
  считают её синтаксической ошибкой, и агент получал задание «исправь» для
  совершенно нормального файла.
* Список проверок не сбрасывался между шагами: одна плохая запись на шаге 4
  портила каждый следующий шаг, даже если файл давно починен.
* Пустое место в списке аргументов инструмента роняло весь прогон.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from hub.agent import BOM, Agent, AgentConfig, verify_file

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# =============================================================== 1.7 BOM


def test_bom_в_python_не_считается_ошибкой(tmp_path: Path) -> None:
    target = tmp_path / "скрипт.py"
    target.write_text(BOM + "print('привет')\n", encoding="utf-8")
    result = verify_file(target)
    assert result["ok"] is True, result["detail"]


def test_bom_в_json_не_считается_ошибкой(tmp_path: Path) -> None:
    target = tmp_path / "данные.json"
    target.write_text(BOM + '{"a": 1}', encoding="utf-8")
    result = verify_file(target)
    assert result["ok"] is True, result["detail"]


def test_настоящая_ошибка_попрежнему_ловится(tmp_path: Path) -> None:
    """BOM не должен отключать проверку: сломанный файл обязан ломаться."""
    target = tmp_path / "сломанный.py"
    target.write_text(BOM + "def f(:\n", encoding="utf-8")
    result = verify_file(target)
    assert result["ok"] is False
    assert "синтаксическая ошибка" in result["detail"]


def test_bom_в_середине_кода_остаётся_ошибкой(tmp_path: Path) -> None:
    """BOM посередине — это уже содержимое, и снимать его нельзя.

    Метку снимает только в начале файла. Внутри кода U+FEFF — посторонний
    символ, и ast.parse правомерно на него ругается.
    """
    target = tmp_path / "середина.py"
    target.write_text("x = 1\n" + BOM + "y = 2\n", encoding="utf-8")
    result = verify_file(target)
    assert result["ok"] is False, "BOM в середине кода не метка, а ошибка"


def test_json_с_bom_читается(tmp_path: Path) -> None:
    target = tmp_path / "конфиг.json"
    target.write_text(BOM + '{"ключ": "значение"}', encoding="utf-8")
    assert verify_file(target)["ok"] is True


# =============================================================== прочее


def test_пустой_файл_ловится(tmp_path: Path) -> None:
    target = tmp_path / "пустой.py"
    target.write_text("", encoding="utf-8")
    assert verify_file(target)["ok"] is False


def test_несуществующий_файл(tmp_path: Path) -> None:
    assert verify_file(tmp_path / "нет.py")["ok"] is False


# =============================================================== 1.6 verifications


class _Scripted:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[Any] = []

    async def ask(self, messages, **kw: Any) -> dict[str, Any]:
        index = min(len(self.calls), len(self.answers) - 1)
        self.calls.append(messages)
        return {"ok": True, "text": self.answers[index],
                "model": "тест/модель", "duration_ms": 1, "status": "ok"}


def make_agent(tmp_path: Path, answers: list[str], *, verify_writes: bool = True):
    from hub.registry import Registry
    from hub.select import Selector
    from hub.tiers import TierBook

    from hub.autonomy import AccessLevel, Autonomy, Guard

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    selector = Selector(Registry(gateways=[], models=[]), TierBook({}))
    agent = Agent(selector, guard,
                  AgentConfig(max_steps=10, base_dir=str(tmp_path),
                              verify_writes=verify_writes),
                  caller=_Scripted(answers))
    agent.set_task("задача")
    return agent


def test_плохая_проверка_не_портит_следующие_шаги(tmp_path: Path) -> None:
    """Главное: одна плохая запись не должна ломать всю задачу.

    Проверки копятся в `self.verifications` и `_reset_cycle` их не сбрасывал,
    поэтому запись с ошибкой в шаге 4 делала каждый следующий шаг с
    инструментом «провалом проверки» — даже когда файл давно починен.
    """
    (tmp_path / "плохой.py").write_text("def f(:\n", encoding="utf-8")
    agent = make_agent(tmp_path, ["готов", "готов"])
    agent.verifications = [{"path": "плохой.py", "ok": False, "detail": "старый"}]
    agent._reset_cycle()
    assert agent.verifications == [], "проверки прошлого цикла остались в списке"


def test_проверки_собираются_заново(tmp_path: Path) -> None:
    agent = make_agent(tmp_path, ["готов"])
    agent.verifications = [{"path": "a.py", "ok": True, "detail": ""}]
    agent._reset_cycle()
    assert agent.verifications == []


# =============================================================== 1.8 лишний аргумент


def test_лишний_аргумент_не_роняет_прогон(tmp_path: Path) -> None:
    """Неизвестный ключ в args должен дать ошибку инструмента, а не агента."""
    from hub.autonomy import AccessLevel, Autonomy, Guard
    from hub.tools import run_tool

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    res = run_tool("read_file", guard, path="нет.py", выдуманный=1)
    assert res.ok is False
    assert "Неверные аргументы" in res.error or "не найден" in res.error.lower()


def test_агент_переживает_ошибку_инструмента(tmp_path: Path) -> None:
    """Шаг с ошибкой инструмента не должен ронять весь цикл."""
    from hub.autonomy import AccessLevel, Autonomy, Guard

    answers = [
        json.dumps({"tool": "read_file", "args": {"path": "нет-такого.py"}}),
        "Готово, такого файла нет.",
    ]
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    agent = make_agent(tmp_path, answers)
    agent.guard = guard
    result = asyncio.run(agent.run())
    assert result.get("ok") is True, result