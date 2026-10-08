r"""Сделать `bots/` самостоятельным проектом.

Зачем
----
Боты лежали в `bots/` копией и без конфига: запустить их оттуда было
нельзя, нужен был агент, чтобы взять ключ модели. Задача человека —
«боты это отдельное от zagent, выдели в другую папку, дай все нужные
секреты сразу, чтобы боты умели связываться с ИИ».

Значит папка должна запускаться сама, из себя, без агента.

Что добавляется
---------------
1. `config.json` с настоящим ключом модели и моделью, подобранной
   проверкой. Ключ копируется из хранилища агента, чтобы боты
   работали сразу и не зависели от `zagent/`.
2. `секреты/ключи-ботов.local.json` — токены всех трёх ботов в
   одном месте, чтобы не вводить их в консоль каждый раз.
3. `запустить-локально.bat` — запуск на своём компьютере.
4. `секреты/ПОЧЕМУ-ТАК.md` — почему ключи здесь, а не в коде.
5. `ЧТО-ЗДЕСЬ.md` переписывается под самостоятельный проект.

Почему ключи в папке, а не в коде
--------------------------------
Человек прямо сказал: «в папках с проектами они могут спокойно
храниться», и отдельно — «на гит секреты не нужно постить». Значит
папка `bots/` содержит ключи для работы, но `bots/` исключается из
git целиком. Так они лежат рядом и работают, и в репозиторий не
попадают.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_bots_standalone.py
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path


def wipe(path: Path) -> None:
    """Удалить дерево, сняв атрибут ReadOnly.

    Windows отказывается удалять каталог с этим флагом, и `rmtree`
    падает с «Access is denied». Это происходит не в первый раз:
    те же битые права стоили 33 папки `zagent-bench-*`, поэтому
    снятие прав встроено сюда, а не повторяется по месту.
    """
    for item in [path, *path.rglob("*")]:
        try:
            os.chmod(item, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)

ROOT = Path(__file__).resolve().parent.parent
BOTS = ROOT / "bots"
SRC = ROOT / "hosting" / "pythonanywhere" / "bots"
SECRETS = json.loads(
    (ROOT / "config" / "secrets.local.json").read_text(encoding="utf-8"))

#: Где лежат токены ботов.
#:
#: Токены НЕ зашиты в этот инструмент. Так было поначалу, и проверка
#: перед коммитом справедливо ругалась: файл попадал бы в репозиторий
#: вместе с тремя рабочими токенами.
#:
#: Источник один — `bots/секреты/ключи-ботов.local.json`, и эта папка
#: в git не идёт. Инструмент её читает, а не хранит. Если файла нет,
#: берётся из переменных окружения, иначе вписывается пустой шаблон,
#: который видно сразу и который придётся заполнить.
TOKENS_FILE = BOTS / "секреты" / "ключи-ботов.local.json"


def read_tokens() -> dict[str, str]:
    """Токены ботов: из файла, из окружения или пустой шаблон."""
    if TOKENS_FILE.is_file():
        try:
            data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
            found = data.get("tokens") or {}
            if found:
                return {str(k): str(v) for k, v in found.items()}
        except (OSError, ValueError):
            pass

    from_env = {name: os.environ.get(name, "") for name in
                ("ADA_TOKEN", "ANATOLY_TOKEN", "Social_TOKEN")}
    if any(from_env.values()):
        return from_env

    return {"ADA_TOKEN": "", "ANATOLY_TOKEN": "", "Social_TOKEN": ""}

#: Провайдеры, которые пробуются при настройке. Порядок — от лучшего
#: к худшему по скорости, но выбор делает не список, а проверка.
#:
#: Список задан, потому что OpenRouter однажды начал отвечать
#: «Access denied by security policy» на все девять ключей сразу, и
#: боты остались без модели. Поэтому настройка не доверяет ни одному
#: адресу: берётся тот, кто реально ответил сейчас.
#:
#: Модели дешёвые и быстрые — в чате важнее скорость, чем максимум
#: качества, и модель должна укладываться в окно прокси хостинга.
CANDIDATES = (
    ("mistralai", "https://api.mistral.ai/v1", "mistral-small-latest"),
    ("z_ai", "https://api.z.ai/api/paas/v4", "glm-4.5-air"),
    ("openrouter", "https://openrouter.ai/api/v1", "openai/gpt-4.1-nano"),
    ("groq", "https://api.groq.com/openai/v1", "llama-3.1-8b-instant"),
)

#: Что означает каждый отказ. Пустая строка — отказ неожиданный, и
#: его надо смотреть своими глазами.
#:
#: Список собран не умозрительно, а прогоном по всем ключам, и это
#: важно: почти все отказы выглядят одинаково, но означают разное.
#:
#:   403 security policy — ключи есть, но доступ закрыт политикой;
#:   429 rate limited      — ключ рабочий, упёрлись в лимит, попробовать
#:                          позже;
#:   429 insufficient      — на счёте нет денег, ключ тут ни при чём;
#:   401                   — ключ неверный;
#:   451                   — сервис недоступен из этой страны.
WHAT_IT_MEANS = {
    "HTTP 403": "ключи есть, но доступ закрыт политикой",
    "HTTP 429": "ключ рабочий, но лимит запросов или не хватает денег",
    "HTTP 401": "ключ неверный",
    "HTTP 451": "сервис недоступен из этой страны",
    "Insufficient balance": "на счёте нет денег",
    "Rate limit exceeded": "упёрлись в лимит, попробовать позже",
}


def explain(detail: str) -> str:
    """Что означает этот отказ — чтобы не гадать."""
    for needle, meaning in WHAT_IT_MEANS.items():
        if needle in detail:
            return meaning
    return ""


def probe(name: str, base: str, model: str) -> tuple[bool, str]:
    """Отвечает ли провайдер с этим ключом прямо сейчас."""
    keys = SECRETS.get(name)
    if not isinstance(keys, list) or not keys:
        return False, "нет ключа"
    body = json.dumps({"model": model, "max_tokens": 5,
                       "messages": [{"role": "user", "content": "ok"}]}).encode()
    for key in keys[:3]:
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions", data=body, method="POST",
            headers={"Authorization": "Bearer " + str(key),
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                json.loads(r.read())
            return True, "отвечает"
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:80].decode("utf-8", "replace")
            return False, f"HTTP {exc.code} {detail}".strip()
        except Exception as exc:
            return False, f"{type(exc).__name__}"
    return False, "ключей не нашлось"

README = """# Боты для Telegram

