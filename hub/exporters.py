"""Экспорт реестра в конфиги других инструментов.

Каждый экспортёр берёт список бесплатных моделей и выдаёт готовый конфиг:

    opencode — opencode.jsonc (V2: providers + models)
    codex    — ~/.codex/config.toml (model_providers, wire_api = responses)
    zed      — Zed settings.json (language_models.openai_compatible)
    cline    — VS Code settings.json (cline.openAiCompatibleBaseUrl и т.д.)
    kilnocode— Kilo Code / Roo Code (аналогично cline)
    agents   — список моделей текстом для ручного вставления

Ключи в экспорт НЕ попадают: вместо них используются имена переменных окружения.
"""

from __future__ import annotations

import json
from typing import Any

from hub.registry import Registry

#: Инструменты, требующие /responses вместо /chat/completions.
RESPONSES_ONLY = "responses"

#: Статусы, при которых модель не имеет смысла переносить в редактор.
DEAD_STATUSES = ("blocked", "down")


def _env(gateway: dict[str, Any]) -> str:
    """Имя переменной окружения с ключом шлюза.

    Берется из конфига шлюза: там имена уже заданы в том виде, в каком их
    ожидают сторонние инструменты (OPENROUTER_API_KEY, GROQ_API_KEY).
    Префикс ZAGENT_ используется только как запасной вариант.
    """
    explicit = gateway.get("env")
    if explicit:
        return str(explicit)
    return "ZAGENT_" + str(gateway["id"]).upper().replace("-", "_") + "_API_KEY"


def _codex_eligible(gateway: dict[str, Any]) -> bool:
    """Codex умеет только Responses API — фильтруем шлюзы без него."""
    return bool(gateway.get("supports_responses"))


