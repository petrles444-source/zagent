r"""Разнести проект по папкам: что остаётся в zagent, что уходит рядом.

Зачем
----
В корне `zagent` лежало 43 папки вперемешку: ядро агента, сайты,
боты, отдельные приложения и три тяжёлые папки на 11,7 ГБ. Агент,
боты и сайты — одно связанное целое, а `content/Photopost`,
`WaveLora/` и `models/` к агенту отношения не имеют и только мешают:
занимают место, попадают в поиск и в бэкапы.

Что куда
--------
Остаётся в `zagent` (это репозиторий агента):

* ядро: `hub/`, `providers/`, `config/`, `bench/`, `tests/`, `tools/`;
* боты: `hosting/`, `bot-worker/`, `projects/`;
* сайты: `site/`, `site-dist/`, `portfolios/`, `publish/`;
* служебное: `docs/`, `reports/`, `ref/`, `tasks/`.

Уходит рядом, в `../` (это отдельные программы):

* `content/Photopost` → `../photopost` — 5,5 ГБ, фотохостинг;
* `WaveLora` → `../WaveLora` — 2,7 ГБ, ComfyUI;
* `models` → `../lora-models` — 3,5 ГБ, веса LoRA;
* `allvpn` → `../allvpn`, `vpn` → `../vpn` — клиенты VPN;
* `colab` → `../colab` — ноутбуки для Colab.

Почему именно так
-----------------
Проверено, что код агента не ссылается ни на `WaveLora`, ни на
`content/Photopost`, ни на `models`. Единственная ссылка была из
`tools/gen_abstract.py`, и она правится здесь же.

Почему `models` переименован в `lora-models`
---------------------------------------------
В `../models` уже лежит `FreeQwenApi` — это другое, к генерации
отношения не имеет. Простое перемещение перемешало бы два разных
смысла в одной папке, поэтому имя уточнено.

Запуск:
    .venv\\Scripts\\python.exe tools\\reorganize_root.py
    .venv\\Scripts\\python.exe tools\\reorganize_root.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTSIDE = ROOT.parent

#: Что уходит из zagent: (откуда, куда, зачем).
#:
#: Куда указывает путь относительно родителя zagent. Имена в правой
#: части выбраны так, чтобы не столкнуться с уже существующими
#: папками: в `../models` лежит `FreeQwenApi`, это другое.
MOVES_OUT = (
    ("content/Photopost", "photopost",
     "фотохостинг, 5,5 ГБ, к агенту отношения не имеет"),
    ("WaveLora", "WaveLora",
     "ComfyUI, 2,7 ГБ, к агенту отношения не имеет"),
    ("models", "lora-models",
     "веса LoRA, 3,5 ГБ, переименовано: в ../models лежит другое"),
    ("allvpn", "allvpn",
     "клиент VPN, к агенту отношения не имеет"),
    ("vpn", "vpn",
     "набор VPN-конфигов, к агенту отношения не имеет"),
    ("colab", "colab",
     "ноутбуки для Colab, запускаются в браузере"),
)

#: Что остаётся в zagent. Перечислено явно, а не «всё остальное»:
#: так неожиданная новая папка не уедет молча наружу.
KEEP = (
    "hub", "providers", "config", "bench", "tests", "tools",
    "hosting", "bot-worker", "projects",
    "site", "site-dist", "portfolios", "publish",
    "docs", "reports", "ref", "tasks",
)

#: Служебное, что удаляется: временное, кэши и остатки отладки.
#: Проверено содержимое каждого — пустые ли они.
#: Проверено перед удалением, а не по имени. Два пункта из первого
#: списка пришлось убрать после проверки:
#:
#: * `screenshots/web.png` — НЕ дубликат: в `site/` такого файла нет,
#:   и он единственный снимок интерфейса. Удалять нельзя.
#: * `cache.db` — никто не ссылается, но файл может создаваться при
#:   работе; оставлен, потому что 32 КБ не стоят риска.
DROP = {
    "pytest-of-HP": "каталоги pytest: 1710 файлов в tmp, а здесь копия",
    "dist": "пустая папка, осталась от прежней сборки",
    "__pycache__": "кэш байткода",
    ".pytest_cache": "кэш pytest",
    "tmpynhcdjoj": "пустая папка от mkdtemp",
    "zagent_radio_live_8x158_2w": "база радио уже есть в web-state",
    "backup": "zip-бэкап на 8,5 МБ, заменяется git",
}

#: Файлы в корне, которые больше не нужны: временные дампы выгрузки,
#: которые так и остались лежать. `cache.db` убран из списка — см.
#: выше.
DROP_FILES = (
    "tmp_up.txt", "tmp_up_err.txt", "nul", "t.json",
)


def size_of(path: Path) -> tuple[int, int]:
    files = [f for f in path.rglob("*") if f.is_file()]
    return len(files), sum(f.stat().st_size for f in files)


def show(doing: str, path: Path, extra: str = "") -> None:
    try:
        count, size = size_of(path)
        print(f"  {doing} {path.name:<26} {size / 1024 / 1024:>8.1f} МБ  "
              f"{count:>6} файлов  {extra}")
    except OSError:
        print(f"  {doing} {path.name:<26} (не удалось измерить)")


def main() -> int:
    parser = argparse.ArgumentParser(description="разнести проект по папкам")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("ПРОСМОТР. Ничего не перемещается.\n")

    print("=" * 70)
    print("УХОДИТ ИЗ zagent")
    print("=" * 70)
    for src_rel, dst_name, why in MOVES_OUT:
        src = ROOT / src_rel
        dst = OUTSIDE / dst_name
        if not src.exists():
            print(f"  нет папки {src_rel} — пропускаю")
            continue
        if dst.exists():
            print(f"  {dst_name} уже есть на месте — пропускаю "
                  "(ничего не перезаписываю)")
            continue
        show("уйдёт:", src, why)
        if not args.dry_run:
            shutil.move(str(src), str(dst))
            print(f"           → {dst}")

    print()
    print("=" * 70)
    print("УДАЛЯЕТСЯ")
    print("=" * 70)
    for name, why in DROP.items():
        path = ROOT / name
        if not path.exists():
            print(f"  нет {name} — пропускаю")
            continue
        show("удалится:", path, why)
        if not args.dry_run and not args.dry_run:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    for name in DROP_FILES:
        path = ROOT / name
        if not path.is_dir() and path.exists():
            print(f"  удалится {name}  {path.stat().st_size} Б")
            if not args.dry_run:
                path.unlink(missing_ok=True)

    print()
    print("=" * 70)
    print("ОСТАЁТСЯ В zagent")
    print("=" * 70)
    for name in KEEP:
        path = ROOT / name
        if not path.exists():
            print(f"  {name} — нет, ожидался")
            continue
        show("останется:", path)

    print()
    print("=" * 70)
    print("ЧТО ОКАЖЕТСЯ В КОРНЕ — и почему")
    print("=" * 70)
    leftovers = [p.name for p in sorted(ROOT.iterdir())
                 if p.is_dir() and p.name not in KEEP
                 and not p.name.startswith(".")
                 and (ROOT / p.name) is not None]
    print("  Папки рядом с ядром, которые не разнесены:")
    for name in leftovers:
        print(f"    {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())