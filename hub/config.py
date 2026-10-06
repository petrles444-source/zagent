"""Загрузка конфигурации из config/*.json.

Все модели и роли берутся из файлов, в коде они не хардкодятся.
Порядок поиска ключа: переменная окружения ZEN_API_KEY, затем
config/secrets.local.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIRNAME = "config"
MODELS_FILE = "models.json"
GATEWAYS_FILE = "gateways.json"
SECRETS_FILE = "secrets.local.json"

#: Префикс переменных окружения для ключей шлюзов.
#: Ключ шлюза "openrouter" можно задать как OPENROUTER_API_KEY.
ENV_PREFIX = "ZAGENT_"
ENV_KEY = ENV_PREFIX + "ZEN_API_KEY"

NO_KEY_MESSAGE = "Ключи не заданы. Создайте config/secrets.local.json"

#: Подстановки вида {cloudflare_account_id} в base_url берутся из secrets.
PLACEHOLDER_PREFIX = "{"


class ConfigError(RuntimeError):
    """Ошибка чтения или проверки конфигурации."""


def project_root() -> Path:
    """Корень проекта (папка, содержащая config/, hub/, providers/, tools/)."""
    return Path(__file__).resolve().parent.parent


def config_dir(root: str | Path | None = None) -> Path:
    return (Path(root) if root is not None else project_root()) / CONFIG_DIRNAME


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Не найден файл конфигурации: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Некорректный JSON в {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Ожидался объект JSON в {path}")
    return data


def load_models(root: str | Path | None = None) -> dict[str, Any]:
    """Прочитать config/models.json.

    Возвращает {"base_url": str, "models": [{"id": str, "label": str}, ...]}.
    """
    path = config_dir(root) / MODELS_FILE
    data = _read_json(path)

    base_url = str(data.get("base_url") or "").strip()
    if not base_url:
        raise ConfigError(f"В {path} не задан base_url")

    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ConfigError(f"В {path} список models пуст или отсутствует")

    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_models):
        if not isinstance(item, dict):
            raise ConfigError(f"В {path} элемент models[{index}] должен быть объектом")
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            raise ConfigError(f"В {path} у models[{index}] не задан id")
        if model_id in seen:
            raise ConfigError(f"В {path} модель {model_id} указана дважды")
        seen.add(model_id)
        models.append({"id": model_id, "label": str(item.get("label") or model_id).strip()})

    return {"base_url": base_url, "models": models}


def load_secrets(root: str | Path | None = None) -> dict[str, Any]:
    """Прочитать config/secrets.local.json. Отсутствие файла — не ошибка."""
    path = config_dir(root) / SECRETS_FILE
    if not path.is_file():
        return {}
    return _read_json(path)


def _env_name(gateway_id: str) -> str:
    """Имя переменной окружения для шлюза: openrouter -> ZAGENT_OPENROUTER_API_KEY."""
    return ENV_PREFIX + gateway_id.upper().replace("-", "_") + "_API_KEY"


def resolve_secret(
    name: str | None,
    *,
    root: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Первый ключ из секрета по имени.

    Историческая функция: возвращает один ключ. Для шлюзов с несколькими
    ключами используйте resolve_keys — иначе девять аккаунтов OpenRouter
    будут работать как один, и лимит выбьет по первому же.
    """
    keys = resolve_keys(name, root=root, env=env)
    return keys[0] if keys else ""


