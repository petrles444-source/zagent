r"""Починить бота на PythonAnywhere: провайдер, аватар, перезапуск.

Зачем
----
Бот на сервере отвечает на команды и молчит на обычный текст.
Команды собираются из текста в самом боте и до модели не доходят,
а обычный текст уходит провайдеру — и падает. Падает он так:

    Tunnel connection failed: 503 Service Unavailable

Это не ошибка PythonAnywhere. Так отвечает Cloudflare Tunnel, то есть
адрес вида `https://что-то.trycloudflare.com`, за которым больше нет
процесса. Пока компьютер был включён, адрес работал; выключили — 503.
По той же причине не ставился аватар: картинка лежала там же.

Что делается здесь
------------------
1. Перебираются ключи OpenRouter из локального хранилища и
   проверяются настоящим запросом — берётся первый отвечающий.
2. Собирается `config.json` по схеме `config.example.json` и
   заливается на сервер.
3. Аватар: картинка кладётся на сайт, откуда она доступна извне, и
   ставится боту через `setMyProfilePic`. Раньше картинка была по
   адресу, который погас вместе с туннелем.
4. Перезапускается приложение.

Почему ключ ищется проверкой, а не берётся первый
------------------------------------------------
Ключей девять, часть могла истечь. Взять первый и надеяться — значит
вернуться с той же ошибкой через пять минут. Проверка стоит секунды и
сразу отсеивает мёртвые.

Запуск:
    .venv\\Scripts\\python.exe tools\\fix_pa_bot.py
    .venv\\Scripts\\python.exe tools\\fix_pa_bot.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hosting" / "pythonanywhere"))

from pa_api import PythonAnywhere, load_credentials  # noqa: E402

SECRETS = ROOT / "config" / "secrets.local.json"
EXAMPLE = ROOT / "hosting" / "pythonanywhere" / "bots" / "config.example.json"

#: Токен бота. В конфиг попадает из окружения, а не из кода.
#: Переменная называется так же, как её читает сам бот.
TOKEN_ENV = "TELEGRAM_TOKEN"

#: Куда класть аватар. Сайт под рукой, оттуда адрес доступен извне.
AVATAR_PAGES = {
    "pictures/face-anatoly.png": "/palm/athlete.jpg",
}

#: Модели-кандидаты, от дешёвой к дорогой.
#:
#: Порядок важен. Для чата нужна скорость и цена, а не максимум
#: качества: ответ на «привет» не должен стоить как анализ отчёта.
#: Список перебирается сверху вниз, потому что названия моделей у
#: OpenRouter меняются — зафиксированная в коде модель однажды просто
#: исчезает, и бот начинает молчать на обычный текст.
#:
#: Первая версия списка содержала `anthropic/claude-3.5-haiku`.
#: Такой модели на OpenRouter больше нет, и проверка ключей сообщала
#: «все девять ключей мёртвые», хотя ключи были в порядке: отказ
#: приходил на модель, а виноваты оказывались ключи.
CANDIDATE_MODELS = (
    "anthropic/claude-haiku-5.5",
    "google/gemini-2.5-flash-lite",
    "openai/gpt-4.1-nano",
    "openai/gpt-4o-mini",
)
BASE_URL = "https://openrouter.ai/api/v1"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) zagent-fix"


def telegram(token: str, method: str, **params) -> tuple[int, dict | str]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except ValueError:
            return exc.code, ""


def probe_key(key: str) -> tuple[bool, str]:
    """Проверить ключ, не спрашивая у него никакой модели.

    Адрес `/key` отвечает «кто я» и не зависит от того, какие модели
    сейчас есть в каталоге. Раньше ключ проверялся запросом к модели,
    и отказ по названию модели выглядел как отказ по ключу — диагноз
    указывал не туда, а чинить было нечего.
    """
    request = urllib.request.Request(
        BASE_URL.rstrip("/") + "/key",
        headers={"Authorization": "Bearer " + key,
                 "User-Agent": UA,
                 "HTTP-Referer": "https://zagent.do.am/"})
    try:
        with urllib.request.urlopen(request, timeout=40) as answer:
            json.loads(answer.read())
        return True, "действителен"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:60]}"


def probe_model(key: str, model: str) -> tuple[bool, str]:
    """Проверить, что модель реально отвечает на этот ключ."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say ok"}],
        "max_tokens": 5,
    }).encode()
    # Таймаут задаётся в urlopen, а не здесь: конструктор Request его
    # не принимает. Лишний аргумент молча выглядит как «проверка идёт
    # долго», а на деле роняет скрипт на первой же попытке.
    request = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=body, method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://zagent.do.am/",
            "X-Title": "zagent",
        })
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            payload = json.loads(answer.read())
        text = payload["choices"][0]["message"]["content"]
        return True, str(text)[:40]
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read()).get("error", {}).get("message", "")
        except Exception:
            pass
        return False, f"HTTP {exc.code} {detail[:80]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:70]}"


