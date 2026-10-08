r"""Подключить виджет агента к трём гайдам и дать им безопасные имена.

Зачем
----
В `site/` лежат три готовые страницы-гайда, но имена у них с пробелами
и тире: `VK API Guide — Extended Documentation.html`. Такое имя нужно
процент-кодировать в каждой ссылке, а по FTP оно ломается куда хуже, чем
просто неудобно. Поэтому файл переезжает в короткий адрес, а сам текст
страницы не меняется ни на байт.

Что добавляется
----------------
Только виджет: стиль, скрипт и тег голоса. Голос один и тот же —
Анатолий: все три страницы про код, и объяснять их должен тот, кто
объясняет код.

Запуск:
    .venv\Scripts\python.exe tools\add_guides.py
    .venv\Scripts\python.exe tools\add_guides.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
ASSETS = ROOT / "site" / "assets"

#: (старое имя, новое имя, заголовок, роль)
#:
#: Голос и подписи — как в tools/add_ai.py, но здесь они свои: страницы
#: другие и объясняющий должен представляться иначе.
GUIDES: tuple[tuple[str, str, str, str, str], ...] = (
    ("VK API Guide — Extended Documentation.html", "vk-api.html",
     "Анатолий", "справочник по VK API", "guide"),
    ("Pandas Guide — Extended Documentation.html", "pandas.html",
     "Анатолий", "разбор pandas", "anatoly"),
    ("OpenCV Guide — Extended Documentation.html", "opencv.html",
     "Анатолий", "разбор OpenCV", "anatoly"),
    ("neural.html", "neural.html",
     "Анатолий", "энциклопедия нейросетей", "anatoly"),
)

#: Страницы, которые лежат не в проекте, а в папке загрузок: их нужно
#: сначала забрать оттуда. После копирования правка идёт уже по файлу
#: в проекте, поэтому вторая сборка в загрузки не полезет.
DOWNLOADS: tuple[tuple[str, str, str, str, str], ...] = (
    ("Neural Networks Encyclopedia — Deep Dive.html", "neural.html",
     "Анатолий", "энциклопедия нейросетей", "anatoly"),
)

GREETING = ("Спросите про любой пример со страницы: почему он такой, "
            "что он делает по шагам и как его проверить.")


def head_block(persona: str, agent: str, role: str) -> str:
    """Строки для вставки в <head>."""
    meta = json.dumps({"persona": persona, "agent": agent, "role": role,
                       "greeting": GREETING}, ensure_ascii=False)
    return "\n".join((
        '<link rel="stylesheet" href="ai.css">',
        f'<meta name="zagent-ai" content=\'{meta}\'>',
        '<script src="ai.js" defer></script>',
    ))


def add_widget(html: str, persona: str, agent: str, role: str) -> str:
    """Вставить подключение перед </head>. Повторный запуск не дублирует."""
    if 'name="zagent-ai"' in html:
        return re.sub(r'<meta name="zagent-ai" content=\'.*?\'>',
                      head_block(persona, agent, role).splitlines()[1],
                      html, count=1, flags=re.S)
    if "</head>" not in html:
        raise SystemExit("нет </head>")
    return html.replace("</head>", head_block(persona, agent, role) + "\n</head>", 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="гайды: имена и виджет")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for name in ("ai.js", "ai.css"):
        if not (ASSETS / name).is_file():
            print(f"нет {name} в assets — виджет нечем подключать", file=sys.stderr)
            return 2

    # Страницы из загрузок забираем в проект: источником правды дальше
    # будет файл здесь, а не копия в папке загрузок.
    downloads = Path.home() / "Downloads"
    for old_name, new_name, agent, role, persona in DOWNLOADS:
        origin = downloads / old_name
        if not origin.is_file():
            print(f"в загрузках нет: {old_name} — пропускаю", file=sys.stderr)
            continue
        if not args.dry_run:
            shutil.copy2(origin, SITE / new_name)
        print(f"{'забрал бы' if args.dry_run else 'забрал'}      "
              f"{old_name} -> site/{new_name}")

    for old_name, new_name, agent, role, persona in GUIDES:
        old = SITE / old_name
        new = SITE / new_name

        # Страница должна быть либо уже в проекте, либо ещё лежать
        # в загрузках: в режиме просмотра копии из загрузок не
        # происходит, и проверка не должна ругаться на нормальное
        # состояние дел.
        pending = tuple(
            d for d in DOWNLOADS
            if (downloads / d[0]).is_file() and d[1] == new_name)
        if not old.is_file() and not new.is_file() and not pending:
            print(f"нет страницы: {old_name}", file=sys.stderr)
            return 2

        # Переименование выполняется один раз: при повторном запуске
        # старого файла уже нет, и работаем с новым именем.
        source = old if old.is_file() else new
        target = new

        if source != target and not args.dry_run:
            source.replace(target)

        if args.dry_run:
            print(f"{'переименую' if source != target else 'оставлю':12} "
                  f"{source.name} -> {target.name}")
            continue

        html = target.read_text(encoding="utf-8")
        updated = add_widget(html, persona, agent, role)
        if updated != html:
            target.write_text(updated, encoding="utf-8")
            print(f"подключён      {target.name:16} голос: {persona}")
        else:
            print(f"без изменений  {target.name}")

    print("\nготово")
    return 0


if __name__ == "__main__":
    sys.exit(main())