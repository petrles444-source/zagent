r"""Переименовать пять рекламных страниц и разложить по папкам.

Зачем
----
Папки назывались по теме (`pizza`, `dental`) — это описание, а не
имя. В адресе описание быстро устаревает: тема сменится, а папка
останется, и адрес начнёт врать. Поэтому папка называется коротким
словом бренда, а тема живёт в заголовке страницы.

Как выбирались имена
--------------------
Имя должно быть коротким, состоять из латиницы и не совпадать с уже
занятыми папками. Проверяется последним: если папка уже есть —
имя не подходит, и это вскрылось бы на сервере как смешанная витрина.

Что делается
------------
1. Папка переименовывается.
2. В заголовке и в первом абзаце остаётся тема — она и должна там быть.
3. Картинки переименовываются в `hero.jpg` и `card-N.jpg`: имена
   макетов по-русски и с пробелами ломаются по FTP.
4. Устаревшие копии со старыми именами удаляются, иначе на сервере
   останутся обе версии.

Запуск:
    .venv\\Scripts\\python.exe tools\\rename_ads.py
    .venv\\Scripts\\python.exe tools\\rename_ads.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

#: было -> стало. Имя короткое, латинское, не пересекается с aurum,
#: lumen, onyx, neon, paper, term, steel, prism, flux, stone, nova,
#: fold, guide, tex, barbie, tovar и demo.
RENAMES = {
    "pizza":   "forno",     # итальянское «печь» — пицца печётся
    "dental":  "dentalia",  # выдуманное, звучит как клиника
    "wedding": "vow",       # «обет» — коротко и про торжество
    "gym":     "grind",     # « Grind» — и усилие, и жернов
    "neon":    "strobe",    # «вспышка» — то, чем неон и работает
}

TITLE = {
    "pizza": "Пицца с доставкой",
    "dental": "Стоматология",
    "wedding": "Свадебный салон",
    "gym": "Тренировки",
    "neon": "Неоновая вечеринка",
}

#: Занятые папки: сюда нельзя вести имя.
#:
#: Сюда НЕ входят новые имена из RENAMES: иначе проверка сравнивает
#: список сам с собой, находит пересечение в каждом имени и
#: отказывается работать, не сделав ничего.
TAKEN = {
    "assets", "guide", "barbie", "tex", "tovar", "demo", "ruffle", "swf",
    "aurum", "lumen", "onyx", "neon", "paper", "term", "steel",
    "prism", "flux", "stone", "nova", "fold", "shared",
} | set(RENAMES)


def fix_refs(folder: Path) -> int:
    """Переименовать картинки в короткие имена и поправить разметку."""
    index = folder / "index.html"
    if not index.is_file():
        return 0

    html = index.read_text(encoding="utf-8")
    mapping: dict[str, str] = {}

    counter = 0
    for item in sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.png")):
        if item.name in ("hero.jpg",) or item.name.startswith("card-"):
            continue
        new = "hero.jpg" if counter == 0 else f"card-{counter}.jpg"
        counter += 1
        mapping[item.name] = new
        item.replace(folder / new)

    if not mapping:
        return 0

    for old, new in mapping.items():
        html = html.replace(f'"{old}"', f'"{new}"')
    index.write_text(html, encoding="utf-8")
    return len(mapping)


def main() -> int:
    parser = argparse.ArgumentParser(description="переименовать рекламные папки")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    clashing = TAKEN & set(RENAMES.values())
    if clashing:
        print(f"имена пересекаются с занятыми: {', '.join(sorted(clashing))}",
              file=sys.stderr)
        return 2

    for old, new in RENAMES.items():
        source = SITE / old
        target = SITE / new
        title = TITLE.get(old, old)

        if not source.is_dir() and not target.is_dir():
            print(f"нет папки: site/{old}", file=sys.stderr)
            return 2

        print(f"site/{old:9} -> site/{new:9}  {title}")

        if args.dry_run:
            continue

        if source.is_dir() and not target.exists():
            source.rename(target)
        elif source.is_dir() and target.exists():
            # Обе папки на месте: предыдущий запуск не добил до конца.
            # Содержимое сливается, лишнее удаляется — иначе на сервере
            # останутся две версии страницы под разными именами.
            for item in source.iterdir():
                dest = target / item.name
                # ?????? ???? ???????? ??????, ? ?? ????????.
                #
                # ?????? ????? ?????? ????????: ??? ?????????? ????
                # ???????? ???? ?? `source`, ?? ???? ?????? ???
                # ???????????????, ? ????????? ?????? ?? `target`.
                # ?????? ? ?????????? ?? ??????? ?? ????????, ????????
                # ?????????? ?????????? ??????? ?????, ? ??? ?????????
                # ???, ????? ?????? ?? ????. ??????? ????? ? ????
                # ????? ????? ???????.
                if dest.exists():
                    dest.unlink()
                item.replace(dest)
            source.rmdir()
            print(f"  (папки обе были на месте, содержимое слито)")

        changed = fix_refs(target)
        if changed:
            print(f"  картинок переименовано: {changed}")

    if args.dry_run:
        print("\nэто был просмотр: ничего не переименовано")
        return 0

    # Проверка: остались ли папки со старыми именами.
    leftover = [old for old in RENAMES if (SITE / old).is_dir()]
    if leftover:
        print(f"\nстарые папки остались: {', '.join(leftover)}", file=sys.stderr)
        return 1

    print("\nготово. новые адреса:")
    for new in RENAMES.values():
        print(f"  https://zagent.do.am/{new}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
