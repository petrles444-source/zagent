"""Выбор модели по роли с fallback-цепочкой.

agents.json задаёт для каждой роли упорядоченный список моделей.
Если первая недоступна (ответ с "error"), берётся следующая.
"""

from __future__ import annotations

from typing import Any, Sequence

from hub.bus import log_usage, usage_record
from providers.base import Provider


class RouterError(RuntimeError):
    """Некорректная роль или пустая цепочка моделей."""


class Router:
    """Роутер ролей: роль -> цепочка моделей -> первый успешный ответ."""

    def __init__(
        self,
        agents: dict[str, list[str]],
        models: Sequence[dict[str, str]] | None = None,
    ) -> None:
        self.agents = {str(role): list(chain) for role, chain in agents.items()}
        self.models = list(models or [])

    @property
    def roles(self) -> list[str]:
        return sorted(self.agents)

    def chain(self, role: str) -> list[str]:
        """Fallback-цепочка моделей для роли."""
        if role not in self.agents:
            known = ", ".join(self.roles) or "нет"
            raise RouterError(f"Неизвестная роль '{role}'. Доступные роли: {known}")
        chain = self.agents[role]
        if not chain:
            raise RouterError(f"У роли '{role}' пустая цепочка моделей")
        return list(chain)

    def label(self, model_id: str) -> str:
        """Метка модели из models.json (или сам id)."""
        for item in self.models:
            if item.get("id") == model_id:
                return item.get("label") or model_id
        return model_id

    async def ask(
        self,
        provider: Provider,
        role: str,
        messages: Sequence[dict[str, Any]],
        *,
        root: str | None = None,
        log: bool = True,
        **kw: Any,
    ) -> dict[str, Any]:
        """Спросить модель по роли, перебирая fallback-цепочку.

        Возвращает нормализованный результат плюс поля:
        model, role, attempts, fallback.
        """
        chain = self.chain(role)
        attempts: list[dict[str, Any]] = []
        last: dict[str, Any] | None = None

        for index, model_id in enumerate(chain):
            result = await provider.chat(model_id, messages, **kw)
            if log:
                log_usage(usage_record(model=model_id, role=role, result=result), root=root)

            failed = result.get("error") is not None
            attempts.append(
                {"model": model_id, "ok": not failed, "error": result.get("error")}
            )
            last = result

            if not failed:
                answer = dict(result)
                answer.update(
                    model=model_id,
                    role=role,
                    attempts=attempts,
                    fallback=index > 0,
                )
                return answer

        # Все модели цепочки упали — возвращаем последнюю ошибку с деталями.
        assert last is not None  # цепочка непустая (проверено в chain())
        answer = dict(last)
        answer.update(
            model=chain[-1],
            role=role,
            attempts=attempts,
            fallback=len(chain) > 1,
        )
        return answer
