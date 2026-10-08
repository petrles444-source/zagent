"""Загрузка конфигурации из config/*.json.

Все модели и роли берутся из файлов, в коде они не хардкодятся.
Порядок поиска ключа: переменная окружения ZEN_API_KEY, затем
config/secrets.local.json.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
import uuid
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


# ================================================================ запись
#
# Ниже — то, чего в проекте не было: правка конфигурации из интерфейса.
# Раньше ключи заводили руками в secrets.local.json, а модели — руками в
# gateways.json и tiers.json; вкладка «Настройки» вызывает именно эти
# функции. Правило всех писателей: в ответ не попадают значения — только
# имена полей и счётчики. Ответ уходит в интерфейс, а интерфейс может
# оказаться на скриншоте или в логе.

#: Потолки на запись: ввод приходит из браузера, и враждебная строка не
#: должна раздовать файлы или валить парсер.
MAX_SECRET_NAME = 64
MAX_KEYS_PER_EDIT = 500
MAX_KEY_LENGTH = 512
MAX_SECRETS_FILE = 128 * 1024

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-\[\]]{0,199}$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")

#: Шлюзы, у которых `secret_key: null`, но ключ всё-таки читается особым
#: legacy-путём (load_api_key): имя поля в файле и переменная окружения.
#: Без этого zen не получит поля для ввода — в файле он лежит под
#: zen_api_key, а переменная у него своя (не _env_name, тот добавил бы
#: второй _API_KEY к уже готовому имени).
_LEGACY_SECRET = {"zen": ("zen_api_key", ENV_KEY)}


class ConfigWriteError(ConfigError):
    """Запись конфигурации отклонена: плохой ввод или нечитаемый файл."""


def clean_secret_name(name: Any) -> str:
    """Имя поля секрета (оно же — id шлюза): одно слово, без мусора."""
    text = str(name or "").strip()
    if not _NAME_RE.match(text) or len(text) > MAX_SECRET_NAME:
        raise ConfigWriteError(
            f"Недопустимое имя поля: {text[:40]!r}. "
            "Годятся буквы, цифры, точка, дефис, подчёркивание."
        )
    return text


def clean_model_id(model: Any) -> str:
    """Идентификатор модели: как настоящий id, но без кавычек и скобок."""
    text = str(model or "").strip()
    if not _MODEL_RE.match(text):
        raise ConfigWriteError(
            "Плохой идентификатор модели: до 200 знаков, "
            "только буквы, цифры и . _ : / @ + - [ ]"
        )
    return text


def split_new_keys(value: Any) -> list[str]:
    """Разобрать вставленные ключи: строка (по переводу строки или запятой) или список.

    Возвращает уникальные ключи в порядке вставки. Ротация не любит дублей:
    два одинаковых ключа в круге означают, что один аккаунт крутится вдвое
    чаще остальных и счётчик лимита уходит вперёд.
    """
    if isinstance(value, (list, tuple)):
        raw = [str(v) for v in value]
    else:
        raw = str(value or "").replace(",", "\n").splitlines()

    keys: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(raw, start=1):
        text = line.strip()
        if not text or text in seen:
            continue
        if len(text) > MAX_KEY_LENGTH:
            raise ConfigWriteError(
                f"Ключ №{number} длиннее {MAX_KEY_LENGTH} знаков — это не ключ"
            )
        if any(ord(ch) < 32 for ch in text):
            raise ConfigWriteError(
                f"Ключ №{number} содержит управляющие символы"
            )
        seen.add(text)
        keys.append(text)

    if not keys:
        raise ConfigWriteError("Ни одного ключа не вставлено")
    if len(keys) > MAX_KEYS_PER_EDIT:
        raise ConfigWriteError(
            f"За раз можно вставить не больше {MAX_KEYS_PER_EDIT} ключей"
        )
    return keys


def detect_indent(text: str) -> int | str:
    """Какой отступ у файла — пишем тем же.

    Конфиги переформатировали по-разному (2 пробела, 1 пробел, табуляция),
    и запись с фиксированным indent=2 превращала бы добавление одной строки
    в правку всего файла: diff нечитаем, ревью бессмысленно.
    """
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped[0] in "{}[]":
            continue
        lead = line[: len(line) - len(stripped)]
        if "\t" in lead:
            return "\t"
        return len(lead) if lead else 2
    return 2


def atomic_write(path: Path, text: str) -> None:
    """Записать файл так, чтобы читатель не увидел половину записи.

    На Windows `os.replace()` иногда падает Access is denied: свежий .tmp
    уже подхватил антивирус или индексатор. Замена повторяется с паузой —
    падать сразу значило бы изредка терять вставленный ключ из-за чужого
    сканера (живой прогон поймал именно такой отказ).
    """
    # Имя временного файла должно быть уникальным. Фиксированное `.tmp`
    # делилось между двумя одновременными сохранениями: второй поток
    # затирал запись первого, а затем получал FileNotFoundError на
    # os.replace. Именно так терялись настройки и ключи: веб пишет
    # конфиг, и в тот же момент его может писать кто-то из консоли.
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    error: OSError | None = None
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            error = exc
            time.sleep(0.03 * (attempt + 1))
    assert error is not None
    # Хвостовой .tmp не оставляем: в папке с ключами чужие файлы не годятся.
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    raise error


def _dump_json(data: Any, indent: int | str) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent) + "\n"


def save_secrets(secrets: dict[str, Any], root: str | Path | None = None) -> Path:
    """Записать config/secrets.local.json атомарно."""
    path = config_dir(root) / SECRETS_FILE
    indent: int | str = 2
    if path.is_file():
        try:
            indent = detect_indent(path.read_text(encoding="utf-8"))
        except OSError:
            indent = 2
    text = _dump_json(secrets, indent)
    if len(text.encode("utf-8")) > MAX_SECRETS_FILE:
        raise ConfigWriteError(
            "secrets.local.json разросся больше 128 КБ — почистите его руками"
        )
    atomic_write(path, text)
    try:
        # На POSIX файл с ключами читает только владелец; на Windows
        # chmod отсутствует, и это не ошибка.
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _single_value_fields(root: str | Path | None = None) -> set[str]:
    """Поля, которые обязаны лежать строкой, а не списком ротации.

    Это ровно те имена, что подставляются в base_url как {cloudflare_account_id}:
    подстановка делает str(value), и список превратился бы в «['abc']» — URL
    сломался бы молча. Правило узнаётся из конфига, а не из запомненного
    списка: новое поле-плейсхолдер не придётся объявлять в двух местах.
    """
    path = config_dir(root) / GATEWAYS_FILE
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    raw = data.get("gateways") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return set()
    fields: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            fields.update(_PLACEHOLDER_RE.findall(str(item.get("base_url") or "")))
    return fields


def edit_secret(
    name: Any,
    keys: Any,
    *,
    action: str = "add",
    single: bool | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Добавить, заменить или удалить ключи одного поля в secrets.local.json.

    `add` — дописать новые в конец (так добавляют ключи других аккаунтов),
    `replace` — списком затереть всё поле, `remove` — выкинуть вставленные.

    `single` — одиночное значение вместо списка (Account ID у Cloudflare).
    Если не передан, выводится из формы текущего значения и из того,
    подставляется ли поле в base_url. Из списка в строку ничего не
    превращается.
    """
    if action not in ("add", "replace", "remove"):
        raise ConfigWriteError(f"Неизвестное действие «{action}»")

    field = clean_secret_name(name)
    incoming = split_new_keys(keys)
    secrets = load_secrets(root)
    value = secrets.get(field)
    if single is None:
        single = isinstance(value, str) or field in _single_value_fields(root)
    current = _keys_from_value(value)

    if action == "add":
        if single:
            raise ConfigWriteError(
                "Это одиночное значение: вставьте одно и сохраните"
            )
        known = set(current)
        added = [k for k in incoming if k not in known]
        updated = current + added
        result: dict[str, Any] = {
            "ok": True, "action": action, "name": field,
            "added": len(added),
            "duplicates": len(incoming) - len(added),
            "total": len(updated),
        }
    elif action == "replace":
        updated = incoming[:1] if single else incoming
        result = {
            "ok": True, "action": action, "name": field,
            "total": len(updated), "was": len(current),
        }
    else:
        drop = set(incoming)
        kept = [k for k in current if k not in drop]
        removed = len(current) - len(kept)
        if not removed:
            return {
                "ok": False, "action": action, "name": field,
                "error": "Ни один из вставленных ключей не найден",
                "total": len(current),
            }
        updated = kept
        result = {
            "ok": True, "action": action, "name": field,
            "removed": removed, "total": len(updated),
        }

    if updated:
        secrets[field] = updated[0] if single else updated
    else:
        secrets.pop(field, None)
    save_secrets(secrets, root)
    return result


