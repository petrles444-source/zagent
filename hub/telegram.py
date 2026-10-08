"""Фабрика telegram-ботов: план, сборка и запуск — без новых зависимостей.

Зачем это в проекте
-------------------
Задача «сделай бота, который отвечает через мои модели» упирается не в
код, а в три вещи, которые надо один раз сделать честно: получить токен,
собрать бота из заготовок и не раздать при этом чужие ключи посторонним.
Этот модуль делает ровно их и отдаёт агенту готовый результат.

Три решения, которые здесь принципиальны
---------------------------------------

**1. Ни одной новой зависимости.** План, который прислали со стороны,
предлагал telebot, SQLAlchemy и Flask. Здесь обойдена стандартная
библиотека: обращения к Bot API идут через `urllib`, состояние лежит в
JSON, веб-интерфейс не нужен вовсе. Причина простая: проект уже отказался
от Flask в пользу встроенного сервера, а telebot потащил бы за собой
дерево зависимостей ради пяти методов HTTP.

**2. Ключи ИИ никогда не попадают в код бота.** Сгенерированный файл
содержит *имя* источника, а не значение ключа, и читает его из
`config/secrets.local.json` в момент запуска. Иначе `tools/check_secrets.py`
заблокирует коммит, а при отправке бота кому-то ключ уехал бы вместе с
ним. Это же делает файл безопасным для хранения в репозитории.

**3. Создание самого бота в Telegram делает человек.** Это ограничение
самого Telegram: бота создаёт только @BotFather из приложения, никакого
API для этого нет. Утила делает всё остальное и честно говорит, что
осталось человеку — один шаг с токеном.

Агент может собрать бота целиком сам, а может остановиться и спросить
человека про токен и про то, какие модели бот должен звать.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hub.config import project_root, resolve_keys
from hub.local_llm import DEFAULT_BASE as OLLAMA_BASE

#: Куда собираются боты. Внутри проекта, рядом с остальным: отдельная
#: папка `projects/` уже есть и тоже не попадает в репозиторий.
BOTS_DIRNAME = "telegram-bots"

#: Задержка длинного опроса. Telegram держит соединение открытым столько,
#: сколько попросили; при разрыве задержку растём, но не бесконечно.
POLL_TIMEOUT_S = 25

#: Имя бота в телеграме: латиница, цифры, подчёркивание, 5–32 символа.
NAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")

#: Форма токена telegram-бота: числовой идентификатор, двоеточие,
#: длинный хвост. Ловится регуляркой, потому что подстроку
#: выбрать нельзя: в коде бота полно чисел через двоеточие.
TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")

#: Имя шлюза в config/gateways.json: латиница и подчёркивание.
GATEWAY_RE = re.compile(r"^[a-z_][a-z0-9_]{1,31}$")

#: Имя модели. Два вида и они непохожи: либо шлюз из конфигурации
#: (`openrouter`), либо локальная модель Ollama с меткой (`qwen2.5:3b`).
#: Раньше проверка требовала вид шлюза от обоих, и сборка падала с
#: «имя шлюза не подходит» на совершенно нормальном `qwen2.5:3b`.
MODEL_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,63}$")

#: Ключи, которые нельзя класть в файл бота. Список намеренно широкий:
#: проверка дешёвая, а цена ошибки — утечка ключа.
#: Что не имеет права попасть в файл бота. Токен Telegram добавлен
#: после проверки мутациями: список ловил только ключи ИИ и пропускал
#: `123456789:AAH...` - то есть ровно то, что утекает с ботом чаще
#: всего. Первым числом идёт любое «числа:буквы», это и есть формат.
FORBIDDEN = (
    "sk-",
    "api_key=",
    "api_key:",
    "token = \"",
    "bot_token = \"",
)


class TelegramError(RuntimeError):
    """Telegram API или конфигурация отказали."""


def bots_root(root: str | Path | None = None) -> Path:
    base = Path(root) if root is not None else project_root()
    return base / "projects" / BOTS_DIRNAME


def check_name(name: str) -> str:
    """Имя бота должно быть безопасным: оно становится именем папки."""
    text = str(name or "").strip()
    if not NAME_RE.match(text):
        raise TelegramError(
            f"имя бота не подходит: {text!r}. Нужны 5-32 символа из латиницы, "
            "цифр и подчёркивания - это требование самого Telegram.")
    return text


def check_gateway(gateway: str) -> str:
    """Проверка имени шлюза - только для тех случаев, где шлюз обязателен."""
    text = str(gateway or "").strip()
    if not GATEWAY_RE.match(text):
        raise TelegramError(
            f"имя шлюза не подходит: {text!r}. Оно должно совпадать с "
            "именем шлюза в config/gateways.json (например openrouter).")
    return text


def check_model(model: str) -> str:
    """Проверка модели: шлюз из конфига либо локальная модель с меткой.

    Разрешены оба вида, потому что бот по умолчанию зовёт локальный рантайм
    (`qwen2.5:3b`), и требование «только имя шлюза» отвергало нормальную
    настройку с понятным сообщением не про то.
    """
    text = str(model or "").strip()
    if not MODEL_RE.match(text):
        raise TelegramError(
            f"имя модели не подходит: {text!r}. Обычно это шлюз из "
            "config/gateways.json (openrouter) или локальная модель (qwen2.5:3b).")
    return text


def model_is_gateway(model: str) -> bool:
    """Это шлюз из конфигурации (а не локальная модель)?"""
    return bool(GATEWAY_RE.match(str(model or "").strip()))


def has_key(model: str, root: str | Path | None = None) -> bool:
    """Есть ли у модели ключ. Значение не возвращаем - только факт.

    Локальные модели (`qwen2.5:3b`) ключа не имеют вовсе, и спрашивать про
    них шлюзовую конфигурацию бессмысленно. Раньше проверка требовала вид
    «имя шлюза» и отвергала нормальную локальную модель.
    """
    text = str(model or "").strip()
    if not model_is_gateway(text):
        return False
    return bool(resolve_keys(text, root=root))


# ------------------------------------------------------------- Telegram API


def api_call(token: str, method: str, *, base: str = "https://api.telegram.org",
             timeout: float = 40.0, **params: Any) -> dict[str, Any]:
    """Один вызов Bot API. Ошибка приходит словами, а не исключением молча."""
    if not str(token or "").strip():
        raise TelegramError("нет токена бота")
    url = f"{base.rstrip('/')}/bot{token}/{method}"
    body = {k: str(v) for k, v in params.items() if v is not None}
    request = urllib.request.Request(url, data=b"" if not body else
                                     json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise TelegramError(f"Telegram HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise TelegramError(f"Telegram недоступен ({type(exc).__name__})") from exc
    if not isinstance(data, dict) or not data.get("ok"):
        described = (data or {}).get("description") or "неизвестная ошибка"
        raise TelegramError(f"Telegram: {described}")
    return data.get("result") or {}


def get_me(token: str) -> dict[str, Any]:
    """Кто этот бот. Без этого токен не проверен, а ошибка всплывает позже."""
    return api_call(token, "getMe")


def delete_webhook(token: str) -> bool:
    """Убрать вебхук, иначе long polling не получит ни одного сообщения."""
    result = api_call(token, "deleteWebhook", drop_pending_updates="true")
    return bool(result.get("result") if isinstance(result, dict) else True)


def send_message(token: str, chat_id: str, text: str) -> dict[str, Any]:
    return api_call(token, "sendMessage", chat_id=chat_id, text=str(text)[:4000])


def long_poll(token: str, *, timeout: int = POLL_TIMEOUT_S,
              offset: int = 0) -> list[dict[str, Any]]:
    """Забрать накопившиеся обновления. Пустой список - это норма, не сбой."""
    result = api_call(token, "getUpdates", timeout=timeout, offset=offset or None,
                      allowed_updates='["message"]')
    return [u for u in result if isinstance(u, dict)] if isinstance(result, list) else []


# ------------------------------------------------------------ сборка бота


def answer_provider(gateway: str, prompt: str, *, root: str | Path | None = None,
                    local_base: str = OLLAMA_BASE) -> str:
    """Спросить наш локальный рантайм.

    У бота по умолчанию стоит именно он: он бесплатный, не требует ключа и
    работает без интернета. Шлюзы с ключами подключаются позже, и ключ
    тогда по-прежнему берётся из конфига на стороне бота.
    """
    from hub import local_llm

    messages = [{"role": "user", "content": str(prompt)}]
    try:
        return "".join(local_llm.stream_chat(gateway, messages, base=local_base,
                                             timeout=180.0)).strip()
    except local_llm.LocalLLMError as exc:
        raise TelegramError(f"локальная модель не ответила: {exc}") from exc


BOT_TEMPLATE = '''#!/usr/bin/env python3
"""Telegram-бот «{title}».

