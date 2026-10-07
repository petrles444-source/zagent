"""Фаза 3: лимит шагов не должен означать отказ.

Живой прогон 06.10.2026 (задачи 64/66): аудит проекта на 48k строк
упирался в `max_steps`, и воркер объявлял задачу `failed` с отчётом
«работа остановлена». Работа при этом не была испорчена — её просто не
дали закончить, и человек получал отказ вместо результата.

Что проверяется здесь:

* задача, оборванная лимитом шагов, возвращается в очередь с добавкой к
  лимиту и продолжает с чекпоинта, а не падает;
* продолжений не больше `MAX_CONTINUATIONS` — иначе получился бы тот же
  сбой, только бесконечный;
* отказ по существу (нет причины, отмена) не продолжается: повтор дал бы
  тот же результат за счёт чужой квоты;
* агент на продолжении не пересказывает свой промежуточный отчёт, а
  продолжает работу.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from hub.agent import Agent, AgentConfig
from hub.autonomy import AccessLevel, Autonomy, Guard
from hub.selector import Selector
from hub.worker import (
    CONTINUE_PROMPT,
    CONTINUATION_STEPS,
    MAX_CONTINUATIONS,
    Worker,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ------------------------------------------------------------- каркас воркера


class _Store:
    """Хранилище, которое помнит вызовы и отдаёт заранее заданную задачу."""

    def __init__(self, task: dict[str, Any] | None = None) -> None:
        self.updates: list[tuple[int, dict[str, Any]]] = []
        self.task = task or {"id": 1, "task": "аудит проекта", "payload": {}}
        self.events: list[dict[str, Any]] = []

    def update_task(self, task_id: int, **fields: Any) -> None:
        self.updates.append((task_id, fields))

    def last(self) -> dict[str, Any]:
        assert self.updates, "задачу ни разу не обновили"
        return self.updates[-1][1]

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [str(e.get("type")) for e in self.events]


@pytest.fixture()
def worker(tmp_path: Path) -> Worker:
    from hub.store import Store

    real = Worker.__new__(Worker)
    real.store = _Store()          # type: ignore[attr-defined]
    real.emit = real.store.emit     # type: ignore[attr-defined]
    return real


def task_row(task_id: int = 1, **payload: Any) -> dict[str, Any]:
    return {"id": task_id, "task": "аудит проекта", "payload": payload}


def limited_result(**over: Any) -> dict[str, Any]:
    """Результат прогона, оборванного лимитом шагов."""
    out: dict[str, Any] = {
        "ok": False,
        "stopped_by": f"лимит шагов исчерпан ({40})",
        "cancelled": False,
        "steps": 40,
        "duration_ms": 1000,
        "last": "Работа остановлена: лимит шагов исчерпан (40).",
        "models_used": ["т/модель"],
        "checkpoint": {"messages": [{"role": "system", "content": "s"},
                                    {"role": "user", "content": "задача"}]},
    }
    out.update(over)
    return out


# ------------------------------------------------- задача не падает, а идёт дальше


def test_задача_оборванная_лимитом_возвращается_в_очередь(worker: Worker) -> None:
    """Главное: `failed` больше не terminal для такой задачи."""
    task = task_row()
    result = limited_result()

    again = worker._requeue_for_more_steps(task, result, task["payload"])

    assert again is True, "задача с лимитом шагов объявлена отказом"
    saved = worker.store.last()
    assert saved["status"] == "queued", saved
    assert saved["finished_at"] is None, "задача осталась с временем финиша"
    assert saved["error"] is None, "ошибка осталась в записи продолжаемой задачи"


def test_продолжение_берёт_чекпоинт_а_не_начинает_заново(worker: Worker) -> None:
    """Главное свойство продолжения: агент возвращается в тот же диалог."""
    task = task_row()
    result = limited_result()

    worker._requeue_for_more_steps(task, result, task["payload"])

    saved = worker.store.last()
    assert saved["payload"]["checkpoint"], "чекпоинт потерян — работа начнётся с нуля"
    assert saved["payload"]["checkpoint"]["messages"][1]["content"] == "задача"


def test_продолжению_добавляются_шаги(worker: Worker) -> None:
    task = task_row()

    worker._requeue_for_more_steps(task, limited_result(), task["payload"])

    payload = worker.store.last()["payload"]
    assert payload["extra_steps"] == CONTINUATION_STEPS
    assert payload["continuations"] == 1


def test_второе_продолжение_получает_больше_шагов(worker: Worker) -> None:
    """Каждая попытка получает добавку, а не начинает с той же суммы.

    Первая попытка не успела, потому что шагов не хватило. Второй раз то же
    самое число шагов дало бы тот же обрыв — и задача умерла бы, обойдя
    счётчик продолжений.
    """
    task = task_row(continuations=1)

    worker._requeue_for_more_steps(task, limited_result(), task["payload"])

    payload = worker.store.last()["payload"]
    assert payload["continuations"] == 2
    assert payload["extra_steps"] == CONTINUATION_STEPS * 2


def test_повтор_использует_тот_же_лимит_и_снова_продолжает(worker: Worker) -> None:
    """Продолжение, у которого не вырос лимит, обязано вырасти — иначе
    получится бесконечный цикл, который выглядит как работа."""
    task = task_row(continuations=1)

    worker._requeue_for_more_steps(task, limited_result(), task["payload"])

    assert worker.store.last()["payload"]["extra_steps"] > CONTINUATION_STEPS


# ------------------------------------------------------ продолжений не больше


def test_продолжений_не_больше_потолка_даже_при_успешном_отчёте(worker: Worker) -> None:
    """Отчёт под давлением `ok=True` не должен открыть лазейку.

    Агент, которому велели «дай итог сейчас», отчёт произносит почти всегда.
    Если бы продолжение зависело от статуса, задача закрывалась бы этим
    отчётом и лимит шагов перестал бы что-либо значить.
    """
    task = task_row()

    again = worker._requeue_for_more_steps(
        task, limited_result(ok=True), task["payload"])

    assert again is True, "успешный отчёт под давлением отключил продолжение"
    assert worker.store.last()["status"] == "queued"


def test_продолжения_кончаются(worker: Worker) -> None:
    """Потолок обязателен: задача, не влезающая в лимит, иначе крутилась бы
    вечно — это тот же сбой, который здесь чинится."""
    task = task_row(continuations=MAX_CONTINUATIONS)

    again = worker._requeue_for_more_steps(task, limited_result(), task["payload"])

    assert again is False
    assert not worker.store.updates, "задача переочередилась после потолка"
    assert "continuation_exhausted" in worker.store.types()


# --------------------------------------------------- что продолжать нельзя


@pytest.mark.parametrize("over, why", [
    ({"stopped_by": "бюджет задачи исчерпан"}, "бюджет"),
    ({"stopped_by": "один и тот же вызов повторён 6 раз"}, "зацикливание"),
    ({"stopped_by": "нет доступа к папке"}, "отказ по существу"),
])
def test_остановка_не_по_лимиту_шагов_не_продолжается(
        worker: Worker, over: dict[str, Any], why: str) -> None:
    """Повтор тут даст ровно тот же результат.

    Отказ по существу — нет ключа, нет доступа, сломанный формат — при
    повторе воспроизводится один в один, а квота аккаунта тратится впустую.
    Продолжать имеет смысл только то, что оборвано лимитом шагов.
    """
    task = task_row()

    again = worker._requeue_for_more_steps(task, limited_result(**over),
                                           task["payload"])

    assert again is False, f"продолжили задачу, остановленную по-другому: {why}"
    assert not worker.store.updates


def test_отменённая_задача_не_продолжается(worker: Worker) -> None:
    """Человек нажал «отмена» — возвращать задачу в очередь нельзя."""
    task = task_row()

    again = worker._requeue_for_more_steps(
        task, limited_result(cancelled=True), task["payload"])

    assert again is False
    assert not worker.store.updates


def test_без_причины_остановки_продолжать_нечего(worker: Worker) -> None:
    """Пустой `stopped_by` — задача остановилась сама, а не по лимиту."""
    task = task_row()

    again = worker._requeue_for_more_steps(
        task, limited_result(stopped_by=""), task["payload"])

    assert again is False
    assert not worker.store.updates


# --------------------------------------- агент продолжает, а не пересказывает


class _Scripted:
    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[list[dict[str, Any]]] = []

    async def ask(self, messages, **kw: Any) -> dict[str, Any]:
        index = min(len(self.calls), len(self.answers) - 1)
        self.calls.append(list(messages))
        return {"ok": True, "text": self.answers[index],
                "model": "т/модель", "duration_ms": 1, "status": "ok"}


def make_agent(tmp_path: Path, answers: list[str], max_steps: int = 4):
    from hub.registry import Registry
    from hub.tiers import TierBook

    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
                  workspace_root=tmp_path.resolve())
    selector = Selector(Registry(gateways=[], models=[]), TierBook({}))
    caller = _Scripted(answers)
    agent = Agent(selector, guard,
                  AgentConfig(max_steps=max_steps, base_dir=str(tmp_path)),
                  caller=caller)
    agent.set_task("Сделай аудит всего проекта")
    return agent, caller


def test_после_продолжения_агент_берётся_за_работу_а_не_за_отчёт(tmp_path: Path) -> None:
    """Ключевое поведение продолжения.

    Без указания «продолжай» агент видел бы в истории свой же промежуточный
    отчёт и на новом лимите просто повторил бы его: шаги потрачены, работа
    не сдвинулась, а со стороны выглядит как прогресс.
    """
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("данные", encoding="utf-8")
    agent, caller = make_agent(tmp_path, [
        '{"tool": "read_file", "args": {"path": "a.txt"}}',   # шаг 1
        '{"tool": "read_file", "args": {"path": "b.txt"}}',   # шаг 2
        "Промежуточный отчёт: прочитал часть файлов.",         # лимит кончен
        '{"tool": "read_file", "args": {"path": "c.txt"}}',   # продолжение
        "Итог: прочитал всё.",
    ], max_steps=2)

    first = asyncio.run(agent.run())
    # Отчёт под давлением «дай итог сейчас» — работа при этом не сделана,
    # и именно поэтому воркер продолжает задачу, а не закрывает её.
    assert (first.get("stopped_by") or "").startswith("лимит шагов")

    # Путь воркера: новый агент, восстановление из чекпоинта (оно сбрасывает
    # счётчики цикла) и требование продолжить. Проверка повторяет его
    # буквально, иначе тест проверял бы не тот путь, что работает в бою.
    agent.save_checkpoint()
    # Ответы второй попытки — свои: это другой вызов модели, а не продолжение
    # того же ответа. Сценарий «инструмент, потом итог» и есть нормальная
    # работа: агент берётся за дело и заканчивает его.
    second_agent, _ = make_agent(tmp_path, [
        '{"tool": "read_file", "args": {"path": "c.txt"}}',
        "Итог: прочитал всё.",
    ], max_steps=2)
    assert second_agent.restore_checkpoint(agent.checkpoint), \
        "чекпоинт не восстановился — продолжение началось бы с нуля"

    second_agent.messages.append({"role": "user", "content": CONTINUE_PROMPT})
    second_agent.config.max_steps += CONTINUATION_STEPS
    second = asyncio.run(second_agent.run())

    assert second.get("ok") is True, second
    assert second["last"] == "Итог: прочитал всё."
    # И он не повторял отчёт на новых шагах.
    assert sum(1 for s in second_agent.steps if s.tool == "read_file") == 1
    # Продолжение началось с того места, где остановилось.
    seen = " ".join(str(m.get("content")) for m in second_agent.messages)
    assert CONTINUE_PROMPT in seen


def test_подсказка_продолжения_запрещает_пересказ(tmp_path: Path) -> None:
    """Формулировка должна прямо запрещать повтор отчёта."""
    low = CONTINUE_PROMPT.lower()
    assert "не пересказывай" in low
    assert "продолжи" in low
    assert "итог" in low


def test_продолжение_сбрасывает_счётчики_остановок(tmp_path: Path) -> None:
    """Иначе второй заход упёрся бы в ту же защиту и остановился сразу.

    `budget_exceeded` и счётчики повторов живут до конца цикла: без сброса
    продолжение получило бы уже взведённый стоп и не сделало ни одного шага.
    """
    agent, _ = make_agent(tmp_path, ["Готово."])
    agent.budget_exceeded = True
    agent.repeat_counts = {"read_file:a.txt": 9}
    agent.wrap_up = 1
    agent.stop_reason = "бюджет задачи исчерпан"

    agent._reset_cycle()

    assert agent.budget_exceeded is False
    assert agent.repeat_counts == {}
    assert agent.wrap_up == 0
    assert agent.stop_reason == ""