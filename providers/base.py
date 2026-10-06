"""Абстрактный провайдер LLM.

Все провайдеры возвращают нормализованный словарь одного вида:

    {
        "text": "ответ модели",
        "tokens_in": 0,
        "tokens_out": 0,
        "duration_ms": 0,
        "status": 200 | None,   # HTTP-код, если он был получен
        "raw": {...},           # сырой JSON ответа (или None)
        "error": None | "текст ошибки",
    }

Поле "error" равно None только при успешном ответе.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

Messages = Sequence[dict[str, Any]]

# Ключи нормализованного результата (всегда присутствуют все).
RESULT_KEYS = ("text", "tokens_in", "tokens_out", "duration_ms", "status", "raw", "error")


def ok_result(
    text: str,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    duration_ms: int = 0,
    status: int | None = None,
    raw: dict[str, Any] | None = None,
    reasoning: str = "",
    cost: Any = None,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Собрать успешный результат.

    Дополнительные поля:
        reasoning: текст размышления, если провайдер вернул его отдельным полем
        cost: стоимость запроса, если провайдер её сообщает (OpenRouter)
        limits: остаток квоты по заголовкам провайдера (`x-ratelimit-*`)
    """
    return {
        "text": text,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "duration_ms": int(duration_ms),
        "status": status,
        "raw": raw,
        "error": None,
        "reasoning": reasoning,
        "cost": cost,
        "limits": limits or {},
    }


def error_result(
    error: str,
    *,
    duration_ms: int = 0,
    status: int | None = None,
    raw: dict[str, Any] | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Собрать результат с ошибкой (текст ответа всегда пустой)."""
    return {
        "text": "",
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "duration_ms": int(duration_ms),
        "status": status,
        "raw": raw,
        "error": error,
        "reasoning": "",
        "cost": None,
        # Остаток лимитов приходит даже в ответе об ошибке — именно в нём
        # видно, что запрос не выдан. Без него нельзя понять заранее,
        # вывезет ли задача этот аккаунт.
        "limits": limits or {},
    }


class Provider(ABC):
    """Базовый класс провайдера."""

    #: короткое имя провайдера для логов
    name: str = "base"

    @abstractmethod
    async def chat(self, model_id: str, messages: Messages, **kw: Any) -> dict[str, Any]:
        """Отправить сообщения модели и вернуть нормализованный результат."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Освободить ресурсы провайдера (по умолчанию ничего не делает)."""
        return None

    async def __aenter__(self) -> "Provider":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()
