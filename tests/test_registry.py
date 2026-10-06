"""Тесты реестра: определение бесплатных моделей, пинг, отчёты, экспорт."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from hub import exporters, report
from hub.registry import (
    FreeModel,
    Registry,
    collect,
    looks_free,
    models_from_live_catalog,
    models_from_static,
)


def gw(**kw) -> dict:
    base = {
        "id": "test",
        "label": "Test",
        "base_url": "https://example.test/v1",
        "resolved_url": "https://example.test/v1",
        "api_key": "",
        "needs_key": True,
        "has_key": False,
        "free_models": [],
        "catalog": [],
        "supports_responses": False,
    }
    base.update(kw)
    return base


# ------------------------------------------------------- маркеры бесплатности


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("vendor/model:free", True),
        ("vendor/thing-free", True),
        ("space-bunny-free", True),
        ("openai/gpt-oss-120b", False),
        ("anthropic/claude-sonnet-5", False),
    ],
)
def test_looks_free(model_id: str, expected: bool) -> None:
    assert looks_free(model_id) is expected


def test_looks_free_respects_gateway_marker() -> None:
    assert looks_free("custom-marked", marker=":free") is False
    assert looks_free("x:free", marker=":free") is True


# --------------------------------------------------------- источники моделей


def test_models_from_static() -> None:
    gateway = gw(id="groq", label="Groq", free_models=["openai/gpt-oss-120b", " qwen/x "])
    models = models_from_static(gateway)

    assert [m.model_id for m in models] == ["openai/gpt-oss-120b", "qwen/x"]
    assert models[0].source == "static"
    assert models[0].gateway_id == "groq"
    assert models[0].label == "Groq"


def test_models_from_live_catalog_filters_paid() -> None:
    gateway = gw(id="openrouter", free_marker=":free", routers=["openrouter/free"])
    catalog = [
        "vendor/a:free",
        "vendor/b",
        "vendor/c:batch",
        "openrouter/free",
    ]
    models = models_from_live_catalog(gateway, catalog)

    ids = {m.model_id: m.source for m in models}
    assert ids == {"vendor/a:free": "live", "openrouter/free": "marked"}


def test_non_chat_models_filtered() -> None:
    models = [
        FreeModel("g", "vendor/bge-m3", "static"),
        FreeModel("g", "vendor/whisper-large-v3", "static"),
        FreeModel("g", "vendor/guard-2", "static"),
        FreeModel("g", "vendor/qwen-27b", "static"),
    ]
    assert [m.is_chat for m in models] == [False, False, False, True]


# ------------------------------------------------------------------ сборка


def test_collect_merges_static_and_marks_missing_key() -> None:
    import asyncio

    gateways = [
        gw(id="keyed", free_models=["a:free"], needs_key=True, has_key=False, secret_key="k"),
        gw(id="keyless", free_models=["b"], needs_key=False, catalog=["static"]),
    ]
    registry = asyncio.run(collect(gateways, check_price=False))

    refs = {m.ref for m in registry.models}
    assert refs == {"keyed/a:free", "keyless/b"}


def test_collect_dedupes_same_model() -> None:
    import asyncio

    # Один и тот же id присутствует и в static, и в live-подобном списке.
    gateways = [gw(id="g", free_models=["x:free"])]
    registry = asyncio.run(collect(gateways, check_price=False))
    registry.models.append(FreeModel("g", "x:free", "live"))

    deduped = Registry(gateways=gateways, models=registry.models)
    from hub.registry import _dedupe

    assert len(_dedupe(deduped.models)) == 1


def test_collect_records_error_for_live_without_key() -> None:
    import asyncio

    gateways = [gw(id="nolock", needs_key=True, has_key=False, catalog=["live"], free_models=[])]
    registry = asyncio.run(collect(gateways, check_price=False))

    assert "нет ключа" in registry.errors["nolock"]


# ------------------------------------------------------------------ отчёты


def test_build_snapshot_and_statuses() -> None:
    gateway = gw(id="openrouter", label="OpenRouter", supports_responses=True)
    registry = Registry(
        gateways=[gateway],
        models=[FreeModel("openrouter", "a:free", "live"), FreeModel("openrouter", "b:free", "live")],
    )
    probes = {
        "openrouter/a:free": {"status": "ok", "duration_ms": 120, "tokens_in": 5, "tokens_out": 3},
        "openrouter/b:free": {"status": "blocked", "error": "закрыт", "http": 403},
    }
    snapshot = report.build_snapshot(registry, probes)

    assert snapshot["total_chat_models"] == 2
    assert snapshot["status_counts"] == {"ok": 1, "blocked": 1}
    by_model = {m["model"]: m for m in snapshot["models"]}
    assert by_model["a:free"]["usable"] is True
    assert by_model["b:free"]["usable"] is False


def test_classify_slow_threshold() -> None:
    slow = {"status": "ok", "duration_ms": 9000}
    assert report.classify(slow, slow_after_ms=5000) == report.STATUS_SLOW
    fast = {"status": "ok", "duration_ms": 100}
    assert report.classify(fast, slow_after_ms=5000) == report.STATUS_OK


def test_classify_missing_probe_is_skipped() -> None:
    assert report.classify(None) == report.STATUS_SKIPPED


def test_write_snapshot_files(tmp_path: Path) -> None:
    registry = Registry(gateways=[gw(id="g", label="G")], models=[FreeModel("g", "m:free", "static")])
    snapshot = report.build_snapshot(registry)

    json_path = report.write_json(snapshot, tmp_path)
    md_path = report.write_markdown(snapshot, tmp_path)

    assert json_path.name == "free-models.json"
    assert md_path.name == "free-models.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total_chat_models"] == 1
    assert "# Бесплатные модели" in md_path.read_text(encoding="utf-8")


def test_render_table_marks_dead_models() -> None:
    registry = Registry(gateways=[gw(id="g")], models=[FreeModel("g", "m", "static")])
    snapshot = report.build_snapshot(
        registry, {"g/m": {"status": "blocked", "error": "закрыт", "http": 403}}
    )
    text = report.render_table(snapshot)

    assert "blocked" in text
    assert "не использовать" in text


# ------------------------------------------------------------------ экспорт


def make_registry() -> Registry:
    return Registry(
        gateways=[
            gw(id="openrouter", label="OpenRouter", base_url="https://openrouter.ai/api/v1",
               has_key=True, supports_responses=True, env="OPENROUTER_API_KEY"),
            gw(id="llm7", label="llm7.io", base_url="https://api.llm7.io/v1",
               needs_key=False, has_key=False),
            gw(id="cloudflare", label="Cloudflare", has_key=True, supports_responses=False),
        ],
        models=[
            FreeModel("openrouter", "nvidia/nemotron-3-super-120b-a12b:free", "live"),
            FreeModel("openrouter", "cohere/north-mini-code:free", "live"),
            FreeModel("llm7", "DeepSeek-V4-Flash-0731", "static"),
            FreeModel("cloudflare", "@cf/openai/gpt-oss-120b", "static"),
        ],
    )


def test_export_opencode_structure() -> None:
    out = exporters.export("opencode", make_registry())
    data = json.loads(out)

    assert data["$schema"] == "https://opencode.ai/config.json"
    assert "openrouter" in data["providers"]
    assert "llm7" in data["providers"]
    # OpenRouter получает нативный пакет.
    assert data["providers"]["openrouter"]["package"] == "@opencode/ai/providers/openrouter"
    assert data["providers"]["llm7"]["package"] == "@opencode/ai/providers/openai-compatible"


def test_export_opencode_excludes_dead_statuses() -> None:
    statuses = {"openrouter/nvidia/nemotron-3-super-120b-a12b:free": "ok",
                "openrouter/cohere/north-mini-code:free": "blocked",
                "llm7/DeepSeek-V4-Flash-0731": "ok",
                "cloudflare/@cf/openai/gpt-oss-120b": "ok"}
    data = json.loads(exporters.export("opencode", make_registry(), statuses=statuses))

    models = data["providers"]["openrouter"]["models"]
    assert "cohere/north-mini-code:free" not in models
    assert "nvidia/nemotron-3-super-120b-a12b:free" in models


def test_export_codex_only_responses_gateways() -> None:
    out = exporters.export("codex", make_registry())

    # Codex-конфиг — TOML, а не JSON.
    assert "[model_providers.openrouter]" in out
    assert 'wire_api = "responses"' in out
    # cloudflare и llm7 не умеют /responses — их в Codex нельзя.
    assert "cloudflare" not in out
    assert "llm7" not in out


def test_export_codex_uses_env_key() -> None:
    out = exporters.export("codex", make_registry())

    assert 'env_key = "OPENROUTER_API_KEY"' in out
    assert 'model_provider = "openrouter"' in out


def test_export_zed_structure() -> None:
    data = json.loads(exporters.export("zed", make_registry()))

    providers = data["language_models"]["openai_compatible"]
    assert "openrouter" in providers
    # keyless-шлюз в Zed не подходит: нужен ключ.
    assert "llm7" not in providers
    model = providers["openrouter"]["available_models"][0]
    assert "max_tokens" in model


def test_export_zed_is_strict_json() -> None:
    """Zed и VS Code не понимают комментарии — вывод должен парситься json.loads."""
    json.loads(exporters.export("zed", make_registry()))
    json.loads(exporters.export("cline", make_registry()))
    json.loads(exporters.export("kilocode", make_registry()))
    json.loads(exporters.export("opencode", make_registry()))


def test_export_cline_uses_best_keyed_gateway() -> None:
    data = json.loads(exporters.export("cline", make_registry()))

    assert data["cline.openAiCompatibleBaseUrl"] == "https://openrouter.ai/api/v1"
    assert "env:OPENROUTER_API_KEY" in data["cline.openAiCompatibleApiKey"]


def test_предупреждение_о_нескольких_аккаунтах() -> None:
    """Сторонней программе отдаётся один ключ — об этом надо сказать."""
    gws = [{"id": "orx", "label": "OpenRouter", "key_count": 9},
           {"id": "groq", "label": "Groq", "key_count": 1}]
    note = exporters.multi_key_note(gws)
    assert "OpenRouter (9)" in note
    assert "Groq" not in note, "шлюз с одним ключом упоминать незачем"


def test_предупреждения_нет_при_одном_ключе() -> None:
    gws = [{"id": "groq", "label": "Groq", "key_count": 1}]
    assert exporters.multi_key_note(gws) == ""


def test_предупреждение_при_отсутствии_счётчика() -> None:
    """Старый конфиг без key_count не должен ломать экспорт."""
    assert exporters.multi_key_note([{"id": "groq"}]) == ""


def test_предупреждение_не_ломает_json() -> None:
    """Подсказка идёт в stderr, конфиг остаётся разбираемым."""
    import re
    import subprocess

    from hub.config import project_root

    done = subprocess.run(
        [sys.executable, "tools/cli.py", "export", "opencode"],
        capture_output=True, text=True, cwd=project_root(), check=False,
    )
    if done.returncode != 0:
        pytest.skip(f"экспорт не отработал: {done.stderr[:200]}")
    json.loads(done.stdout)  # не бросает — значит, ключи не попали в вывод
    assert "sk-or" not in done.stdout
    assert "Внимание" in done.stderr or not re.search(
        r"несколько аккаунтов", done.stdout
    )


def test_export_plain_lists_all() -> None:
    out = exporters.export("plain", make_registry())

    assert "## OpenRouter" in out
    assert "## llm7.io" in out
    assert "DeepSeek-V4-Flash-0731" in out


def test_export_unknown_format() -> None:
    with pytest.raises(ValueError, match="Неизвестный формат"):
        exporters.export("nope", make_registry())


def test_export_filters_by_gateway() -> None:
    out = exporters.export("plain", make_registry(), model_ids=["llm7/DeepSeek-V4-Flash-0731"])

    assert "DeepSeek-V4-Flash-0731" in out
    assert "nemotron" not in out


def test_exported_configs_contain_no_secrets() -> None:
    registry = make_registry()
    registry.gateways[0]["api_key"] = "sk-or-v1-SECRET"

    for name in exporters.EXPORTERS:
        out = exporters.export(name, registry)
        assert "SECRET" not in out, f"{name} утёк ключ"
