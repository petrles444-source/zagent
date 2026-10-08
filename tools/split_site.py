r"""Разложить сайт по папкам: главная, гайды, витрина.

Зачем
----
Каждая страница сайта лежала в корне вперемешку с чужими файлами, и
все ссылки на неё выглядели одинаково: `/index.html`, `/pandas.html`,
`/opencv.html`. Три страницы гайдов отличались от главной только
именем файла — их невозможно было отличить друг от друга в списке
файлов, не открывая каждый.

После разбора на сервере будет так:

    /                 витрина всех страниц (бывший catalog.html)
    /archive/         Neural Archive — главная страница с архивом
    /guide/           четыре справочника с примерами кода
    /aurum/ … /term/  шесть подач портфолио (уже в папках)
    /shared/          общий виджет ИИ-агента

Что важно про главную
---------------------
Главная уезжает в папку, поэтому у неё меняется адрес: был
`/index.html`, станет `/archive/`. Витрина в корне остаётся
`index.html` — иначе на сайте не будет входа, и открывать пришлось бы
вспоминать адрес.

Что важно про пути внутри страниц
---------------------------------
Раньше сборщик «расплющивал» все файлы в корень и переписывал ссылки
(`assets/style.css` → `style.css`). Теперь структура папок
настоящая, и переписывать ничего не нужно: главная внутри `archive/`
продолжает ссылаться на `assets/…`, и эти файлы лежат рядом с ней.
Сборщик поэтому больше не переписывает пути — см. tools/build_site.py.

Запуск:
    .venv\\Scripts\\python.exe tools\\split_site.py
    .venv\\Scripts\\python.exe tools\\split_site.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

#: Куда переезжает главная. Имя совпадает с названием сайта.
ARCHIVE = SITE / "archive"

#: Папка справочников.
GUIDE = SITE / "guide"

#: Главная со всем её хозяйством: страница, стили, движок проигрывания
#: флеш-работ, сами работы и шрифты. Список папок копируется целиком.
MOVE_DIRS = ("assets", "ruffle", "swf")

#: Гайды: было в корне с плоскими именами, станет в guide/ с теми же
#: именами файлов — адрес сдвинется на один уровень, сами имена
#: понятны и пробелов не содержат.
GUIDES = ("neural.html", "pandas.html", "opencv.html", "vk-api.html")

#: Витрина из корня становится index.html: корень сайта должен что-то
#: отдавать по умолчанию.
CATALOG = SITE / "catalog.html"


def move(source: Path, target: Path, dry: bool) -> None:
    """Перенести файл или папку, сообщив что получилось."""
    if not source.exists():
        print(f"  нет, пропускаю: {source.relative_to(ROOT)}")
        return
    if dry:
        print(f"  {source.relative_to(ROOT)}  ->  {target.relative_to(ROOT)}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Куда-то уже переехало: с прошлого прогона. Молчаливый
        # пропуск скрыл бы рассинхронизацию папок.
        print(f"  уже на месте, пропускаю: {target.relative_to(ROOT)}")
        return
    shutil.move(str(source), str(target))
    print(f"  {source.relative_to(ROOT)}  ->  {target.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="разложить сайт по папкам")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = args.dry_run

    print("главная Neural Archive -> archive/")
    move(SITE / "index.html", ARCHIVE / "index.html", dry)
    move(SITE / "favicon.ico", ARCHIVE / "favicon.ico", dry)
    move(SITE / "favicon.png", ARCHIVE / "favicon.png", dry)
    for name in MOVE_DIRS:
        move(SITE / name, ARCHIVE / name, dry)

    print("\nгайды -> guide/")
    if not dry:
        GUIDE.mkdir(parents=True, exist_ok=True)
    for name in GUIDES:
        move(SITE / name, GUIDE / name, dry)

    print("\nвитрина -> index.html в корне")
    move(CATALOG, SITE / "index.html", dry)

    if dry:
        print("\nэто был просмотр: ничего не перемещено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