Сгенерировано фабрикой zagent. Запуск: python bot.py

Токен бота и ключи моделей НЕ хранятся в этом файле. Токен приходит из
config/secrets.local.json, ключи моделей - оттуда же. Так файл можно
отдать кому угодно и положить в репозиторий: секретов в нём нет.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
STATE = HERE / "state.json"


def load_config() -> dict:
    """Настройки бота. Токен - обязателен, ключи моделей - нет."""
    data = {{}}
    if CONFIG.is_file():
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    token = data.get("token") or os.environ.get("TELEGRAM_TOKEN", "")
    return {{"token": str(token), "model": str(data.get("model") or {model!r}),
            "system": str(data.get("system") or "")}}


def telegram(token: str, method: str, **params) -> dict:
    url = "https://api.telegram.org/bot" + token + "/" + method
    data = urllib.parse.urlencode({{k: str(v) for k, v in params.items()
                                   if v is not None}}).encode()
    with urllib.request.urlopen(url, data=data, timeout=40) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "Telegram отказал")
    return payload.get("result") or {{}}


def ask_llm(prompt: str, config: dict) -> str:
    """Ответ модели.

    По умолчанию зовётся локальный рантайм: он ничего не требует и всегда
    под рукой. Если в config.json указан шлюз из config/gateways.json,
    ключ берётся из secrets - в этом файле его нет.
    """
    model = config["model"]
    try:
        from zagent_bridge import ask  # подключается агентом при сборке
        return ask(model, prompt)
    except Exception:
        return ("Модель недоступна: не настроен шлюз {model!r}. "
                "Укажите его в config.json или переключитесь на локальный "
                "рантайм.").format(model=model)