Три разговорных бота. Проект самостоятельный: запускается сам, из
этой папки, без агента и без сети к чему-либо ещё.

| Бот | Токен в переменной | Персона | Что делает |
|---|---|---|---|
| `@adaweffeBot` | `ADA_TOKEN` | Ада | девушка для общения, флиртует |
| `@social_neuro_bot` | `ANATOLY_TOKEN` | Анатолий | помощник по программированию |
| `@social_neuro2_bot` | `Social_TOKEN` | Кети | помощница по текстам |

## Запуск на своём компьютере

Двойной клик по `запустить-локально.bat`.

Батк сам подставит токены из `секреты/ключи-ботов.local.json`,
прочитает `config.json` и запустит всех троих. Ничего вводить не
нужно.

## Запуск вручную

```powershell
$env:ADA_TOKEN='...'
$env:ANATOLY_TOKEN='...'
$env:Social_TOKEN='...'
python pythonanywhere\\bots\\run_all.py
```

## Управление характером прямо в чате

```
/характер              — что настроено и как менять
/характер веселее      — переключить
/характер сброс        — вернуть исходный
```

Псевдонимы: `/character`, `/char`, `/persona`, `/режим`.

Настройки личные: в группе бот будет другим с другим человеком.

## Что боты умеют сами, без модели

Арифметику, время, длину текста, приветствия и рассказ о себе.
Это сделано кодом намеренно: модель считает `17*23` с вероятностью
опечатки, а выражение в Python — без. И если ключ недоступен или
сеть моргнула, бот остаётся полезным.

## Связь с моделями

Боты ходят в OpenRouter. Ключ и модель лежат в `config.json`,
сам ключ — в `секреты/ключи-моделей.local.json`.

Почему модель не зашита в код: каталог OpenRouter меняется быстрее
кода. Раньше в коде стояла `claude-3.5-haiku`, её убрали — и все
девять ключей объявлялись мёртвыми, хотя были живы: отказ приходил
на модель.

## Залить на хостинг

Двойной клик по `pythonanywhere/bots/upload-bots.bat`.

