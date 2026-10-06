"""Текст ошибки не должен нести ключ.

У части шлюзов секрет входит в `base_url` query-строкой, а текст
исключения httpx URL повторяет. Ошибка из `list_models` едет в
`registry.errors` и оттуда — в интерфейс и CLI; ошибка из `chat` — в журнал
событий. То есть ключ, показанный один раз на экране, остаётся там в
скриншоте и в переписке.

Проверяется, что во всех трёх местах остаётся хост (иначе диагностика
умирает: «что сломалось, у какого шлюза»), а полного адреса нет.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from providers.base import host_of  # noqa: E402
from providers.openai_compat import OpenAICompatProvider  # noqa: E402
from providers.zen import ZenProvider  # noqa: E402

SECRET_URL = "https://gw.test/v1?apikey=TOPSECRET-9f3a"
SECRET = "TOPSECRET-9f3a"


class _ExplodingClient:
    """Клиент, который падает с текстом, повторяющим адрес запроса."""

    def __init__(self, method: str = "get") -> None:
        self.method = method

    async def get(self, url: str, **kw: Any) -> Any:
        raise RuntimeError(f"All connection attempts failed for {url}")

    async def post(self, url: str, **kw: Any) -> Any:
        raise RuntimeError(f"All connection attempts failed for {url}")


class _ExplodingHttpxClient:
    """Как выше, но с исключением из семейства httpx — как в zen."""

    async def post(self, url: str, **kw: Any) -> Any:
        raise _HttpxFailure(f"All connection attempts failed for {url}")


class _HttpxFailure(httpx.HTTPError):
    """Своя ошибка httpx: конструктор не требует request."""


# ============================================================ list_models


def test_list_models_не_показывает_ключ() -> None:
    provider = OpenAICompatProvider("gw", SECRET_URL, "k",
                                    client=_ExplodingClient())
    result = asyncio.run(provider.list_models())

    assert result["ok"] is False
    assert SECRET not in str(result["error"]), result["error"]
    assert "gw.test" in str(result["error"]), (
        f"хост пропал — диагностика больше не говорит, куда сломалось: "
        f"{result['error']}"
    )


# =================================================================== chat


def test_chat_не_показывает_ключ_из_url() -> None:
    provider = OpenAICompatProvider("gw", SECRET_URL, "k",
                                    client=_ExplodingClient("post"))
    result = asyncio.run(
        provider.chat("m", [{"role": "user", "content": "x"}]))

    assert result["error"], "ошибки нет вовсе"
    assert SECRET not in str(result["error"]), result["error"]
    assert "gw.test" in str(result["error"]), result["error"]


def test_zen_не_показывает_адрес_запроса() -> None:
    provider = ZenProvider(SECRET_URL, "sk-zen", client=_ExplodingHttpxClient())
    result = asyncio.run(
        provider.chat("m", [{"role": "user", "content": "x"}]))

    assert result["error"], "ошибки нет вовсе"
    assert SECRET not in str(result["error"]), result["error"]
    assert "gw.test" in str(result["error"]), result["error"]


def test_ошибка_сети_в_zen_остаётся_ошибкой_сети() -> None:
    """Закрытие утечки не должно превратить сообщение в безликий мусор."""
    provider = ZenProvider(SECRET_URL, "sk-zen", client=_ExplodingHttpxClient())
    result = asyncio.run(
        provider.chat("m", [{"role": "user", "content": "x"}]))

    assert "Сеть недоступна" in str(result["error"]), result["error"]


# ================================================================ хост_как_так


def test_host_of_отрезает_путь_и_параметры() -> None:
    assert host_of(SECRET_URL) == "gw.test"
    assert host_of("http://127.0.0.1:8783/api") == "127.0.0.1:8783"
    assert host_of("") == "?"