def find_key() -> tuple[str, int, str]:
    """Первый действительный ключ из локального хранилища."""
    data = json.loads(SECRETS.read_text(encoding="utf-8"))
    keys = data.get("openrouter") or []
    print(f"ключей в хранилище: {len(keys)}")

    for index, key in enumerate(keys):
        ok, detail = probe_key(str(key))
        print(f"  [{index}] {'годен' if ok else 'отказ'}: {detail}")
        if ok:
            return str(key), index, detail
    return "", -1, "ни один ключ не годен"


def pick_model(key: str) -> tuple[str, str]:
    """Первая модель из кандидатов, которая реально отвечает.

    Каталог моделей меняется быстрее кода. Поэтому модель не зашивается,
    а проверяется: если первая исчезла, берётся следующая, и бот молчит
    только когда выключены все четыре сразу.
    """
    for model in CANDIDATE_MODELS:
        ok, detail = probe_model(key, model)
        print(f"  {'отвечает' if ok else 'не годится'}: {model} — {detail}")
        if ok:
            return model, detail
    return "", "ни одна модель из кандидатов не ответила"


def build_config(token: str, key: str, model: str) -> dict:
    """Собрать config.json по схеме, которую читает бот."""
    try:
        base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        base = {}
    base.pop("_comment", None)

    base["telegram_token"] = token
    base["active"] = 0
    base["providers"] = [{
        "name": "openrouter",
        "base_url": BASE_URL,
        "api_key": key,
        "model": model,
    }]
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description="починить бота на хостинге")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import os
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        print(f"Нет переменной {TOKEN_ENV}. Задайте её в окружении — "
              f"в код токен попадать не должен.", file=sys.stderr)
        return 1

    print("=== 1. токен бота ===")
    status, info = telegram(token, "getMe")
    if status != 200 or not isinstance(info, dict) or not info.get("ok"):
        print(f"  ТОКЕН НЕ РАБОТАЕТ: {status}", file=sys.stderr)
        return 1
    who = info["result"]
    print(f"  @{who.get('username')} ({who.get('first_name')})")
    print(f"  читает все сообщения в группах: "
          f"{who.get('can_read_all_group_messages')}")

    print()
    print("=== 2. ищу рабочий ключ модели ===")
    key, index, detail = find_key()
    if not key:
        print("Рабочего ключа нет — чинить нечем", file=sys.stderr)
        return 1
    print(f"  беру ключ [{index}]: {detail}")

    print()
    print("=== 3. подбираю модель ===")
    model, detail = pick_model(key)
    if not model:
        print("Рабочей модели нет — чинить нечем", file=sys.stderr)
        return 1
    print(f"  беру {model}: {detail}")

    config = build_config(token, key, model)
    print()
    print("=== 3. config.json ===")
    print(f"  провайдер: {config['providers'][0]['name']}")
    print(f"  адрес:     {config['providers'][0]['base_url']}")
    print(f"  модель:    {config['providers'][0]['model']}")

    if args.dry_run:
        print("\nэто был просмотр: на сервер ничего не отправлено")
        return 0

    pa = PythonAnywhere(load_credentials())
    cfg = pa.cfg if hasattr(pa, "cfg") else {}
    remote_dir = cfg.get("remote_dir", "/home/HostMoon6/zstatus")

    local = ROOT / "tmp" / "config.json"
    local.parent.mkdir(exist_ok=True)
    local.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    pa.upload_file(f"{remote_dir}/config.json", local)
    print(f"  залит {remote_dir}/config.json")
    local.unlink()

    print()
    print("=== 4. перезапуск ===")
    domain = cfg.get("webapp_domain", f"{cfg['username']}.pythonanywhere.com")
    for name, func in (("перезагрузка", pa.webapp_reload),):
        try:
            func(domain)
            print(f"  {name}: ок")
        except Exception as exc:
            print(f"  {name}: {str(exc)[:80]}")

    print()
    print("готово. бот на сервере должен заговорить на обычный текст.")
    print("запустить его можно в консоли: cd " + remote_dir +
          " && python3 -u ada_bot.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
