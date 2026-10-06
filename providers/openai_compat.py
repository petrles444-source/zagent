"""Универсальный OpenAI-совместимый провайдер.

Один класс покрывает все шлюзы из config/gateways.json: у них одинаковый контракт
`POST {base_url}/chat/completions` с Bearer-токеном, отличаются только base_url,
заголовки и способ авторизации (в том числе полное отсутствие ключа).
"""

from __future__ import annotations

import time
from urllib.parse import urlparse
from typing import Any

import httpx

from providers.base import Messages, Provider, error_result, ok_result

DEFAULT_TIMEOUT = 45.0

USER_AGENT = "zagent/0.1 (+https://github.com/)"


class OpenAICompatProvider(Provider):
    """Клиент одного шлюза.

    Параметры:
        gateway_id: id шлюза из config/gateways.json
        base_url: база API (уже с подставленными секретами)
        api_key: Bearer-токен; пустая строка для keyless-шлюзов
        timeout: таймаут одного запроса, сек
        client: готовый httpx.AsyncClient (для тестов)
        extra_body: поля, которые шлюз требует сверх стандартного запроса

    `extra_body` — не украшение. У NVIDIA, например, размышление включается
    по умолчанию, и модель тратит на него несколько секунд и часть ответа.
    Поле `chat_template_kwargs: {"enable_thinking": false}` выключает его,
    и по замеру ответ приходит вдвое быстрее. Прописывать это в коде нельзя:
    у другого шлюза такого поля нет, и запрос ушёл бы с ошибкой.
    """

    def __init__(
        self,
        gateway_id: str,
        base_url: str,
        api_key: str = "",
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.gateway_id = gateway_id
        self.name = gateway_id
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = float(timeout)
        self.extra_headers = dict(extra_headers or {})
        self.extra_body = dict(extra_body or {})
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        return headers

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

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

        payload: dict[str, Any] = {"model": model_id, "messages": list(messages)}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(self.extra_body)
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
        except Exception as exc:
            # Текст исключения сюда не пишем: у httpx он включает URL, а
            # `base_url` у некоторых шлюзов уже с подставленными секретами.
            # Ошибка уходит в журнал событий, то есть в интерфейс, — и ключ
            # оказался бы на экране.
            return error_result(
                f"Сеть недоступна: {type(exc).__name__} "
                f"({_host_of(self.base_url)})",
                duration_ms=_ms(started),
            )

        duration_ms = _ms(started)
        status = response.status_code
        limits = rate_limits(response.headers)

        if status == 401 or status == 403:
            return error_result(
                f"Ключ отклонён или доступ закрыт ({status})", duration_ms=duration_ms,
                status=status, limits=limits,
            )
        if status == 429:
            # Причина 429 разная, и от неё зависит, что делать с ключом:
            # кончилась минутная квота — подождёт минуту; нет денег на
            # аккаунте — не отпустит никогда. Разбор делаем здесь, потому что
            # дальше текст попадает в keyring, где решается судьба аккаунта.
            reason = _limit_reason(response.text)
            return error_result(reason, duration_ms=duration_ms, status=status,
                                limits=limits)
        if status >= 500:
            return error_result(
                f"Модель {model_id} временно недоступна", duration_ms=duration_ms,
                status=status, limits=limits,
            )

        try:
            data = response.json()
        except ValueError:
            if status >= 400:
                return error_result(
                    f"HTTP {status}: {_snippet(response.text)}", duration_ms=duration_ms,
                    status=status, limits=limits,
                )
            return error_result("Некорректный ответ шлюза (не JSON)",
                                duration_ms=duration_ms, status=status, limits=limits)

        if status >= 400:
            message = _error_message(data) or _snippet(response.text)
            return error_result(f"HTTP {status}: {message}", duration_ms=duration_ms,
                                status=status, raw=data, limits=limits)

        usage = data.get("usage") or {}
        text = _extract_text(data)
        reasoning = _extract_reasoning(data)

        # Reasoning-модели могут потратить весь max_tokens на размышление и вернуть
        # пустой content. Это не ошибка, поэтому отдаём текст ответа как есть,
        # но помечаем результат, чтобы health-check не считал модель упавшей.
        return ok_result(
            text,
            tokens_in=usage.get("prompt_tokens") or 0,
            tokens_out=usage.get("completion_tokens") or 0,
            duration_ms=duration_ms,
            status=status,
            raw=data,
            reasoning=reasoning,
            cost=usage.get("cost"),
            limits=limits,
        )

    async def list_models(self) -> dict[str, Any]:
        """GET /models — каталог шлюза. Ошибки не бросает, а возвращает как результат."""
        started = time.perf_counter()
        try:
            response = await self.client.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=self.timeout
            )
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "ids": []}

        if response.status_code != 200:
            return {"ok": False, "error": f"HTTP {response.status_code}", "ids": [], "status": response.status_code}
        try:
            data = response.json()
        except ValueError:
            return {"ok": False, "error": "не JSON", "ids": []}

        return {"ok": True, "ids": extract_model_ids(data), "status": 200, "duration_ms": _ms(started)}


