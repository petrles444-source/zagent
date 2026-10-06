"""Тесты загрузки конфигурации шлюзов."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub.config import (
    ConfigError,
    gateway_by_id,
    gateways_with_key,
    load_gateways,
    render_base_url,
    resolve_secret,
)


def write_config(root: Path, gateways: list[dict], secrets: dict | None = None) -> Path:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "gateways.json").write_text(
        json.dumps({"gateways": gateways}), encoding="utf-8"
    )
    if secrets is not None:
        (root / "config" / "secrets.local.json").write_text(
            json.dumps(secrets), encoding="utf-8"
        )
    return root


def test_reads_gateways(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [{"id": "openrouter", "base_url": "https://openrouter.ai/api/v1", "free_models": ["a:free"]}],
        {"openrouter": "sk-or-v1-x"},
    )
    gateways = load_gateways(tmp_path, env={})

    assert len(gateways) == 1
    assert gateways[0]["id"] == "openrouter"
    assert gateways[0]["api_key"] == "sk-or-v1-x"
    assert gateways[0]["has_key"] is True
    assert gateways[0]["free_models"] == ["a:free"]
    assert gateways[0]["label"] == "openrouter"


def test_keyless_gateway_has_no_key(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [{"id": "llm7", "base_url": "https://api.llm7.io/v1", "needs_key": False,
          "free_models": ["DeepSeek-V4-Flash-0731"]}],
    )
    gateways = load_gateways(tmp_path, env={})

    assert gateways[0]["needs_key"] is False
    assert gateways[0]["has_key"] is False
    assert gateways[0]["api_key"] == ""


def test_api_key_literal_for_keyless(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [{"id": "ollama", "base_url": "http://localhost:11434/v1", "needs_key": False,
          "api_key_literal": "ollama", "free_models": []}],
    )
    gateways = load_gateways(tmp_path, env={})

    # Ollama игнорирует ключ, но клиент OpenAI требует непустой Bearer.
    assert gateways[0]["api_key"] == "ollama"


def test_missing_key_marks_has_key_false(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [{"id": "groq", "base_url": "https://api.groq.com/openai/v1",
          "secret_key": "groq", "needs_key": True, "free_models": ["openai/gpt-oss-120b"]}],
    )
    gateways = load_gateways(tmp_path, env={})

    assert gateways[0]["has_key"] is False
    assert gateways[0]["api_key"] == ""


def test_env_overrides_secrets(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [{"id": "groq", "base_url": "https://api.groq.com/openai/v1",
          "secret_key": "groq", "free_models": ["x"]}],
        {"groq": "from-file"},
    )
    gateways = load_gateways(tmp_path, env={"ZAGENT_GROQ_API_KEY": "from-env"})

    assert gateways[0]["api_key"] == "from-env"


def test_base_url_placeholder_substituted(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [{"id": "cloudflare", "base_url": "https://api.cloudflare.com/x/accounts/{cloudflare_account_id}/ai/v1",
          "secret_key": "cloudflare_token", "free_models": ["@cf/openai/gpt-oss-120b"]}],
        {"cloudflare_token": "cfut-1", "cloudflare_account_id": "acc-42"},
    )
    gateways = load_gateways(tmp_path, env={})

    assert "acc-42" in gateways[0]["resolved_url"]
    assert "{cloudflare_account_id}" not in gateways[0]["resolved_url"]
    # base_url остаётся шаблоном — он идёт в экспортируемые конфиги.
    assert "{cloudflare_account_id}" in gateways[0]["base_url"]


def test_render_base_url_keeps_unknown_placeholder() -> None:
    assert render_base_url("https://x/{nope}/y", {"a": "b"}) == "https://x/{nope}/y"


def test_render_base_url_without_placeholders() -> None:
    assert render_base_url("https://api.llm7.io/v1", {"a": "b"}) == "https://api.llm7.io/v1"


def test_catalog_mode_defaults(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {"id": "static_gw", "base_url": "https://a/v1", "free_models": ["m1"]},
            {"id": "live_gw", "base_url": "https://b/v1", "free_models": []},
        ],
    )
    gateways = load_gateways(tmp_path, env={})

    by_id = {g["id"]: g for g in gateways}
    assert by_id["static_gw"]["catalog"] == ["static"]
    assert by_id["live_gw"]["catalog"] == ["live"]


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {"id": "dup", "base_url": "https://a/v1", "free_models": ["x"]},
            {"id": "dup", "base_url": "https://b/v1", "free_models": ["y"]},
        ],
    )
    with pytest.raises(ConfigError, match="дважды"):
        load_gateways(tmp_path, env={})


def test_missing_base_url_rejected(tmp_path: Path) -> None:
    write_config(tmp_path, [{"id": "no_url", "free_models": ["x"]}])
    with pytest.raises(ConfigError, match="base_url"):
        load_gateways(tmp_path, env={})


def test_missing_id_rejected(tmp_path: Path) -> None:
    write_config(tmp_path, [{"base_url": "https://a/v1", "free_models": ["x"]}])
    with pytest.raises(ConfigError, match="не задан id"):
        load_gateways(tmp_path, env={})


def test_empty_gateways_rejected(tmp_path: Path) -> None:
    write_config(tmp_path, [])
    with pytest.raises(ConfigError, match="пуст или отсутствует"):
        load_gateways(tmp_path, env={})


def test_missing_file_reports_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="gateways.json"):
        load_gateways(tmp_path, env={})


def test_free_models_must_be_list(tmp_path: Path) -> None:
    write_config(tmp_path, [{"id": "x", "base_url": "https://a/v1", "free_models": "oops"}])
    with pytest.raises(ConfigError, match="free_models"):
        load_gateways(tmp_path, env={})


def test_gateway_by_id(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {"id": "a", "base_url": "https://a/v1", "free_models": ["x"]},
            {"id": "b", "base_url": "https://b/v1", "free_models": ["y"]},
        ],
    )
    gateways = load_gateways(tmp_path, env={})

    assert gateway_by_id(gateways, "b")["id"] == "b"
    with pytest.raises(ConfigError, match="Неизвестный шлюз"):
        gateway_by_id(gateways, "zzz")


def test_gateways_with_key_includes_keyless(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        [
            {"id": "keyless", "base_url": "https://a/v1", "needs_key": False, "free_models": ["x"]},
            {"id": "keyed_missing", "base_url": "https://b/v1", "secret_key": "nope",
             "needs_key": True, "free_models": ["y"]},
        ],
    )
    gateways = load_gateways(tmp_path, env={})

    usable = {g["id"] for g in gateways_with_key(gateways)}
    assert usable == {"keyless"}


def test_resolve_secret_empty_name() -> None:
    assert resolve_secret(None) == ""
    assert resolve_secret("") == ""


def test_secret_file_absent_is_ok(tmp_path: Path) -> None:
    write_config(tmp_path, [{"id": "x", "base_url": "https://a/v1", "free_models": ["m"]}])
    gateways = load_gateways(tmp_path, env={})
    assert gateways[0]["has_key"] is False


def test_real_project_config_loads() -> None:
    """Шаблон репозитория должен оставаться валидным."""
    root = Path(__file__).resolve().parent.parent
    gateways = load_gateways(root, env={})

    ids = {g["id"] for g in gateways}
    assert "openrouter" in ids
    assert "llm7" in ids
    # keyless-шлюз обязан работать без ключа
    llm7 = next(g for g in gateways if g["id"] == "llm7")
    assert llm7["needs_key"] is False