def _keyed(gateways: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Только шлюзы, у которых реально есть ключ (для экспорта в IDE)."""
    return [g for g in gateways if g.get("has_key")]


#: Контекст по умолчанию, если шлюз не отдал context_length.
DEFAULT_CONTEXT = 128000


def _opencode_model(model: Any) -> dict[str, Any]:
    """Описание модели для OpenCode: имя, контекст и поддержка инструментов.

    limit.context обязателен, иначе OpenCode не знает, сколько токенов влезает
    в запрос, и обрезает контекст по своим умолчаниям.
    """
    entry: dict[str, Any] = {"name": model.model_id}
    context = model.context or DEFAULT_CONTEXT
    entry["limit"] = {
        "context": context,
        "output": max(4096, min(context // 4, 32768)),
    }
    # Эти шлюзы — агрегаторы чат-моделей; tool calling поддерживают.
    if model.is_chat and not model.model_id.startswith("@cf/"):
        entry["capabilities"] = {"tools": True}
    return entry


# ------------------------------------------------------------------ OpenCode


def export_opencode(
    registry: Registry, *, model_ids: list[str] | None = None, statuses: dict[str, str] | None = None
) -> str:
    """opencode.jsonc для OpenCode V2.

    Шлюз OpenRouter получает нативный пакет @opencode/ai/providers/openrouter,
    остальные — @opencode/ai/providers/openai-compatible.

    statuses: снимок из ping (ref -> status). Если передан, модели со статусом
    blocked/down в конфиг не попадают — их вставлять в редактор бессмысленно.
    """
    if statuses is not None:
        keep = {ref for ref, status in statuses.items() if status not in DEAD_STATUSES}
        model_ids = sorted(keep if model_ids is None else set(model_ids) & keep)

    by_gateway: dict[str, list[Any]] = {}
    for model in registry.chat_models:
        if model_ids is not None and model.ref not in model_ids:
            continue
        by_gateway.setdefault(model.gateway_id, []).append(model)

    providers: dict[str, Any] = {}
    for gateway in registry.gateways:
        models = by_gateway.get(gateway["id"])
        if not models:
            continue
        gid = gateway["id"].replace("_", "-")
        entry: dict[str, Any] = {
            "name": gateway.get("label", gateway["id"]),
            "package": "@opencode/ai/providers/openai-compatible",
            "models": {},
        }
        if gateway["id"] == "openrouter":
            entry["package"] = "@opencode/ai/providers/openrouter"
        if gateway.get("api_key"):
            entry["env"] = [_env(gateway)]
        entry["settings"] = {"baseURL": gateway["base_url"]}
        for model in models:
            entry["models"][model.model_id] = _opencode_model(model)
        providers[gid] = entry

    config: dict[str, Any] = {"$schema": "https://opencode.ai/config.json"}
    if providers:
        first = next(iter(providers))
        first_model = next(iter(providers[first]["models"]))
        config["model"] = f"{first}/{first_model}"
    config["providers"] = providers
    return _jsonc(config)


# ---------------------------------------------------------------------- Codex


def export_codex(
    registry: Registry, *, model_ids: list[str] | None = None, statuses: dict[str, str] | None = None
) -> str:
    """Фрагмент ~/.codex/config.toml.

    Codex требует Responses API, поэтому шлюзы без supports_responses отбрасываются.
    """
    if statuses is not None:
        keep = {ref for ref, status in statuses.items() if status not in DEAD_STATUSES}
        model_ids = sorted(keep if model_ids is None else set(model_ids) & keep)

    by_gateway: dict[str, list[Any]] = {}
    for model in registry.chat_models:
        if model_ids is not None and model.ref not in model_ids:
            continue
        gateway = next((g for g in registry.gateways if g["id"] == model.gateway_id), None)
        if gateway is None or not _codex_eligible(gateway):
            continue
        by_gateway.setdefault(gateway["id"], []).append(model)

    lines = [
        "# zagent export — Codex CLI",
        "# Только шлюзы с поддержкой Responses API (wire_api = \"responses\").",
        "# Ключи задаются переменными окружения, имена указаны в env_key.",
        "",
    ]
    if not by_gateway:
        lines.append("# Нет шлюзов с /responses среди проверенных.")
        return "\n".join(lines) + "\n"

    lines.append('model_provider = "%s"' % next(iter(by_gateway)))
    first_models = by_gateway[next(iter(by_gateway))]
    lines.append('model = "%s"' % first_models[0].model_id)
    lines.append("")

    for gateway_id, models in by_gateway.items():
        gateway = next(g for g in registry.gateways if g["id"] == gateway_id)
        table = gateway_id.replace("-", "_")
        lines.append(f"[model_providers.{table}]")
        lines.append(f'name = "{gateway.get("label", gateway_id)}"')
        lines.append(f'base_url = "{gateway["base_url"]}"')
        lines.append(f'env_key = "{_env(gateway)}"')
        lines.append(f'wire_api = "{RESPONSES_ONLY}"')
        lines.append("")
        lines.append(f"# Модели этого шлюза: {', '.join(m.model_id for m in models)}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------ Zed


def export_zed(
    registry: Registry, *, model_ids: list[str] | None = None, statuses: dict[str, str] | None = None
) -> str:
    """Фрагмент Zed settings.json (language_models.openai_compatible)."""
    if statuses is not None:
        keep = {ref for ref, status in statuses.items() if status not in DEAD_STATUSES}
        model_ids = sorted(keep if model_ids is None else set(model_ids) & keep)

    providers: dict[str, Any] = {}
    for model in registry.chat_models:
        if model_ids is not None and model.ref not in model_ids:
            continue
        gateway = next((g for g in registry.gateways if g["id"] == model.gateway_id), None)
        if gateway is None or not gateway.get("has_key"):
            continue
        pid = gateway["id"].replace("_", "-")
        entry = providers.setdefault(pid, {"api_url": gateway["base_url"], "available_models": []})
        entry["available_models"].append(
            {
                "name": model.model_id,
                "display_name": model.model_id,
                "max_tokens": model.context or DEFAULT_CONTEXT,
            }
        )

    config = {"language_models": {"openai_compatible": providers}}
    # Чистый JSON без комментариев: Zed и VS Code не понимают JSONC.
    # Подсказка про переменные окружения уходит отдельной строкой в stderr.
    return json.dumps(config, ensure_ascii=False, indent=2)


#: Подсказка по ключам для Zed — печатается в stderr, чтобы не ломать JSON.
ZED_KEY_HINT = (
    "Ключи Zed берёт из переменных окружения: имя = ID провайдера в верхнем "
    "snake_case + _API_KEY (OPENROUTER_API_KEY, CLOUDFLARE_API_TOKEN и т.п.). "
    "В settings.json ключи не пишутся."
)


def multi_key_note(gateways: list[dict[str, Any]]) -> str:
    """Предупреждение о нескольких аккаунтах, если они есть.

    Экспорт отдаёт наружу один ключ на шлюз, а у OpenRouter их теперь девять.
    Молча отдав первый, мы получили бы в чужом инструменте ровно ту квоту,
    ради которой ушли от одного аккаунта, — остальные девять работали бы впустую.
    Поэтому говорим прямо: в сторонней программе ключ один.
    """
    multi = [g for g in gateways if int(g.get("key_count") or 0) > 1]
    if not multi:
        return ""
    names = ", ".join(
        f"{g.get('label', g['id'])} ({g['key_count']})" for g in multi
    )
    return (
        f"\nВнимание: у {len(multi)} шлюзов несколько аккаунтов — {names}. "
        "Экспорт отдаёт один ключ на шлюз, поэтому сторонняя программа "
        "будет работать с лимитом одного аккаунта, а не всех сразу."
    )


# --------------------------------------------------------- Cline / Roo / Kilo


def export_cline(registry: Registry, *, model_ids: list[str] | None = None) -> str:
    """Фрагмент VS Code settings.json для Cline / Roo Code / Kilo Code.

    Эти расширения берут один OpenAI-совместимый endpoint, поэтому берём лучший
    доступный шлюз (по умолчанию OpenRouter: много моделей, Responses API есть).
    """
    preferred = _preferred_gateway(registry, model_ids)
    if preferred is None:
        return '{\n  // Нет шлюза с ключом для Cline.\n}\n'
    gateway, models = preferred

    settings: dict[str, Any] = {
        "cline.openAiCompatibleBaseUrl": gateway["base_url"],
        "cline.openAiCompatibleApiKey": f"${{env:{_env(gateway)}}}",
        "cline.openAiCompatibleModelId": models[0].model_id,
        "cline.vsCodeSettingGeneration": "EMBEDDED",
        "cline.useAutocomplete": True,
    }
    return json.dumps(settings, ensure_ascii=False, indent=2)


def export_kilocode(registry: Registry, *, model_ids: list[str] | None = None) -> str:
    """Фрагмент VS Code settings.json для Kilo Code."""
    preferred = _preferred_gateway(registry, model_ids)
    if preferred is None:
        return '{\n  // Нет шлюза с ключом для Kilo Code.\n}\n'
    gateway, models = preferred
    settings = {
        "kilocode.vscodeLmApiBaseUrl": gateway["base_url"],
        "kilocode.vscodeLmApiKey": f"${{env:{_env(gateway)}}}",
        "kilocode.vscodeLmModelSelector": models[0].model_id,
    }
    return json.dumps(settings, ensure_ascii=False, indent=2)


def _preferred_gateway(
    registry: Registry, model_ids: list[str] | None
) -> tuple[dict[str, Any], list[Any]] | None:
    """Шлюз с наибольшим числом бесплатных моделей среди тех, где есть ключ."""
    best: tuple[dict[str, Any], list[Any]] | None = None
    for gateway in _keyed(registry.gateways):
        models = [
            m for m in registry.for_gateway(gateway["id"])
            if m.is_chat and (model_ids is None or m.ref in model_ids)
        ]
        if not models:
            continue
        if best is None or len(models) > len(best[1]):
            best = (gateway, models)
    return best


# -------------------------------------------------------------------- список


def export_plain(registry: Registry, *, model_ids: list[str] | None = None) -> str:
    """Плоский список моделей для ручного вставления в любой инструмент."""
    lines = ["# zagent export — список бесплатных моделей", ""]
    current = ""
    for model in registry.chat_models:
        if model_ids and model.ref not in model_ids:
            continue
        if model.gateway_id != current:
            current = model.gateway_id
            gateway = next((g for g in registry.gateways if g["id"] == current), {})
            lines.append(f"## {gateway.get('label', current)}")
            lines.append(f"base_url: {gateway.get('base_url')}")
            if gateway.get("has_key"):
                lines.append(f"api_key: ${{{_env(gateway)}}}")
            lines.append("")
        lines.append(f"- {model.model_id}")
    lines.append("")
    return "\n".join(lines)


EXPORTERS = {
    "opencode": export_opencode,
    "codex": export_codex,
    "zed": export_zed,
    "cline": export_cline,
    "kilocode": export_kilocode,
    "plain": export_plain,
}

#: Экспортёры, принимающие статусы из ping.
STATUS_AWARE = ("opencode", "codex", "zed")


def export(
    name: str,
    registry: Registry,
    *,
    model_ids: list[str] | None = None,
    statuses: dict[str, str] | None = None,
) -> str:
    """Экспорт по имени. Бросает ValueError при неизвестном имени."""
    if name not in EXPORTERS:
        known = ", ".join(sorted(EXPORTERS))
        raise ValueError(f"Неизвестный формат '{name}'. Доступные: {known}")
    func = EXPORTERS[name]
    if name in STATUS_AWARE:
        return func(registry, model_ids=model_ids, statuses=statuses)
    return func(registry, model_ids=model_ids)


def _jsonc(data: dict[str, Any]) -> str:
    """JSON с комментариями-заглушками там, где значения ещё нужно уточнить."""
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body