def edit_gateway_models(
    gateway_id: Any,
    model: Any,
    *,
    action: str = "add",
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Добавить или убрать модель из ручного списка free_models шлюза.

    Список вручную добавленных моделей — вторая половина вкладки «Настройки»:
    tiers.json задаёт ранг модели, а здесь она попадает в каталог, без
    этого селектор её просто не увидит.
    """
    if action not in ("add", "remove"):
        raise ConfigWriteError(f"Неизвестное действие «{action}»")

    gid = clean_secret_name(gateway_id)
    m = clean_model_id(model)
    path = config_dir(root) / GATEWAYS_FILE
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigWriteError(f"Некорректный JSON в {path}: {exc}") from exc

    raw = data.get("gateways")
    if not isinstance(raw, list):
        raise ConfigWriteError(f"В {path} список gateways отсутствует")
    item = next(
        (g for g in raw if isinstance(g, dict) and str(g.get("id")) == gid), None
    )
    if item is None:
        known = ", ".join(str(g.get("id")) for g in raw if isinstance(g, dict))
        raise ConfigWriteError(f"Неизвестный шлюз «{gid}». Есть: {known}")

    free = [
        str(x).strip() for x in (item.get("free_models") or []) if str(x).strip()
    ]

    if action == "add":
        if m in free:
            return {
                "ok": True, "action": action, "gateway": gid, "model": m,
                "added": 0, "total": len(free), "note": "уже есть в списке",
            }
        if not item.get("catalog"):
            # _default_catalog() решает по наличию free_models: «список есть»
            # значит статический каталог. То есть первая же ручная модель
            # молча выключила бы живой каталог шлюза — а это модели, которые
            # сеть приносит сама. Явный catalog сохраняет и то, и другое.
            before = _default_catalog(item)
            item["free_models"] = free + [m]
            after = _default_catalog(item)
            if before != after:
                item["catalog"] = sorted(set(before) | set(after))
        else:
            item["free_models"] = free + [m]
        result: dict[str, Any] = {
            "ok": True, "action": action, "gateway": gid, "model": m,
            "added": 1, "total": len(free) + 1,
        }
    else:
        if m not in free:
            return {
                "ok": False, "action": action, "gateway": gid, "model": m,
                "error": "Такой модели нет в ручном списке шлюза "
                         "(её приносит живой каталог — правьте tiers.json)",
                "total": len(free),
            }
        kept = [x for x in free if x != m]
        if kept:
            item["free_models"] = kept
        else:
            item.pop("free_models", None)
        result = {
            "ok": True, "action": action, "gateway": gid, "model": m,
            "removed": 1, "total": len(kept),
        }

    atomic_write(path, _dump_json(data, detect_indent(text)))
    return result


def build_settings(
    root: str | Path | None = None, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Что показывает вкладка «Настройки»: шлюзы, поля секретов, их счётчики.

    Значений ключей здесь нет по построению — только имена полей и сколько
    ключей лежит. `key_field` — как поле называется в secrets.local.json
    (у Cloudflare их два: токен и Account ID, второй берётся из {placeholder}
    в base_url), `env_var` — куда положить тот же ключ переменной окружения.

    Поля не всегда очевидны: у zen `secret_key: null`, но ключ читается
    legacy-путём (`load_api_key`), а у ollama ключ и вовсе литерал — там
    вводить нечего, и интерфейс обязан это сказать, а не показывать пустое
    поле с нулём ключей.
    """
    environ = os.environ if env is None else env
    gateways = load_gateways(root, env=env)
    out: list[dict[str, Any]] = []
    for g in gateways:
        raw_field = g.get("secret_key") if "secret_key" in g else g.get("id")
        legacy = _LEGACY_SECRET.get(g["id"])
        if raw_field:
            field = str(raw_field)
            env_var = _env_name(field)
        elif legacy:
            field, env_var = legacy
        else:
            field = env_var = None
        base = str(g.get("base_url") or "")
        extra: list[dict[str, str]] = []
        for holder in dict.fromkeys(_PLACEHOLDER_RE.findall(base)):
            extra.append({"name": holder, "label": holder.replace("_", " ")})
        if field:
            # Счётчик считаем сами, а не берём key_count из load_gateways:
            # у zen поле лежит под zen_api_key, сам шлюз о нём в конфиге не
            # знает — интерфейс показывал бы ноль при двух ключах в файле.
            count = len(resolve_keys(field, root=root, env=env))
            has_key = count > 0
        else:
            # Без поля остаётся то, что дал сам шлюз: литерал Ollama (1) или
            # ничего у анонимного llm7.
            count = int(g.get("key_count") or 0)
            has_key = bool(g.get("has_key"))
        out.append({
            "id": g["id"],
            "label": str(g.get("label") or g["id"]),
            "key_field": field,
            "key_count": count,
            "has_key": has_key,
            "needs_key": bool(g.get("needs_key") or g.get("env")),
            "literal": bool(g.get("api_key_literal")),
            "from_env": bool(env_var and env_var in environ),
            "env_var": env_var,
            "extra_fields": extra,
            "free_models": [str(m) for m in (g.get("free_models") or [])],
            "catalog": [str(c) for c in (g.get("catalog") or [])],
        })
    return {"ok": True, "gateways": out}