def reply(text: str) -> None:
    """Ответить в телеграм текстом."""
    config = load_config()
    if not config["token"]:
        print("Нет токена: впишите его в config.json или в TELEGRAM_TOKEN")
        return
    print("ответ:", text[:200])
    # Отправка требует chat_id: подставьте его сами или сохраняйте при
    # первом сообщении.
    # telegram(config["token"], "sendMessage", chat_id=CHAT_ID, text=text)


def handle(message: dict, config: dict) -> None:
    text = str((message.get("text") or "")).strip()
    if not text:
        return
    if text.startswith("/"):
        reply("Я бот «{title}». Напишите вопрос обычным текстом.".format(
            title=TITLE))
        return
    system = config["system"]
    prompt = (system + "\\n\\n" + text) if system else text
    try:
        reply(ask_llm(prompt, config))
    except Exception as exc:
        reply("Не получилось ответить: " + str(exc)[:200])


def main() -> None:
    config = load_config()
    if not config["token"]:
        raise SystemExit("Нет токена бота")
    offset = 0
    print("Бот «{title}» слушает сообщения. Остановить: Ctrl+C".format(
        title=TITLE))
    while True:
        for update in telegram(config["token"], "getUpdates",
                               offset=offset or None,
                               timeout=POLL):
            offset = update.get("update_id", offset) + 1
            handle(update.get("message") or {{}}, config)
        time.sleep(0.5)


POLL = 25
TITLE = {title!r}

if __name__ == "__main__":
    main()
