"""Чёрный ящик задачи: полный трейс одной задачи одним файлом.

Идея из `update/creativeupdate-07-10-26.txt` («Полётный регистратор»):
все попытки, хопы и ошибки уже пишутся в SQLite (`store.events`) — остаётся
отдать их человеку одним нажатием, чтобы разбор полёта не превращался в
опрос базы руками.

Формат — JSONL, одна запись на строку:

    {"record": "task",    ...}   карточка задачи: текст, статус, время
    {"record": "summary", ...}   хопы, модели, токены, первая ошибка
    {"record": "event",   ...}   каждое событие по порядку

Такой файл открывается обычным редактором, граблится `grep`'ом и дописывается,
если задача ещё идёт. Значения ключей вымарываются: чёрный ящик выкладывают
в переписку при разборе, а там секретов быть не должно.
"""

from __future__ import annotations

import json
from typing import Any

from hub.config import load_secrets

#: Потолок событий на выгрузку. Журнал подрезается сам (`trim_events`),
#: но гипотеза «задача на миллион событий» не должна вешать интерфейс.
MAX_EVENTS = 10_000

#: События, по которым считается сводка. `step` — хоп с моделью и временем,
#: `model_call` — расход токенов и ошибка вызова.
STEP_TYPE = "step"
CALL_TYPE = "model_call"


class BlackboxError(LookupError):
    """Задача не найдена — выдавать её нечего."""


def _secrets(root: Any = None) -> list[str]:
    """Значения настоящих ключей, которые обязаны вымараться в выдаче."""
    try:
        data = load_secrets(root)
    except Exception:  # нет файла — вымарывать нечего, и это не повод падать
        return []
    out: list[str] = []
    for value in data.values():
        for item in (value if isinstance(value, list) else [value]):
            text = str(item).strip()
            if len(text) >= 8:
                out.append(text)
    return out


def redact(text: str, root: Any = None) -> str:
    """Заменить каждое вхождение настоящего ключа на маркер.

    Точное сравнение, а не эвристика по виду ключа: ложных срабатываний
    нет (маркер не появится там, где ключа не было), а секрет в трейсе
    появиться не может — он подставляется из той же папки конфигурации,
    откуда его читает сама программа.
    """
    for value in _secrets(root):
        text = text.replace(value, "***")
    return text


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка по трейсу: сколько хопов, какие модели, где сломалось.

    `events` — то, что отдаёт `store.events_since()`: само событие, поля
    лежат на верхнем уровне (type, step, sent, error), отдельной «payload»
    там нет — она была только в колонке базы.
    """
    steps = [e for e in events if e.get("type") == STEP_TYPE]
    calls = [e for e in events if e.get("type") == CALL_TYPE]

    models: dict[str, dict[str, int]] = {}
    failed: list[str] = []
    ms_total = 0
    for event in steps:
        step = event.get("step") or {}
        model = str(step.get("model") or "")
        if not model:
            continue
        row = models.setdefault(model, {"steps": 0, "failed": 0, "ms": 0})
        row["steps"] += 1
        ms = int(step.get("duration_ms") or 0)
        row["ms"] += ms
        ms_total += ms
        if step.get("ok") is False:
            row["failed"] += 1
            if step.get("error"):
                failed.append(str(step["error"]))

    sent = sum(int(c.get("sent") or 0) for c in calls)
    got = sum(int(c.get("got") or 0) for c in calls)
    call_errors = [
        str(c.get("error")) for c in calls if c.get("error")
    ]

    types: dict[str, int] = {}
    for event in events:
        kind = str(event.get("type") or "?")
        types[kind] = types.get(kind, 0) + 1

    return {
        "events": len(events),
        "steps": len(steps),
        "models": models,
        "duration_ms": ms_total,
        "tokens_sent": sent,
        "tokens_got": got,
        "types": dict(sorted(types.items())),
        "first_error": (failed + call_errors)[0] if (failed or call_errors) else None,
    }


def build(store: Any, task_id: int, *, root: Any = None) -> str:
    """Собрать чёрный ящик задачи в текст JSONL.

    `store` — объект хранилища (нужны `get_task` и `events_since`),
    `root` — корень проекта для вымаркивания ключей.
    """
    task = store.get_task(task_id)
    if task is None:
        raise BlackboxError(f"Задачи {task_id} в журнале нет")

    events = [
        {"record": "event", **row}
        for row in store.events_since(0, task_id=task_id, limit=MAX_EVENTS)
    ]
    card = {"record": "task", **task}
    summary = {"record": "summary", **summarize(events)}

    text = "\n".join(
        json.dumps(line, ensure_ascii=False, default=str)
        for line in [card, summary, *events]
    )
    return redact(text, root) + "\n"


def filename(task_id: int) -> str:
    """Имя файла для скачивания: по номеру задачи, ничего лишнего."""
    return f"blackbox-task-{int(task_id)}.jsonl"
