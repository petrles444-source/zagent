"""Готовые инструкции: как использовать модели zagent в другом софте.

Смысл модуля один: человек не должен никуда лезть за справкой. Всё, что нужно
для подключения, уже лежит в config/gateways.json и config/secrets.local.json:

    provider id   идентификатор, который вставляется в конфиг инструмента
    base url      адрес шлюза
    api key       ключ из secrets (никогда не показывается целиком в логах)

Каждый инструмент получает свой блок: что нажать, что вставить, куда сохранить.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hub.exporters import DEFAULT_CONTEXT, _env
from hub.keyring import fingerprint
from hub.registry import Registry
from hub.tools import mask_secret


@dataclass
class ConnectInfo:
    """Всё, что нужно для подключения одного шлюза к стороннему софту."""

    gateway: str
    label: str
    base_url: str
    provider_id: str
    api_key: str | None
    env_var: str
    models: list[str] = field(default_factory=list)
    needs_key: bool = True
    supports_responses: bool = False
    keyless: bool = False
    note: str = ""
    error: str | None = None

    def to_dict(self, *, reveal: bool = False) -> dict[str, Any]:
        """Данные для интерфейса.

        Ключ по умолчанию маскируется. Он попадает в DOM страницы, а страница
        тянет шрифты с CDN — при компрометации CDN его скрипт прочитал бы всё,
        что лежит в странице, вместе с ключами провайдеров. Полный ключ
        отдаётся только по прямому действию человека.
        """
        key = self.api_key or ""
        return {
            "gateway": self.gateway,
            "label": self.label,
            "base_url": self.base_url,
            "provider_id": self.provider_id,
            "api_key": key if reveal else mask_secret(key),
            "key_masked": mask_secret(key),
            "key_hint": fingerprint(key),
            "key_count": max(1, len(key)) if key else 0,
            "has_key": bool(key),
            "env_var": self.env_var,
            "models": self.models,
            "needs_key": self.needs_key,
            "supports_responses": self.supports_responses,
            "keyless": self.keyless,
            "note": self.note,
            "error": self.error,
        }


def build_connect_info(registry: Registry) -> list[ConnectInfo]:
    """Собрать подключения по всем шлюзам реестра.

    base_url берётся из конфига шаблоном, с подстановкой {placeholder} при
    необходимости: так пользователь получает то, что вводит вручную.
    """
    out: list[ConnectInfo] = []

    for gateway in registry.gateways:
        gateway_id = gateway["id"]
        models = [m.model_id for m in registry.chat_models if m.gateway_id == gateway_id]
        needs_key = bool(gateway.get("needs_key"))
        has_key = bool(gateway.get("api_key"))

        error = None
        if needs_key and not has_key:
            error = "ключ не задан в config/secrets.local.json"

        out.append(
            ConnectInfo(
                gateway=gateway_id,
                label=str(gateway.get("label") or gateway_id),
                # Шаблонный base_url: пользователь подставит свой account id.
                base_url=str(gateway.get("base_url") or ""),
                provider_id=gateway_id.replace("_", "-"),
                api_key=gateway.get("api_key") if needs_key else None,
                env_var=_env(gateway),
                models=models,
                needs_key=needs_key,
                supports_responses=bool(gateway.get("supports_responses")),
                keyless=not needs_key,
                note=str(gateway.get("notes") or ""),
                error=error,
            )
        )

    return out


# ---------------------------------------------------------------- инструкции


def opencode_block(info: ConnectInfo) -> str:
    """Блок для OpenCode: Custom provider → base URL → ключ → модели."""
    lines = [
        "1. Откройте настройки моделей, добавьте Custom provider (OpenAI-compatible).",
        "2. Заполните поля:",
        f"   Provider ID:  {info.provider_id}",
        f"   Base URL:     {info.base_url}",
        f"   API key:      {info.env_var}  (подставьте свой ключ)",
        "3. Добавьте модели (можно скопировать список кнопкой):",
    ]
    for model in info.models[:8]:
        lines.append(f"   - {model}")
    if len(info.models) > 8:
        lines.append(f"   ... и ещё {len(info.models) - 8}")

    if not info.keyless:
        provider = info.provider_id
        entries = []
        for index, model in enumerate(info.models):
            escaped = model.replace('"', '\\"')
            comma = "," if index < len(info.models) - 1 else ""
            entries.append(f'        "{escaped}": {{"name": "{escaped}"}}{comma}')
        first_model = info.models[0] if info.models else "model-id"
        lines.extend([
            "",
            "Готовый фрагмент opencode.jsonc (вставьте целиком):",
            "{",
            '  "$schema": "https://opencode.ai/config.json",',
            f'  "model": "{provider}/{first_model}",',
            '  "providers": {',
            f'    "{provider}": {{',
            f'      "name": "{info.label}",',
            f'      "env": ["{info.env_var}"],',
            '      "package": "@opencode/ai/providers/openai-compatible",',
            f'      "settings": {{"baseURL": "{info.base_url}"}},',
            '      "models": {',
            *entries,
            "      }",
            "    }",
            "  }",
            "}",
        ])
    return "\n".join(lines)


def deepseek_block(info: ConnectInfo) -> str:
    """Блок для DeepSeek Harness: такой же Custom model API."""
    lines = [
        "1. Plugins / Settings → Models → Custom model API.",
        "2. Заполните форму:",
        f"   Provider ID:  {info.provider_id}",
        f"   Base URL:     {info.base_url}",
        "   Protocol:     OpenAI Chat Completions",
        f"   API key:      {info.env_var}  (свой ключ)",
        "3. Нажмите Add model и внесите id моделей:",
    ]
    for model in info.models[:8]:
        lines.append(f"   - {model}")
    if info.models:
        lines.extend(["", "Быстрый способ — скопировать готовый JSON через кнопку «Экспорт»."])
    return "\n".join(lines)


def codex_block(info: ConnectInfo) -> str:
    """Блок для Codex. Важно: Codex умеет только Responses API."""
    if not info.supports_responses:
        return (
            f"{info.label}: НЕЛЬЗЯ подключить к Codex.\n"
            "У этого шлюза нет эндпоинта /responses, а Codex поддерживает только "
            "его (wire_api = \"responses\"). Используйте OpenCode, Zed или Cline."
        )

    lines = [
        "1. Откройте ~/.codex/config.toml и добавьте секцию:",
        "",
        f'[model_providers.{info.gateway.replace("-", "_")}]',
        f'name = "{info.label}"',
        f'base_url = "{info.base_url}"',
        f'env_key = "{info.env_var}"',
        'wire_api = "responses"',
        "",
        "2. В начале файла выберите провайдера:",
        "",
        f'model_provider = "{info.gateway.replace("-", "_")}"',
        f'model = "{info.models[0] if info.models else "model-id"}"',
    ]
    return "\n".join(lines)


def zed_block(info: ConnectInfo) -> str:
    """Блок для Zed: language_models.openai_compatible."""
    lines = [
        "1. Agent Settings → LLM Providers → Add Provider → OpenAI.",
        "2. Заполните:",
        f"   Provider name:  {info.provider_id}",
        f"   API URL:        {info.base_url}",
        f"   API key env:    {info.env_var}",
        "3. Внесите модели (max_tokens — размер контекста):",
    ]
    if info.models:
        entries = []
        for index, model in enumerate(info.models):
            escaped = model.replace('"', '\\"')
            comma = "," if index < len(info.models) - 1 else ""
            entries.append(
                f'          {{"name": "{escaped}", "display_name": "{escaped}", '
                f'"max_tokens": {DEFAULT_CONTEXT}}}{comma}'
            )
        lines.extend([
            "",
            "Готовый фрагмент settings.json:",
            "{",
            '  "language_models": {',
            '    "openai_compatible": {',
            f'      "{info.provider_id}": {{',
            f'        "api_url": "{info.base_url}",',
            '        "available_models": [',
            *entries,
            "        ]",
            "      }",
            "    }",
            "  }",
            "}",
        ])
    return "\n".join(lines)


def cline_block(info: ConnectInfo) -> str:
    """Блок для Cline / Roo Code / Kilo Code."""
    return "\n".join([
        "1. В настройках расширения выберите провайдера OpenAI Compatible.",
        "2. Заполните:",
        f"   Base URL:  {info.base_url}",
        f"   API Key:   {info.env_var}  (свой ключ)",
        f"   Model ID:  {info.models[0] if info.models else 'model-id'}",
        "",
        "Готовый фрагмент settings.json:",
        "{",
        f'  "cline.openAiCompatibleBaseUrl": "{info.base_url}",',
        f'  "cline.openAiCompatibleApiKey": "${{env:{info.env_var}}}",',
        f'  "cline.openAiCompatibleModelId": "{info.models[0] if info.models else "model-id"}"',
        "}",
    ])


#: Инструменты и функции, собирающие для них инструкцию.
TARGETS = {
    "opencode": opencode_block,
    "deepseek": deepseek_block,
    "codex": codex_block,
    "zed": zed_block,
    "cline": cline_block,
}

TARGET_LABELS = {
    "opencode": "OpenCode",
    "deepseek": "DeepSeek Harness",
    "codex": "Codex CLI",
    "zed": "Zed",
    "cline": "Cline / Roo / Kilo",
}

#: Почему инструмент не подойдёт.
TARGET_REASONS = {
    "codex": "Codex поддерживает только Responses API — шлюзы без /responses не подходят.",
}


def build_guide(registry: Registry) -> dict[str, Any]:
    """Полное руководство по подключению для веб-интерфейса.

    Возвращает список шлюзов с готовыми инструкциями по каждому инструменту.
    Ключи включаются сюда намеренно: пользователь просил видеть их в интерфейсе,
    а сам файл secrets защищён .gitignore.
    """
    connections = build_connect_info(registry)
    targets: dict[str, Any] = {}

    for target, builder in TARGETS.items():
        entries = []
        for info in connections:
            if info.error and info.needs_key:
                # Не показываем инструкцию для шлюза без ключа: она бесполезна.
                entries.append({
                    "gateway": info.gateway,
                    "label": info.label,
                    "available": False,
                    "reason": info.error,
                })
                continue
            if target in TARGET_REASONS and not info.supports_responses:
                entries.append({
                    "gateway": info.gateway,
                    "label": info.label,
                    "available": False,
                    "reason": TARGET_REASONS[target],
                })
                continue
            entries.append({
                "gateway": info.gateway,
                "label": info.label,
                "available": True,
                "base_url": info.base_url,
                "provider_id": info.provider_id,
                "env_var": info.env_var,
                "api_key": mask_secret(info.api_key),
                "key_masked": mask_secret(info.api_key),
                "key_hint": fingerprint(info.api_key or ""),
                "has_key": bool(info.api_key),
                "keyless": info.keyless,
                "models": info.models,
                "instruction": builder(info),
            })
        targets[target] = {
            "label": TARGET_LABELS[target],
            "entries": entries,
        }

    return {
        "connections": [c.to_dict() for c in connections],
        "targets": targets,
        "target_order": list(TARGETS),
    }


def reveal_key(registry: Registry, gateway_id: str) -> dict[str, Any]:
    """Полный ключ одного шлюза — по прямому действию человека.

    Отдельный маршрут вместо параметра в общем ответе: иначе маскирование
    было бы фикцией, а любой вызов `/api/connect` отдавал бы ключи целиком.
    Специально отдаётся один шлюз: весь список ключей в одном ответе — это
    уже не «показать своё», это выгрузка секретов.
    """
    gateway = next((g for g in registry.gateways if g["id"] == gateway_id), None)
    if gateway is None:
        return {"ok": False, "error": f"Шлюз не найден: {gateway_id}"}
    keys = list(gateway.get("api_keys") or [])
    key = keys[0] if keys else str(gateway.get("api_key") or "")
    if not key:
        return {"ok": False, "error": "Ключ не задан"}
    return {
        "ok": True,
        "gateway": gateway_id,
        "label": str(gateway.get("label") or gateway_id),
        "api_key": key,
        "key_count": len(keys),
        "env_var": _env(gateway),
    }