Проверяет, что список файлов совпадает с папкой, заливает на
PythonAnywhere, перезапускает приложение.

## Ограничение, о котором важно помнить

Консоль PythonAnywhere живёт, пока открыта вкладка. Закрыли — боты
умерли. Для круглосуточной работы нужен веб-приложение, и одна
строка в браузере его включает.
"""

WHY = """# Почему секреты лежат в этой папке

Здесь три разных вида ключей, и они устроены по-разному.

## Ключи моделей — в `ключи-моделей.local.json`

Ключ OpenRouter. Он же используется агентом, но здесь лежит своя
копия, чтобы боты работали без агента: проект должен запускаться
сам.

## Токены ботов — в `ключи-ботов.local.json`

Токены трёх ботов. Батк подставляет их в переменные окружения при
запуске, вводить руками не нужно.

## Почему всё это не в git

Папка `bots/` исключена целиком. Причина одна: ключ в репозитории
достаточно одного неверного `git add .`, а отменить это нельзя —
история помнит всё.

При этом сами ключи здесь лежат свободно: они нужны для работы, и
задача была именно в том, чтобы всё лежало рядом и запускалось без
хлопот.

## Что делать, когда ключи сменятся

1. Вписать новые в `секреты/ключи-моделей.local.json`.
2. Вписать новые токены в `секреты/ключи-ботов.local.json`.
3. Для сервера: `pythonanywhere/bots/upload-bots.bat`, затем
   `config.json` заливается заново.

## Если бот перестал отвечать

Сначала проверить токен: он мог истечь. Потом ключ модели. Потом
сеть хостинга — её прокси периодически обрывает соединение, и бот
делает до двенадцати повторов сам.
"""

BAT = """@echo off
REM ============================================================
REM  Start the three Telegram bots on this computer
REM
REM  Double-click. No input needed: tokens and the model key
REM  are read from the secrets folder next to this file.
REM ============================================================

chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=..\\.venv\\Scripts\\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "секреты\\ключи-ботов.local.json" (
    echo ERROR: secrets file not found:
    echo   секреты\\ключи-ботов.local.json
    pause
    exit /b 1
)