def resolve_keys(
    name: str | None,
    *,
    root: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Все ключи секрета.

    Значение может быть строкой (один ключ, как было раньше) или списком
    строк (несколько аккаунтов одного провайдера). Список — норма для
    провайдеров с лимитом на аккаунт: у OpenRouter 50 запросов в сутки на
    аккаунт, и девять аккаунтов дают в девять раз больше работы, чем один.

    Приоритет тот же, что у одного ключа: переменная окружения, затем файл
    секретов. Переменная окружения всегда даёт один ключ — это осознанно:
    окружение нужно для CI, где секреты не лежат файлом.
    """
    if not name:
        return []
    environ = os.environ if env is None else env
    from_env = str(environ.get(_env_name(name)) or "").strip()
    if from_env:
        return [from_env]
    return _keys_from_value(load_secrets(root).get(name))


def _keys_from_value(value: Any) -> list[str]:
    """Привести значение секрета к списку ключей без пустых и повторов.

    Повторы убираются: иначе девять одинаковых записей выглядели бы как девять
    аккаунтов, а квота была бы одна.
    """
    if value is None:
        return []
    raw: list[Any]
    if isinstance(value, str):
        # Многострочная строка тоже принимается: ключи часто вставляют
        # списком в текстовом виде.
        raw = value.replace(",", "\n").splitlines() if "\n" in value or "," in value else [value]
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = [value]

    keys: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        keys.append(text)
    return keys


def render_base_url(base_url: str, secrets: dict[str, Any]) -> str:
    """Подставить {placeholder} в base_url значениями из секретов.

    Неизвестный placeholder оставляем как есть, чтобы ошибка была видна.
    """
    text = str(base_url or "")
    if PLACEHOLDER_PREFIX not in text:
        return text
    result = text
    for key, value in secrets.items():
        token = PLACEHOLDER_PREFIX + str(key) + "}"
        if token in result:
            result = result.replace(token, str(value or ""))
    return result


def load_gateways(
    root: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Прочитать config/gateways.json и дополнить каждый шлюз полями:

        api_key       — ключ из env или secrets (пусто для keyless)
        resolved_url  — base_url с подставленными секретами
        has_key       — задан ли ключ
        catalog       — ["static"] | ["live"] | ["static", "live"]

    Проверяет уникальность id и наличие base_url.
    """
    path = config_dir(root) / GATEWAYS_FILE
    data = _read_json(path)

    raw = data.get("gateways")
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"В {path} список gateways пуст или отсутствует")

    secrets = load_secrets(root)
    gateways: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigError(f"В {path} элемент gateways[{index}] должен быть объектом")

        gateway_id = str(item.get("id") or "").strip()
        if not gateway_id:
            raise ConfigError(f"В {path} у gateways[{index}] не задан id")
        if gateway_id in seen:
            raise ConfigError(f"В {path} шлюз '{gateway_id}' указан дважды")
        seen.add(gateway_id)

        base_url = str(item.get("base_url") or "").strip()
        if not base_url:
            raise ConfigError(f"В {path} у шлюза '{gateway_id}' не задан base_url")

        needs_key = bool(item.get("needs_key"))
        # Имя секрета по умолчанию совпадает с id шлюза: "groq" -> secrets["groq"].
        # Явный "secret_key": null означает «ключ не предусмотрен» (keyless-шлюз).
        secret_name = item["secret_key"] if "secret_key" in item else gateway_id
        api_keys: list[str] = []
        if secret_name:
            api_keys = resolve_keys(str(secret_name), root=root, env=env)
        if not api_keys:
            # Шлюз без своего секрета может использовать литерал (Ollama: "ollama").
            literal = str(item.get("api_key_literal") or "").strip()
            if literal:
                api_keys = [literal]
        # Первый ключ оставлен для совместимости со всем, что читает api_key.
        # Новый код должен брать api_keys и выбирать по кругу.
        api_key = api_keys[0] if api_keys else ""

        free_models = item.get("free_models")
        if free_models is not None and not isinstance(free_models, list):
            raise ConfigError(f"В {path} у шлюза '{gateway_id}' free_models должен быть списком")

        entry = dict(item)
        entry.update(
            id=gateway_id,
            label=str(item.get("label") or gateway_id).strip(),
            base_url=base_url,
            resolved_url=render_base_url(base_url, secrets),
            api_key=api_key,
            # Все ключи этого шлюза. У провайдеров с лимитом на аккаунт их
            # несколько, и запросы надо разбрасывать между ними.
            api_keys=api_keys,
            key_count=len(api_keys),
            needs_key=needs_key,
            has_key=bool(api_key),
            free_models=[str(m).strip() for m in (free_models or []) if str(m).strip()],
            catalog=list(item.get("catalog") or _default_catalog(item)),
            discover_live=bool(item.get("discover_live")),
        )
        gateways.append(entry)

    return gateways


def _default_catalog(item: dict[str, Any]) -> list[str]:
    """Каталог по умолчанию: static для готового списка, live для шлюзов с /models."""
    if item.get("free_models"):
        return ["static"]
    return ["live"]


def gateway_by_id(gateways: list[dict[str, Any]], gateway_id: str) -> dict[str, Any]:
    for item in gateways:
        if item.get("id") == gateway_id:
            return item
    known = ", ".join(str(g.get("id")) for g in gateways) or "нет"
    raise ConfigError(f"Неизвестный шлюз '{gateway_id}'. Доступные: {known}")


def gateways_with_key(gateways: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Только шлюзы, у которых ключ реально задан."""
    return [g for g in gateways if g.get("has_key") or not g.get("needs_key")]


def load_api_key(
    root: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Ключ Zen (legacy). Приоритет: ZAGENT_ZEN_API_KEY, затем secrets.zen_api_key."""
    environ = os.environ if env is None else env
    from_env = str(environ.get(ENV_KEY) or "").strip()
    if from_env:
        return from_env
    value = load_secrets(root).get("zen_api_key")
    return str(value or "").strip()


def model_label(models: list[dict[str, str]], model_id: str) -> str:
    """Человекочитаемая метка модели (или сам id, если не найдена)."""
    for item in models:
        if item.get("id") == model_id:
            return item.get("label") or model_id
    return model_id
