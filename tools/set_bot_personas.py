r"""Проверить все три токена бота и переписать конфиг на сервере.

Зачем это
---------
Человек принёс три токена от трёх разных ботов и говорит, что не
работает ни один. Прежде чем чинить код, надо убедиться, что токены
живые: если бот создан, но ещё ни разу не запускался, Telegram всё
равно считает его рабочим, а вот `/getMe` сразу скажет правду.

Одновременно ставится `persona_key` — имя, которым бот представляется.
Раньше там стоял `anatoly` у всех, поэтому токен `@adaweffeBot`
отвечал «Я Анатолий».

Токены берутся из переменных окружения, а не пишутся в код: файл
лежит в репозитории, и ключ в нём — это ключ в репозитории.

Запуск (по одному токену за раз):
    $env:ADA_TOKEN='...'
    $env:ANATOLY_TOKEN='...'
    $env:Social_TOKEN='...'
    .venv\\Scripts\\python.exe tools\\set_bot_personas.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hosting" / "pythonanywhere"))

from pa_api import PythonAnywhere, load_credentials  # noqa: E402

import os  # noqa: E402

EXAMPLE = ROOT / "hosting" / "pythonanywhere" / "bots" / "config.example.json"
SECRETS = ROOT / "config" / "secrets.local.json"
REMOTE_DIR = "/home/HostMoon6/zstatus"

#: Имя бота -> переменная окружения с токеном и ключ персоны.
#:
#: Персоны взяты из `persona.py`: `anatoly` и `katy` там есть, а персон
#: для Ады нет вообще — поэтому она добавляется в `persona.py` и
#: заливается вместе с остальным.
BOTS = (
    ("Ада", "ADA_TOKEN", "ada"),
    ("Анатолий", "ANATOLY_TOKEN", "anatoly"),
    ("Кети", "Social_TOKEN", "katy"),
)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) zagent"


def get_me(token: str) -> tuple[bool, str]:
    """Живой ли токен. `/getMe` — единственный честный ответ."""
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getMe",
        headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=40) as answer:
            data = json.loads(answer.read())
        who = data["result"]
        return True, (f"@{who.get('username')} ({who.get('first_name')}), "
                      f"группы: {who.get('can_read_all_group_messages')}")
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}"


def main() -> int:
    secrets = json.loads(SECRETS.read_text(encoding="utf-8"))
    openrouter = secrets["openrouter"][0]
    #: Модель выбрана замером скорости, а не на глаз. Подробности в
    #: комментарии над CANDIDATE_MODELS в tools/fix_pa_bot.py.
    model = "openai/gpt-4.1-nano"

    base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    base.pop("_comment", None)

    alive = []
    print("=== проверяю токены ===")
    for label, env, persona_key in BOTS:
        token = os.environ.get(env, "").strip()
        if not token:
            print(f"  {label:<10} нет переменной {env} — пропускаю")
            continue
        ok, detail = get_me(token)
        print(f"  {label:<10} {'жив' if ok else 'МЁРТВ'}: {detail}")
        if ok:
            alive.append((label, token, persona_key))

    if not alive:
        print("\nНи один токен не задан — настраивать нечего.",
              file=sys.stderr)
        return 1

    print()
    print("=== собираю config.json ===")
    config = dict(base)
    config["telegram_token"] = alive[0][1]
    config["active"] = 0
    config["persona_key"] = alive[0][2]
    config["providers"] = [{
        "name": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": openrouter,
        "model": model,
    }]
    print(f"  токен:    @{alive[0][0]}")
    print(f"  персона:  {alive[0][2]}")
    print(f"  модель:   {model}")

    pa = PythonAnywhere(load_credentials())
    local = ROOT / "tmp" / "config.json"
    local.parent.mkdir(exist_ok=True)
    local.write_text(json.dumps(config, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    pa.upload_file(f"{REMOTE_DIR}/config.json", local)
    local.unlink()
    print(f"  залит {REMOTE_DIR}/config.json")

    print()
    print("Запуск в консоли:")
    print(f"  cd {REMOTE_DIR}")
    print("  python3 -u ada_bot.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())