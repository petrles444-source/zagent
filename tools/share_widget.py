r"""Собрать общий виджет агента в `shared/` и убрать копии из папок.

Зачем
----
Виджет ИИ-агента — одна и та же программа для всех страниц сайта.
Раньше он копировался в каждую папку: восемь одинаковых копий `ai.js`,
восемь `ai.css`, семь `ai.json` — больше сотни килобайт, которые
расходятся при первой же правке. Сейчас он лежит один раз в `shared/`,
а страницы подключают его по абсолютному пути.

Что важно понимать про пути
---------------------------
Страницы лежат в разных папках (`/archive/`, `/guide/aurum/` и так
далее), поэтому ссылка на общий файл должна быть абсолютной — от корня
сайта. Внутренние адреса самого виджета (шрифты, картинки) при этом
не ломаются: стили подключаются к конкретной странице, и браузер
ищет `url()` относительно неё, а не относительно файла стилей.

Почему `ai.json` тоже один
--------------------------
Раньше настройки копировались в каждую папку, но адрес прокси у всех
страниц один и тот же: это свойство сервера, а не страницы. Виджет
теперь сам выводит путь к настройкам из адреса собственного скрипта
(см. комментарий в `ai.js`), поэтому копия рядом со скриптом — ровно
та, что нужна, и ломаться не может.

Запуск:
    .venv\\Scripts\\python.exe tools\\share_widget.py
    .venv\\Scripts\\python.exe tools\\share_widget.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "site" / "assets"
SHARED = ROOT / "site" / "shared"

#: Исходники виджета живут в assets/, потому что оттуда их забирает
#: сборщик главной страницы. В shared/ попадают копии.
WIDGET = ("ai.js", "ai.css")

#: Папки, из которых виджет вычищается после того, как shared/ собран.
#: Корень сайта в списке: главная и витрина тоже подключали виджет
#: своими копиями.
FOLDERS = [
    ROOT / "site",
    ROOT / "site" / "guide",
    ROOT / "site" / "archive",
    ROOT / "portfolios" / "aurum",
    ROOT / "portfolios" / "lumen",
    ROOT / "portfolios" / "neon",
    ROOT / "portfolios" / "onyx",
    ROOT / "portfolios" / "paper",
    ROOT / "portfolios" / "term",
]

#: Настройки кладутся только в shared/: адрес прокси общий для всех.
#: Проверка на «файл есть» — см. docstring.
CONFIG = "ai.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="собрать общий виджет")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать, что изменится, и не писать")
    args = parser.parse_args()

    if not args.dry_run:
        SHARED.mkdir(parents=True, exist_ok=True)

    for name in WIDGET:
        source = ASSETS / name
        if not source.is_file():
            print(f"нет исходника {source}", file=sys.stderr)
            return 2
        if args.dry_run:
            print(f"соберу      shared/{name}")
        else:
            shutil.copy2(source, SHARED / name)
            print(f"собран      shared/{name}")

    # Настройки: берём из site-dist, если он уже собран, иначе — из
    # assets. В site-dist они лежат потому, что прошлая сборка их
    # положила; настройки меняются адресом прокси, и терять их нельзя.
    config_source = ROOT / "site-dist" / CONFIG
    if not config_source.is_file():
        config_source = ASSETS / CONFIG
    if not config_source.is_file():
        print(f"нет настроек {CONFIG} — создайте пустой", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"соберу      shared/{CONFIG} (из {config_source.parent.name})")
    else:
        shutil.copy2(config_source, SHARED / CONFIG)
        print(f"собран      shared/{CONFIG} (из {config_source.parent.name})")

    removed = 0
    freed = 0
    for folder in FOLDERS:
        if folder == SHARED or not folder.is_dir():
            continue
        for name in (*WIDGET, CONFIG):
            stale = folder / name
            if not stale.is_file():
                continue
            size = stale.stat().st_size
            if args.dry_run:
                print(f"уберу       {stale.relative_to(ROOT)}")
            else:
                stale.unlink()
                print(f"убран       {stale.relative_to(ROOT)}")
            removed += 1
            freed += size

    print(f"\nкопий убрано: {removed}, освобождено {freed / 1024:.1f} КБ")
    if args.dry_run:
        print("это был просмотр: ничего не записано")
    return 0


if __name__ == "__main__":
    sys.exit(main())
