"""Провайдер OpenCode Zen (OpenAI-совместимый Chat Completions)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from providers.base import Messages, Provider, error_result, host_of, ok_result

#: таймаут по умолчанию, сек (ТЗ, раздел 7)
DEFAULT_TIMEOUT = 30.0

NO_KEY_MESSAGE = "ZEN_API_KEY не задан. Создайте config/secrets.local.json"


class ZenProvider(Provider):
    """Клиент шлюза OpenCode Zen.

    Параметры:
        base_url: база API, например https://opencode.ai/zen/v1
        api_key: ключ oc_sk-...
        timeout: таймаут одного запроса в секундах
        client: готовый httpx.AsyncClient (удобно для тестов)
    """

    name = "zen"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = _check_timeout(timeout)
        self._client = client
        self._owns_client = client is None

    # ------------------------------------------------------------------ клиент

    @property
    def client(self) -> httpx.AsyncClient:
        """Лениво создаём общий AsyncClient, чтобы переиспользовать соединения."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True
        return self._client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def aclose(self) -> None:
        """Закрыть клиент, если он создан самим провайдером."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    # -------------------------------------------------------------------- чат

    async def chat(
        self,
        model_id: str,
        messages: Messages,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        **kw: Any,
    ) -> dict[str, Any]:
        """Один вызов /chat/completions с нормализованным результатом."""
        started = time.perf_counter()

        if not self.api_key:
            return error_result(NO_KEY_MESSAGE, duration_ms=_ms(started))

        payload: dict[str, Any] = {"model": model_id, "messages": list(messages)}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(kw)

        url = f"{self.base_url}/chat/completions"
        try:
            response = await self.client.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=timeout if timeout is not None else self.timeout,
            )
        except httpx.TimeoutException:
            return error_result(f"Таймаут модели {model_id}", duration_ms=_ms(started))
        except httpx.HTTPError:
            # Текст исключения не пишем: httpx повторяет URL запроса.
            # Правило то же, что в openai_compat.chat, — иначе ошибка из
            # одного провайдера утекает, а из другого нет.
            return error_result(f"Сеть недоступна ({host_of(self.base_url)})",
                                duration_ms=_ms(started))
        except OSError:
            # Сеть недоступна целиком: DNS не resolved, соединение refused,
            # сокет упал. `httpx.HTTPError` это не покрывает, а ловить
            # Exception здесь нельзя — под ним прячется опечатка в коде
            # провайдера, и она молча превращается в «сеть недоступна».
            return error_result(f"Сеть недоступна ({host_of(self.base_url)})",
                                duration_ms=_ms(started))

        duration_ms = _ms(started)
        status = response.status_code

        # --- ошибки HTTP (ТЗ, раздел 7)
        if status == 401:
            return error_result("Неверный ключ", duration_ms=duration_ms, status=status)
        if status == 429:
            return error_result("Лимит запросов, попробуйте позже", duration_ms=duration_ms, status=status)
        if status >= 500:
            return error_result(
                f"Модель {model_id} временно недоступна", duration_ms=duration_ms, status=status
            )

        try:
            data = response.json()
        except ValueError:
            if status >= 400:
                return error_result(
                    f"HTTP {status}: {_snippet(response.text)}", duration_ms=duration_ms, status=status
                )
            return error_result("Некорректный ответ шлюза (не JSON)", duration_ms=duration_ms, status=status)

        if status >= 400:
            message = _error_message(data) or _snippet(response.text)
            return error_result(f"HTTP {status}: {message}", duration_ms=duration_ms, status=status, raw=data)

        text = _extract_text(data)
        if not text.strip():
            return error_result("Пустой ответ модели", duration_ms=duration_ms, status=status, raw=data)

        usage = data.get("usage") or {}
        return ok_result(
            text,
            tokens_in=usage.get("prompt_tokens") or 0,
            tokens_out=usage.get("completion_tokens") or 0,
            duration_ms=duration_ms,
            status=status,
            raw=data,
        )


# ------------------------------------------------------------------ утилиты


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _check_timeout(timeout: float) -> float:
    """Проверить таймаут на границе провайдера.

    httpx трактует таймаут <= 0 как «истечь мгновенно», и ошибка приходит
    уже изнутри сетевого слоя — с текстом, по которому не понять, что
    не так. Здесь она превращается в сообщение про саму настройку.
    """
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"timeout должен быть числом, получено {timeout!r}") from exc
    if value <= 0:
        raise ValueError(f"timeout должен быть положительным, получено {value}")
    return value


def _extract_text(data: dict[str, Any]) -> str:
    """Достать текст ответа из OpenAI-совместимого тела.

    Шлюз — чужой код, и `choices[0]` у него может оказаться не словарём или
    вовсе `null`: тело ответа тогда разбирается ниже по `.get`, и
    AttributeError уходил наружу вместо нормального «пустой ответ модели».
    """
    choices = data.get("choices") or []
    first = choices[0] if choices else None
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # некоторые шлюзы отдают список частей
        parts = []
        for chunk in content:
            if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                parts.append(chunk["text"])
        return "".join(parts)
    return ""


def _error_message(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "")
    if isinstance(error, str):
        return error
    return ""


def _snippet(text: str, limit: int = 200) -> str:
    return " ".join((text or "").split())[:limit]
