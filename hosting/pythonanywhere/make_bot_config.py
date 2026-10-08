r"""Собрать config.json для бота из источников истины zagent и залить его.

Ключи не пишутся на диск
------------------------
Скрипт читает `config/secrets.local.json`, собирает конфиг в памяти и
отправляет на сервер. Промежуточного файла с ключами на этой машине не
возникает: если бы он появился, то рано или поздно попал бы в
репозиторий вместе с остальным.

Что откуда берётся
------------------
* Адреса — из `config/gateways.json`. Это единственное место, где они
  описаны; дублировать их в боте нельзя, адрес поменяется и бот
  молча перестанет отвечать.
* Ключи — первый непустой из списка в `config/secrets.local.json`:
  их там по нескольку на провайдера, и сгодится любой.
* Модели — из списка ниже: только те, что уже проверены в zagent.
  Несуществующий идентификатор модель принимает молча, отвечает ошибкой
  и съедает квоту, поэтому «на глаз» их лучше не ставить.

Запуск:
    .venv\Scripts\python.exe hosting\pythonanywhere\make_bot_config.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from pa_api import PaError, PythonAnywhere  # noqa: E402

#: Проверенные связки «шлюз — модель». Всё, чего здесь нет, не
#: выкладывается: несуществующий идентификатор модель принимает молча,
#: отвечает ошибкой и съедает квоту впустую.
#:
#: Порядок важен: первым идёт тот, что реально отвечает С СЕРВЕРА.
#: Замер на хостинге (hosting/pythonanywhere/tools/selfcheck.py):
#:   NVIDIA NIM — работает, отвечает;
#:   Groq       — HTTP 403: регион исходящих адресов сервера закрыт,
#:                хотя домашняя машина ходит туда свободно. Вот почему
#:                проверять надо оттуда, где бот будет жить;
#:   OpenRouter — HTTP 404: модели с идентификатором :free в каталоге
#:                нет. В список не выкладываем.
MODELS: tuple[tuple[str, str], ...] = (
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
    ("groq", "openai/gpt-oss-120b"),
)

SYSTEM = ("Ты — помощник zagent. Отвечай по-русски, коротко и по делу. "
          "Если не знаешь ответа, скажи об этом прямо.")


def gateways() -> dict[str, dict[str, Any]]:
    path = ROOT / "config" / "gateways.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("gateways") if isinstance(data, dict) else data
    return {g["id"]: g for g in (items or []) if isinstance(g, dict) and g.get("id")}


def first_key(secrets: dict[str, Any], name: str) -> str:
    """Первый непустой ключ провайдера.

    Секреты хранятся списком: это запас на ротацию. Пустые строки в
    списке — обычное дело после отзыва ключа, их надо пропускать.
    """
    value = secrets.get(name)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
    return ""


def bot_persona() -> str:
    """Взять персону из самого бота.

    Дублировать текст в двух местах нельзя: поменяют в одном файле, а
    бот на сервере продолжит говорить прежним. Импорт безопасен — `main`
    вызывается только под `if __name__ == "__main__"`.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ada_bot_persona", HERE / "bots" / "ada_bot.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(getattr(module, "PERSONA", SYSTEM))


def build() -> dict[str, Any]:
    """Собрать конфиг бота. Возвращает только то, что поедет на сервер."""
    secrets = json.loads(
        (ROOT / "config" / "secrets.local.json").read_text(encoding="utf-8"))
    known = gateways()
    providers: list[dict[str, Any]] = []
    for gateway_id, model in MODELS:
        gateway = known.get(gateway_id)
        if not gateway:
            print(f"шлюз {gateway_id} не описан в gateways.json — пропускаю")
            continue
        key = first_key(secrets, gateway.get("secret_key") or gateway_id)
        if not key:
            print(f"у {gateway_id} нет ключа — пропускаю")
            continue
        providers.append({
            "name": gateway.get("label") or gateway_id,
            "base_url": gateway["base_url"],
            "model": model,
            "api_key": key,
        })
    return {
        "telegram_token": os.environ.get("TELEGRAM_TOKEN", ""),
        "heartbeat_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "active": 0,
        "persona": bot_persona(),
        "providers": providers,
    }


def main() -> int:
    config = build()
    if not config["providers"]:
        print("Ни один провайдер не собрался: проверь secrets.local.json")
        return 1
    print("собрано провайдеров:", len(config["providers"]))
    for provider in config["providers"]:
        print(f"   {provider['name']:16} {provider['model']}  "
              f"ключ: {len(provider['api_key'])} символов")
    if not config["telegram_token"]:
        print("\nТокена Telegram нет. Бот зальётся и будет честно писать")
        print("«нет токена» — сначала создай бота у @BotFather.")
    return upload(config)


def upload(config: dict[str, Any]) -> int:
    """Отправить конфиг на сервер."""
    try:
        from pa_api import load_credentials
        pa = PythonAnywhere(load_credentials())
    except PaError as exc:
        print(exc)
        return 2
    remote_dir = pa.cfg.get("remote_dir", f"/home/{pa.user}/zstatus")
    text = json.dumps(config, ensure_ascii=False, indent=2)
    pa.upload_text(f"{remote_dir}/config.json", text)
    print(f"\nзалит {remote_dir}/config.json ({len(text)} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