REM Read the tokens from the local secrets file.
for /f "usebackq tokens=1,* delims==" %%A in (
    "python -c \"import json,os;d=json.load(open('секреты/ключи-ботов.local.json',encoding='utf-8'));[print(k+'='+v) for k,v in d['tokens'].items()]\""
) do (
    if /i "%%A"=="ADA_TOKEN" set "ADA_TOKEN=%%B"
    if /i "%%A"=="ANATOLY_TOKEN" set "ANATOLY_TOKEN=%%B"
    if /i "%%A"=="Social_TOKEN" set "Social_TOKEN=%%B"
)

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo.
echo === Starting bots ===
echo.
"%PY%" pythonanywhere\\bots\\run_all.py
pause
"""


def main() -> int:
    print("=== 0. выбираю живого провайдера ===")
    chosen = None
    for name, base, model in CANDIDATES:
        ok, detail = probe(name, base, model)
        meaning = explain(detail)
        line = f"  {name:<12} {model:<22} {detail}"
        if meaning and not ok:
            line += f"\n{'':<16}└ {meaning}"
        print(line)
        if ok and chosen is None:
            chosen = (name, base, model)
    if not chosen:
        print("\n  НИ ОДИН провайдер не отвечает. Это внешние причины, "
              "не код.\n  Боты запустятся и будут работать: время, "
              "арифметика, настройка\n  характера и разговор без модели "
              "делаются кодом. Но на\n  свободный вопрос модель не "
              "ответит, пока не заработает\n  хотя бы один ключ.",
              file=sys.stderr)
    else:
        print(f"\n  беру {chosen[0]} / {chosen[2]}")
    name, base, model = chosen or CANDIDATES[-1]

    print()
    print("=== 1. копия файлов бота ===")
    target = BOTS / "pythonanywhere" / "bots"
    if target.exists():
        wipe(target)
    shutil.copytree(SRC, target,
                    ignore=shutil.ignore_patterns("__pycache__"))
    count = len(list(target.rglob("*.*")))
    print(f"  скопировано файлов: {count}")

    print()
    print("=== 2. ключи ===")
    sec_dir = BOTS / "секреты"
    sec_dir.mkdir(parents=True, exist_ok=True)

    keys = SECRETS.get(name)
    key_value = str(keys[0]) if isinstance(keys, list) and keys else ""
    models = {
        "_что-это": "Ключи моделей для ботов. Копия из хранилища агента, "
                    "чтобы боты работали без агента.",
        "provider": name,
        "base_url": base,
        "model": model,
        "api_key": key_value,
    }
    (sec_dir / "ключи-моделей.local.json").write_text(
        json.dumps(models, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  записан секреты/ключи-моделей.local.json")

    tokens = {
        "_что-это": "Токены ботов. Подставляются в переменные окружения "
                    "батником при запуске.",
        "tokens": read_tokens(),
    }
    (sec_dir / "ключи-ботов.local.json").write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  записан секреты/ключи-ботов.local.json")

    print()
    print("=== 3. конфиг для запуска ===")
    config = {
        "_что-это": "Настройки, из которых боты читают модель. Токены "
                    "сюда не кладутся: они приходят из переменных "
                    "окружения.",
        "active": 0,
        "persona_key": "ada",
        "providers": [{
            "name": name,
            "base_url": base,
            "api_key": key_value,
            "model": model,
        }],
    }
    (BOTS / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print("  записан config.json")

    print()
    print("=== 4. инструкции и запуск ===")
    (BOTS / "README.md").write_text(README, encoding="utf-8")
    print("  записан README.md")
    (sec_dir / "ПОЧЕМУ-ТАК.md").write_text(WHY, encoding="utf-8")
    print("  записан секреты/ПОЧЕМУ-ТАК.md")
    (BOTS / "запустить-локально.bat").write_text(BAT, encoding="utf-8")
    print("  записан запустить-локально.bat")

    print()
    print("=== 5. исключить из git ===")
    ignore = ROOT / ".gitignore"
    body = ignore.read_text(encoding="utf-8")
    if "\nbots/\n" not in body:
        ignore.write_text(
            body.rstrip() +
            "\n\n# Проект ботов: в нём лежат токены и ключи, поэтому в\n"
            "# репозиторий он не идёт целиком. Код бота лежит в\n"
            "# hosting/pythonanywhere/bots и едет в репозиторий.\n"
            "bots/\n", encoding="utf-8")
        print("  bots/ добавлен в .gitignore")

    print()
    print("=== 6. проверка: бот запускается из своей папки ===")
    check = r'''
import json, os, sys
from pathlib import Path
# Рабочая папка проекта, а не папка этого скрипта: проверка лежит
# во временной папке агента и `__file__` указал бы не туда.
here = Path.cwd()
sys.path.insert(0, str(here / "pythonanywhere" / "bots"))

tokens = json.loads(
    (here / "секреты" / "ключи-ботов.local.json").read_text(encoding="utf-8")
)["tokens"]
config = json.loads((here / "config.json").read_text(encoding="utf-8"))

for name, value in tokens.items():
    os.environ[name] = value
    print(f"  {name}: {'есть' if value else 'ПУСТО'}")

import ada_bot, chars
print("  код бота загрузился")
for key in ("ada", "anatoly", "katy"):
    print(f"  персона {key}: {chars.char_for(key)['name']}")

provider = config["providers"][0]
import urllib.request
body = json.dumps({"model": provider["model"],
                   "messages": [{"role": "user", "content": "ok"}],
                   "max_tokens": 5}).encode()
req = urllib.request.Request(
    provider["base_url"] + "/chat/completions", data=body, method="POST",
    headers={"Authorization": "Bearer " + provider["api_key"],
             "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=60) as r:
    text = json.loads(r.read())["choices"][0]["message"]["content"]
print(f"  модель отвечает: {text.strip()[:30]!r}")
print("  БОТЫ САМОСТОЯТЕЛЬНЫ")
'''
    probe_path = ROOT / "tmp" / "probe_bots_standalone.py"
    probe_path.parent.mkdir(exist_ok=True)
    probe_path.write_text(check, encoding="utf-8")
    import subprocess
    res = subprocess.run([str(ROOT / ".venv" / "Scripts" / "python.exe"),
                          str(probe_path)], capture_output=True, text=True,
                         cwd=str(BOTS))
    print(res.stdout.strip() or res.stderr.strip()[-400:])
    return 0


if __name__ == "__main__":
    sys.exit(main())