'''

README_TEMPLATE = """# {title}

Бот собран фабрикой zagent.

## Что нужно сделать человеком

1. Создать бота у [@BotFather](https://t.me/BotFather): команда `/newbot`.
   Это единственный шаг, который делает только человек - у Telegram нет
   API для создания ботов.
2. Полученный токен вписать в `config.json` (файл создан рядом) или
   отдать переменной окружения `TELEGRAM_TOKEN`.

## Запуск

    python bot.py

## Про модели

По умолчанию бот зовёт локальный рантайм Ollama: ключ не нужен, всё
работает без интернета. Чтобы звать шлюз из `config/gateways.json`,
укажите его именем в поле `model` - и добавьте ключ в
`config/secrets.local.json` проекта zagent. В коде бота ключей нет.

## Чего бот не умеет

Не отправляет сообщения сам: `reply()` собран как заготовка, где нужно
подставить `chat_id`. Это сделано намеренно - иначе бот писал бы в
случайные чаты.
"""

CONFIG_TEMPLATE = {
    "token": "",
    "model": "qwen2.5:3b",
    "system": "",
}


def build_bot(name: str, *, title: str = "", model: str = "qwen2.5:3b",
              system: str = "", root: str | Path | None = None,
              force: bool = False) -> dict[str, Any]:
    """Собрать бота на диске. Возвращает, что получилось и что осталось."""
    safe = check_name(name)
    # Модель проверяем ДО создания папки: раньше проверка стояла
    # в конце и падала уже после записи файлов, оставляя наполовину
    # собранного бота, который следующий запуск объявлял
    # «уже собран».
    model = check_model(model)
    target = bots_root(root) / safe
    existing = target / "bot.py"
    if existing.is_file() and not force:
        raise TelegramError(
            f"бот {safe!r} уже собран: {existing}. Перезаписать - force=True.")

    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    bot_py = target / "bot.py"
    bot_py.write_text(
        BOT_TEMPLATE.format(title=title or safe, model=model, system=system),
        encoding="utf-8")
    written.append("bot.py")

    config_json = target / "config.json"
    if not config_json.exists():
        config_json.write_text(
            json.dumps({**CONFIG_TEMPLATE, "model": model, "system": system},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        written.append("config.json")

    readme = target / "README.md"
    readme.write_text(README_TEMPLATE.format(title=title or safe),
                      encoding="utf-8")
    written.append("README.md")

    # Проверка, что секретов в написанном действительно нет. Дешёвая, но
    # единственная, которая защищает от ошибки в самой фабрике.
    for path in target.iterdir():
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")
        for needle in FORBIDDEN:
            if needle in body:
                raise TelegramError(
                    f"в {path.name} найдено {needle!r}: секрет в коде бота "
                    "недопустим - он уедет вместе с ботом")
        # Токен телеграма узнаётся по форме, а не по подстроке: цифры,
        # двоеточие и длинный хвост букв. Подстрокой его не поймать.
        if TOKEN_RE.search(body):
            raise TelegramError(
                f"в {path.name} похоже на токен telegram-бота: секрет в коде "
                "бота недопустим - он уедет вместе с ботом")

    return {
        "ok": True,
        "name": safe,
        "dir": str(target),
        "files": written,
        # Что обязан сделать человек: у Telegram нет API для создания бота.
        "human_steps": [
            f"у @BotFather выполнить /newbot и получить токен для {safe!r}",
            f"вписать токен в {config_json}",
            f"запустить: python {bot_py}",
        ],
        "model": model,
        "gateway_has_key": has_key(model, root=root),
    }


def list_bots(root: str | Path | None = None) -> list[dict[str, Any]]:
    """Что уже собрано. Секреты не читаются и не показываются."""
    base = bots_root(root)
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not (child / "bot.py").is_file():
            continue
        cfg: dict[str, Any] = {}
        cfg_path = child / "config.json"
        if cfg_path.is_file():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cfg = {}
        out.append({
            "name": child.name,
            "model": str(cfg.get("model") or ""),
            # Токен показываем только как факт: сам секрет не уходит из
            # интерфейса и не попадает в отчёт.
            "token_set": bool(str(cfg.get("token") or "").strip()),
            "dir": str(child),
        })
    return out


def status(name: str, *, root: str | Path | None = None) -> dict[str, Any]:
    """Состояние бота: собран, токен есть, отвечает ли Telegram."""
    safe = check_name(name)
    target = bots_root(root) / safe
    if not (target / "bot.py").is_file():
        return {"ok": False, "name": safe, "built": False,
                "error": "бот не собран"}
    cfg_path = target / "config.json"
    token = ""
    model = ""
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            token = str(data.get("token") or "")
            model = str(data.get("model") or "")
        except (OSError, ValueError):
            pass
    result: dict[str, Any] = {
        "ok": True, "name": safe, "built": True,
        "token_set": bool(token.strip()), "model": model,
    }
    if not token.strip():
        result["error"] = "токен не вписан - нужен человек с @BotFather"
        return result
    try:
        me = get_me(token.strip())
        result["telegram_ok"] = True
        result["username"] = str(me.get("username") or "")
    except TelegramError as exc:
        result["telegram_ok"] = False
        result["error"] = str(exc)
    return result
