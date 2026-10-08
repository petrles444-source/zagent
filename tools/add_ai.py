r"""Раздать виджет ИИ-агента по всем страницам сайта.

Зачем
----
Виджет один и тот же, а страниц семь: главная, каталог и шесть подач
портфолио. Копировать его руками в каждый html — значит через месяц
забыть про одну из них. Здесь страница правится один раз, и сразу
проверяется, что подключение на месте.

Что делается
------------
1. Копируются `ai.js` и `ai.css` в папку каждой страницы: файлы лежат
   рядом, внешних загрузок на хостинге быть не может.
2. В `<head>` добавляются две ссылки на стиль и один скрипт.
3. Добавляется `<meta name="zagent-ai">` с голосом страницы: прокси
   по нему выбирает, кто отвечает.

Почему meta, а не data-атрибут на body
---------------------------------------
Значение читается как JSON, и такой способ не ломает разметку, если
в строке есть кавычки: экранировать всё равно пришлось бы, а при
ошибке разбора страница просто остаётся без голоса, а не падает.

Запуск:
    .venv\Scripts\python.exe tools\add_ai.py
    .venv\Scripts\python.exe tools\add_ai.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "site" / "assets"

AI_JS = ASSETS / "ai.js"
AI_CSS = ASSETS / "ai.css"

#: Что добавлять в <head> страницы. Порядок важен только для читаемости.
HEAD_LINES = (
    '<link rel="stylesheet" href="{css}">',
    '<meta name="zagent-ai" content=\'{meta}\'>',
    '<script src="{js}" defer></script>',
)

#: Страница, куда что раздаём: путь к html и голос агента.
#:
#: Голосы взяты из `tools/bot_proxy.py` и проверяются там же по списку:
#: неизвестное имя молча превратилось бы в базовый голос, и страница
#: отвечала бы не тем, кто она притворяется.
PAGES: tuple[tuple[str, str, str, str], ...] = (
    # (html, голос, имя, роль)
    ("site/index.html", "archivist", "Хранитель архива",
     "про флеш-работы и воспроизведение"),
    ("site/catalog.html", "guide", "Проводник",
     "где что лежит на сайте"),
    ("portfolios/aurum/index.html", "guide", "Проводник",
     "золотая подача портфолио"),
    ("portfolios/lumen/index.html", "anatoly", "Анатолий",
     "программист службы поддержки"),
    ("portfolios/onyx/index.html", "guide", "Проводник",
     "тёмная подача портфолио"),
    ("portfolios/neon/index.html", "guide", "Проводник",
     "подача NEON"),
    ("portfolios/paper/index.html", "guide", "Проводник",
     "подача PAPER"),
    ("portfolios/term/index.html", "anatoly", "Анатолий",
     "учит Python в консоли"),
)

#: Приветствие. Кладём в ai.json, а не в разметку: текст длинный, а
#: файл настроек общий для страницы.
GREETING = ("Спросите про проект, про любую из работ или про то, "
            "как всё это собрать у себя.")


def head_block(persona: str, agent: str, role: str, css: str, js: str) -> str:
    """Строки, которые надо вставить в <head>."""
    meta = json.dumps({"persona": persona, "agent": agent, "role": role,
                       "greeting": GREETING}, ensure_ascii=False)
    return "\n".join(line.format(css=css, js=js, meta=meta)
                     for line in HEAD_LINES)


def add_to_head(html: str, block: str) -> str:
    """Вставить блок перед </head>, если его там ещё нет.

    Идемпотентность здесь обязательна: скрипт можно запускать повторно,
    и каждая страница должна получить ровно один подключённый виджет.
    """
    if 'name="zagent-ai"' in html:
        # Уже подключён — обновляем содержимое meta, чтобы смена голоса
        # или имени не требовала ручной правки разметки.
        return re.sub(r'<meta name="zagent-ai" content=\'.*?\'>',
                      block.splitlines()[1], html, count=1, flags=re.S)
    marker = "</head>"
    if marker not in html:
        raise SystemExit("нет </head> — вставлять некуда")
    return html.replace(marker, block + "\n" + marker, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="раздать виджет агента")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать, что изменится, и не писать")
    args = parser.parse_args()

    if not AI_JS.is_file() or not AI_CSS.is_file():
        print("нет site/assets/ai.js или ai.css", file=sys.stderr)
        return 2

    for relative, persona, agent, role in PAGES:
        page = ROOT / relative
        folder = page.parent

        if not page.is_file():
            print(f"нет страницы {relative}", file=sys.stderr)
            return 2

        html = page.read_text(encoding="utf-8")
        # Файлы кладём рядом со страницей: у главной это корень
        # site-dist, у подачи — своя папка. Внешних адресов на хостинге
        # быть не может, поэтому относительный путь — единственный.
        block = head_block(persona, agent, role, "ai.css", "ai.js")
        updated = add_to_head(html, block)

        if args.dry_run:
            changed = "изменится" if updated != html else "без изменений"
            print(f"{changed:15} {relative}")
            continue

        # Копии виджета: одна и та же, но в каждой папке.
        for asset in (AI_JS, AI_CSS):
            shutil.copy2(asset, folder / asset.name)

        page.write_text(updated, encoding="utf-8")
        print(f"подключён      {relative}  голос: {persona}")

    print("\nготово: виджет на всех страницах")
    return 0


if __name__ == "__main__":
    sys.exit(main())