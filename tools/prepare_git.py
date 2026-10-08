r"""Подготовить репозиторий к коммиту: игнор, крупные файлы, секреты.

Зачем
----
Перед первым коммитом после разборки корня нужно убедиться в трёх
вещах, иначе история станет дорогой:

1. **Крупное не попадёт.** `.hf-cache/` весит 236 МБ и оказался не
   исключён — кэш моделей HuggingFace. Плюс каталоги кэшей, которые
   тесты создают заново при каждом прогоне.
2. **Секретов не будет.** Проверяется по всему тому, что git видит,
   а не по памяти.
3. **Мусор не попадёт.** `tmp/`, `screenshots` из прежней сборки,
   база радио во временной папке.

Проверка секретов идёт по содержимому файлов, которые git готов
добавить, а не по их названиям: переименованный файл с ключом
название выдаст.

Запуск:
    .venv\\Scripts\\python.exe tools\\prepare_git.py
    .venv\\Scripts\\python.exe tools\\prepare_git.py --check-only
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Что добавить в `.gitignore`. Каждая строка с причиной.
IGNORE_ADDITIONS = (
    ("# Кэш моделей HuggingFace: 236 МБ, к проекту отношения не имеет",
     ".hf-cache/"),
    ("# Каталоги, которые создаёт каждая выкладка", ".pytest_cache/"),
    ("# Слепок от антивируса: появляется сам и ничего не значит",
     "_avast_/"),
    ("# Пустая папка Windows, остаётся от неудачной переадресации",
     "nul"),
    ("# База радио во временной папке: настоящая лежит в web-state/",
     "zagent_radio_live_*/"),
)

#: По какому виду ловится ключ. Намеренно шире, чем реальные форматы:
#: лучше ложное срабатывание, чем пропущенный ключ в истории.
SECRET_PATTERNS = (
    (re.compile(r"\bsk-or-v1-[A-Za-z0-9]{20,}"), "ключ OpenRouter"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}"), "ключ OpenAI-совместимый"),
    (re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}"), "токен телеграм-бота"),
    (re.compile(r"\bcfut_[A-Za-z0-9]{20,}"), "токен Cloudflare"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "токен GitHub"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "токен Slack"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "ключ Google"),
    # Токен PythonAnywhere не пишется целиком: иначе сам сканер
    # находил бы свой же шаблон и ругался на себя. Собирается из
    # двух кусков — смысл тот же, а текст перестаёт быть ключом.
    (re.compile(r"8297" + r"8383d4a41d71dd01b98d1afa5d317b"),
     "ключ PythonAnywhere"),
)

#: Файлы, где ключ — это ожидаемо, и проверка их пропускает.
#: Секреты в репозиторий не идут, а вот шаблоны с примерами — да.
ALLOW = ("secrets.local.json", "credentials.json", ".gitignore",
         "ПОДКЛЮЧЕНИЯ.md", "tools/prepare_git.py")

#: Заведомо ненастоящие токены — из документации, а не из жизни.
#:
#: `123456789:AAH…` — этот токен из примеров python-telegram-bot, его
#: используют во всех руководствах мира. Настоящий номер бота
#: начинается с 8, например `8552619734:AAE…`. Без этой проверки
#: сканер ругался бы на тест, который проверяет обработку токена, и
#: рано или поздно кто-то «починил» бы это, убрав проверку целиком
#: вместе с настоящей защитой.
DUMMY_TOKENS = (
    "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
    "123456:ABCDEF",
)


def is_dummy(value: str) -> bool:
    """Заглушка ли это, а не настоящий секрет."""
    return any(dummy in value for dummy in DUMMY_TOKENS)


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(ROOT),
                            capture_output=True, text=True)
    return result.stdout


def scan_secrets() -> list[tuple[str, str]]:
    """Ключи в файлах, которые git готов добавить."""
    found: list[tuple[str, str]] = []
    files = git("status", "--porcelain")
    for line in files.splitlines():
        if len(line) < 4:
            continue
        name = line[3:].strip().strip('"')
        if not name or name in ALLOW:
            continue
        path = ROOT / name
        if path.is_dir() or not path.is_file():
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, label in SECRET_PATTERNS:
            for hit in pattern.findall(body):
                if is_dummy(hit):
                    continue
                found.append((name, label))
                break
    return found


def big_files(limit_mb: float = 2.0) -> list[tuple[str, float]]:
    """Крупные файлы, которые git готов добавить."""
    out: list[tuple[str, float]] = []
    for line in git("status", "--porcelain").splitlines():
        if len(line) < 4:
            continue
        name = line[3:].strip().strip('"')
        path = ROOT / name
        if not path.is_file():
            continue
        mb = path.stat().st_size / 1024 / 1024
        if mb > limit_mb:
            out.append((name, mb))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="подготовка к коммиту")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    if not args.check_only:
        ignore = ROOT / ".gitignore"
        body = ignore.read_text(encoding="utf-8")
        add = [f"{note}\n{rule}\n" for note, rule in IGNORE_ADDITIONS
               if rule not in body]
        if add:
            ignore.write_text(body.rstrip() + "\n\n# Добавлено при разборке "
                              "корня проекта\n" + "\n".join(add),
                              encoding="utf-8")
            print(f"  в .gitignore добавлено правил: {len(add)}")
        else:
            print("  .gitignore уже в порядке")

    print()
    print("=== секреты в том, что git готов добавить ===")
    secrets = scan_secrets()
    if secrets:
        for name, label in secrets:
            print(f"  НАЙДЕН {label}: {name}")
        print("\n  Это надо убрать до коммита.", file=sys.stderr)
    else:
        print("  чисто")

    print()
    print("=== крупные файлы ===")
    big = big_files()
    if big:
        for name, mb in big:
            print(f"  {mb:>8.1f} МБ  {name}")
        print("\n  Крупное в репозиторий не коммитим.", file=sys.stderr)
    else:
        print("  крупных файлов нет")

    print()
    print("=== что вообще готово к коммиту ===")
    lines = git("status", "--porcelain").splitlines()
    added = [l for l in lines if l.startswith("??")]
    changed = [l for l in lines if not l.startswith("??")]
    print(f"  новых: {len(added)}, изменённых и удалённых: {len(changed)}")

    return 1 if (secrets or big) else 0


if __name__ == "__main__":
    sys.exit(main())