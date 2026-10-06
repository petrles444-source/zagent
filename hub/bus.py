"""Шина параллельных вызовов и журнал usage.jsonl."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from providers.base import Provider, error_result

USAGE_DIRNAME = "logs"
USAGE_FILENAME = "usage.jsonl"


def utc_now() -> str:
    """Метка времени в формате 2026-10-05T12:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def gather_chats(
    provider: Provider,
    model_ids: Sequence[str],
    messages: Sequence[dict[str, Any]],
    **kw: Any,
) -> list[dict[str, Any]]:
    """Параллельно спросить несколько моделей.

    Результаты возвращаются в том же порядке, что и model_ids.
    Исключение внутри одного вызова не роняет остальные — оно
    превращается в результат с ошибкой.
    """
    tasks = [provider.chat(model_id, messages, **kw) for model_id in model_ids]
    if not tasks:
        return []
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[dict[str, Any]] = []
    for model_id, item in zip(model_ids, raw):
        if isinstance(item, BaseException):
            results.append(error_result(f"Внутренняя ошибка: {item}"))
        elif not isinstance(item, dict):
            # Провайдер нарушил контракт и вернул не словарь. Раньше такое
            # молча уходило в выдачу, и первый же `result.get(...)` падал с
            # AttributeError уже в другом месте — виноватым оказывался
            # вызывающий, а не сломанный провайдер.
            results.append(error_result(
                f"Некорректный результат от провайдера: {type(item).__name__}"))
        else:
            results.append(item)
    return results


def usage_record(
    *,
    model: str,
    role: str,
    result: dict[str, Any],
    at: str | None = None,
) -> dict[str, Any]:
    """Собрать одну запись журнала из нормализованного результата."""
    return {
        "at": at or utc_now(),
        "model": model,
        "role": role,
        "ok": result.get("error") is None,
        "duration_ms": int(result.get("duration_ms") or 0),
        "tokens_in": int(result.get("tokens_in") or 0),
        "tokens_out": int(result.get("tokens_out") or 0),
        "error": result.get("error"),
    }


def usage_path(root: str | Path | None = None) -> Path:
    from hub.config import project_root

    base = Path(root) if root is not None else project_root()
    return base / USAGE_DIRNAME / USAGE_FILENAME


def log_usage(record: dict[str, Any], root: str | Path | None = None) -> None:
    """Дописать событие в logs/usage.jsonl (одна строка = одно событие).

    Ошибка записи не должна ломать вызов модели — предупреждаем в stderr.
    Ловится не только `OSError`: `json.dumps` падает с `TypeError` на любом
    несериализуемом значении (объект, сет,.bytes), и раньше такая ошибка
    вылетала из журнала и роняла вызов модели, ради которого писалась
    строчка. Журнал — не то место, где задача должна падать.
    """
    path = usage_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"Предупреждение: не удалось записать {path}: {exc}", file=sys.stderr)


def log_results(
    pairs: Iterable[tuple[str, str, dict[str, Any]]],
    root: str | Path | None = None,
) -> None:
    """Записать пачку событий: (model, role, result)."""
    for model, role, result in pairs:
        log_usage(usage_record(model=model, role=role, result=result), root=root)