# ------------------------------------------------------------------ утилиты


def extract_model_ids(data: Any) -> list[str]:
    """Достать id моделей из разных форматов каталогов."""
    payload = data.get("data") if isinstance(data, dict) else data
    if not isinstance(payload, list):
        payload = data.get("models") if isinstance(data, dict) else None
    if not isinstance(payload, list):
        return []
    ids: list[str] = []
    for item in payload:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            value = item.get("id") or item.get("name") or item.get("model")
            if isinstance(value, str):
                ids.append(value)
    return ids


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                parts.append(chunk["text"])
        return "".join(parts)
    return ""


def _extract_reasoning(data: dict[str, Any]) -> str:
    """Текст размышления reasoning-моделей (некоторые кладут его в отдельное поле)."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    for field in ("reasoning", "reasoning_content"):
        value = message.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _error_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or "")
    if isinstance(error, str):
        return error
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or "")
        return str(first)
    return ""


#: Заголовки квоты у разных провайдеров называются по-разному, но смысл
#: один: сколько ещё осталось и сколько всего. Приводим к общим именам.
_LIMIT_FIELDS = {
    # Только заголовок про запросы. Заголовок про *токены запросов*
    # (`x-ratelimit-remaining-request-tokens`) сюда раньше попадал, и его
    # значение — миллионы токенов — записывалось в `requests_remaining`, то
    # есть в «осталось запросов». Из этого дальше читались и остаток в
    # интерфейсе, и решение о том, хватит ли аккаунта на часть задачи:
    # оба предостерегали, что ноль не то же самое, что неизвестно, и оба
    # переставали работать.
    "requests_remaining": ("x-ratelimit-remaining-requests",),
    "requests_limit": ("x-ratelimit-limit-requests",
                       "ratelimit-limit-requests"),
    "tokens_remaining": ("x-ratelimit-remaining-tokens",
                         "x-ratelimit-remaining-request-tokens"),
    "tokens_limit": ("x-ratelimit-limit-tokens",),
    "reset_after": ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"),
    "reset_at": ("x-ratelimit-reset", "ratelimit-reset"),
}


def rate_limits(headers: Any) -> dict[str, Any]:
    """Остаток квоты из заголовков ответа. Пусто — провайдер не сообщает.

    Нужно не для красивого счёта, а для решения *до* запроса: если у аккаунта
    осталось два запроса, поручать ему часть из двадцати шагов бессмысленно —
    агент упрётся в лимит на середине и потеряет результат.
    """
    out: dict[str, Any] = {}
    for field, names in _LIMIT_FIELDS.items():
        for name in names:
            raw = headers.get(name)
            if raw is None:
                continue
            out[field] = _limit_value(raw)
            break
    return {k: v for k, v in out.items() if v is not None}


def _limit_value(raw: Any) -> Any:
    """Значение заголовка: число, если это число.

    Часть провайдеров пишет время сброса как «1m26.4s», а не как секунды.
    Такое оставляем строкой: использовать его как число хуже, чем не
    использовать вовсе.
    """
    text = str(raw).strip()
    if not text:
        return None
    try:
        value: Any = int(text)
    except ValueError:
        try:
            value = float(text)
        except ValueError:
            return text
    # Отрицательный остаток встречается у некоторых: значит «перерасход»,
    # и считать его нулём нельзя — так потеряется сам факт исчерпания.
    return value


def _host_of(url: str) -> str:
    """Только хост из адреса шлюза, без схемы, пути и параметров.

    Нужно для текста ошибки: полный URL у некоторых шлюзов содержит ключ в
    query-строке, а текст ошибки попадает в журнал событий и на экран.
    """
    try:
        return urlparse(str(url or "")).netloc or "?"
    except ValueError:
        return "?"


def _snippet(text: str, limit: int = 200) -> str:
    return " ".join((text or "").split())[:limit]


#: Признаки того, что аккаунт пуст, а не исчерпал лимит. У всех провайдеров
#: текст разный, но смысл один: денег нет, и ждать бесполезно.
EMPTY_ACCOUNT_MARKERS = (
    "insufficient",
    "no resource package",
    "recharge",
    "quota exceeded for",
    "out of credits",
    "billing",
)

#: Признаки настоящего лимита — квота кончилась, но восстановится.
LIMIT_MARKERS = (
    "rate limit",
    "rate_limited",
    "too many requests",
    "quota",
    "429",
)


def _limit_reason(body: str) -> str:
    """Понять, почему провайдер ответил 429.

    Текст ответа уходит дальше в keyring, где по нему аккаунт либо
    помечается как исчерпавший лимит на час, либо как пустой. Путать эти два
    случая нельзя: первый отпустит через час сам, второй не отпустит никогда,
    пока не пополнят.
    """
    text = _snippet(body, 400).lower()
    if any(marker in text for marker in EMPTY_ACCOUNT_MARKERS):
        return "429 нет баланса на аккаунте — пополните его"
    if any(marker in text for marker in LIMIT_MARKERS):
        return "429 лимит запросов, попробуйте позже"
    return f"429 {_snippet(body, 120)}"
