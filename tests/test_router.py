"""Тесты роутера ролей: цепочки, fallback, журнал."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Sequence

import pytest

from hub.bus import usage_path
from hub.router import Router, RouterError
from providers.base import Provider, error_result, ok_result

AGENTS = {
    "coder": ["mimo-v2.6-flash-free", "space-bunny-free"],
    "architect": ["longcat-2.5-preview-free"],
}
MODELS = [
    {"id": "mimo-v2.6-flash-free", "label": "MiMo"},
    {"id": "longcat-2.5-preview-free", "label": "LongCat"},
    {"id": "space-bunny-free", "label": "Space Bunny"},
]


class FakeProvider(Provider):
    """Провайдер-заглушка: падает на моделях из fail_for, отвечает на остальные."""

    name = "fake"

    def __init__(self, fail_for: Sequence[str] = ()) -> None:
        self.fail_for = set(fail_for)
        self.calls: list[str] = []

    async def chat(self, model_id: str, messages: Sequence[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        self.calls.append(model_id)
        if model_id in self.fail_for:
            return error_result(f"Модель {model_id} временно недоступна", duration_ms=10, status=503)
        return ok_result(f"ответ от {model_id}", tokens_in=5, tokens_out=3, duration_ms=12)


def make_router() -> Router:
    return Router(AGENTS, MODELS)


# ------------------------------------------------------------------- цепочки


def test_chain_returns_configured_order():
    assert make_router().chain("coder") == ["mimo-v2.6-flash-free", "space-bunny-free"]


def test_chain_is_a_copy():
    router = make_router()
    router.chain("coder").append("x")
    assert router.chain("coder") == ["mimo-v2.6-flash-free", "space-bunny-free"]


def test_unknown_role_raises():
    with pytest.raises(RouterError, match="Неизвестная роль"):
        make_router().chain("нет-такой-роли")


def test_roles_listed():
    assert make_router().roles == ["architect", "coder"]


def test_label_lookup():
    router = make_router()
    assert router.label("space-bunny-free") == "Space Bunny"
    assert router.label("неизвестная") == "неизвестная"


# ------------------------------------------------------------------- fallback


def test_ask_uses_first_model():
    provider = FakeProvider()
    result = asyncio.run(make_router().ask(provider, "coder", [{"role": "user", "content": "привет"}], log=False))
    assert result["error"] is None
    assert result["model"] == "mimo-v2.6-flash-free"
    assert result["fallback"] is False
    assert provider.calls == ["mimo-v2.6-flash-free"]


def test_ask_falls_back_to_second_model():
    provider = FakeProvider(fail_for=["mimo-v2.6-flash-free"])
    result = asyncio.run(make_router().ask(provider, "coder", [{"role": "user", "content": "привет"}], log=False))
    assert result["error"] is None
    assert result["model"] == "space-bunny-free"
    assert result["fallback"] is True
    assert provider.calls == ["mimo-v2.6-flash-free", "space-bunny-free"]
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["ok"] is False


def test_ask_returns_error_when_all_models_fail():
    provider = FakeProvider(fail_for=["mimo-v2.6-flash-free", "space-bunny-free"])
    result = asyncio.run(make_router().ask(provider, "coder", [{"role": "user", "content": "привет"}], log=False))
    assert result["error"] is not None
    assert result["status"] == 503
    assert result["model"] == "space-bunny-free"
    assert provider.calls == ["mimo-v2.6-flash-free", "space-bunny-free"]


def test_ask_awaits_calls_with_kwargs():
    provider = FakeProvider()
    result = asyncio.run(
        make_router().ask(
            provider, "architect", [{"role": "user", "content": "?"}], log=False, temperature=0
        )
    )
    assert result["model"] == "longcat-2.5-preview-free"


# --------------------------------------------------------------------- журнал


def test_ask_writes_usage_jsonl(tmp_path: Path):
    provider = FakeProvider(fail_for=["mimo-v2.6-flash-free"])
    result = asyncio.run(
        make_router().ask(
            provider,
            "coder",
            [{"role": "user", "content": "привет"}],
            root=tmp_path,
            log=True,
        )
    )
    assert result["error"] is None

    lines = usage_path(tmp_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # две попытки — две строки

    first, second = (json.loads(line) for line in lines)
    assert first["model"] == "mimo-v2.6-flash-free"
    assert first["role"] == "coder"
    assert first["ok"] is False
    assert first["error"] is not None
    assert first["at"].endswith("Z")
    assert second["model"] == "space-bunny-free"
    assert second["ok"] is True
    assert second["tokens_in"] == 5 and second["tokens_out"] == 3
