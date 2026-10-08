r"""Найти каталог сайтов, даже если проект уехал из агента.

Зачем
----
`bot_proxy.py` — инструмент агента, он остался в агенте. Но он
читает каталог сайтов, а проект сайтов теперь лежит рядом, в
`../portfolio/`. Путь был зашит как `корень агента / site`, и после
переноса он указывал в никуда.

Раньше это молча работало: `catalog_line()` проверяет время
изменения и при отсутствии файла просто отдаёт пустую строку. То
есть бот перестал знать состав каталога и никто об этом не узнал —
именно так и выглядит поломка, о которой узнают через месяц.

Что делается
------------
Путь ищется в трёх местах по порядку:

1. рядом с агентом — если каталоги всё-таки лежат в `site/`;
2. в проекте сайтов рядом, `../portfolio/site/`;
3. иначе остаётся первый путь, и файл просто не найдётся.

Тот же порядок применён в тесте, который читает каталог напрямую.
Иначе проверка проверяла бы одно место, а код искал бы другое —
и расходились бы они молча.

Запуск:
    .venv\\Scripts\\python.exe tools\\fix_catalog_path.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = (
    ROOT / "tools" / "bot_proxy.py",
    ROOT / "tests" / "test_bot_proxy.py",
)

HELPER = '''
def find_site_dir() -> Path:
    """Папка с сайтами, где бы проект ни лежал.

    Каталог сайтов вынесен из агента в соседний проект, и путь к нему
    больше нельзя писать жёстко: было `корень агента / site`.

    Проверяются места по порядку — своё рядом с агентом, потом
    соседний проект. Первое найденное и есть ответ; если ничего не
    нашлось, возвращается ожидаемое путь: файл просто не найдётся,
    и код это переживёт, а не упадёт.

    Раньше путь был один и жёсткий, а `catalog_line()` при
    отсутствии файла отдавал пустую строку. Бот переставал знать
    состав каталога, и ничего об этом не сообщал.
    """
    candidates = (
        Path(__file__).resolve().parent.parent / "site",
        Path(__file__).resolve().parent.parent.parent
        / "portfolio" / "site",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]
'''


def main() -> int:
    bot = ROOT / "tools" / "bot_proxy.py"
    if not bot.is_file():
        print("bot_proxy.py не найден", file=sys.stderr)
        return 1

    body = bot.read_text(encoding="utf-8-sig")

    if "find_site_dir" in body:
        print("  путь уже устойчивый")
        return 0

    old = ('CATALOG_FILE = Path(__file__).resolve().parent.parent / "site" '
           '/ "assets" / "catalog.json"')
    if old not in body:
        print(f"  строка с путём не найдена, искать вручную", file=sys.stderr)
        return 1

    new = HELPER.strip() + '\n\nCATALOG_FILE = find_site_dir() / "assets" \\\n' \
        '    / "catalog.json"'

    body = body.replace(old, new, 1)
    bot.write_text(body, encoding="utf-8-sig")

    import ast
    ast.parse(body)
    print("  bot_proxy.py: путь к каталогу стал устойчивым")

    # Тест читает каталог напрямую — поправить так же.
    test = ROOT / "tests" / "test_bot_proxy.py"
    if test.is_file():
        tbody = test.read_text(encoding="utf-8-sig")
        t_old = '(ROOT / "site" / "assets" / "catalog.json")'
        if t_old in tbody:
            t_new = '(bot.find_site_dir() / "assets" / "catalog.json")'
            test.write_text(tbody.replace(t_old, t_new, 1), encoding="utf-8-sig")
            ast.parse(test.read_text(encoding="utf-8-sig"))
            print("  test_bot_proxy.py: путь синхронизирован с кодом")

    # Проверка: каталог находится и читается.
    sys.path.insert(0, str(ROOT / "tools"))
    import bot_proxy
    found = bot_proxy.find_site_dir()
    print(f"  каталог сайтов: {found}")
    print(f"  существует: {found.is_dir()}")
    line = bot_proxy.catalog_line()
    print(f"  бот читает каталог: {'да' if line else 'НЕТ'}")
    if not line:
        print("  ПУСТО — каталог не читается", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())