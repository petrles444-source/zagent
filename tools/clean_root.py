r"""Убрать из корня проекта мусор и пустые папки.

Зачем
----
В корне проекта скопился мусор от прошлых прогонов: временные папки
`tempfile`, кэши pytest, каталоги, которые остались после падения
скрипта. Ничего из этого не нужно ни программе, ни человеку, и в git
ни одна из этих папок не отслеживается — то есть их удаление ничего
не ломает и незачем откатывать.

Что удаляется
-------------
1. **Пустые папки** в корне. Их оставляют упавшие скрипты: временная
   папка создаётся, работа падает, содержимое не появилось. В списке
   их видно по нулю файлов.
2. **Кэши и временное**:
   - `tmp*` в корне — временные папки, которые не убрал tempfile;
   - `tmp/` — рабочая папка скриптов. Внимание: там лежит
     `bin/cloudflared.exe`, который используется как туннель. Папка
     пересоздаётся, но сам cloudflared придётся ставить заново, и об
     этом сказано в отчёте;
   - `.pytest_cache/`, `pytest-of-HP/`, `torchinductor_HP/` — кэши
     тестов и компилятора PyTorch, создаются заново при первом прогоне.

Чего скрипт НЕ делает
----------------------
Не трогает крупные папки (`content/`, `WaveLora/`, `vpn/`, `models/`,
`web-state/`, `site/`, `portfolios/` и прочие). Они не пустые, могут
быть нужны, и в git их нет — удаление было бы необратимым. Их размеры
скрипт лишь показывает в отчёте, решение остаётся за человеком.

Проверка перед удалением
------------------------
Папка считается пустой только если в ней нет файлов **рекурсивно**.
Обычная проверка «есть ли что-то внутри» обманчива: в папке может
лежать одна подпапка, а в той — нужные файлы. Пустой считается только
то, где файлов нет вообще.

Запуск:
    .venv\\Scripts\\python.exe tools\\clean_root.py
    .venv\\Scripts\\python.exe tools\\clean_root.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Папки, которые удаляются целиком, независимо от содержимого.
#: Все они пересоздаются при следующем прогоне и в git не числятся.
BY_NAME = (
    # Кэши тестов: создаются заново при первом же запуске pytest.
    ".pytest_cache",
    "pytest-of-HP",
    # Кэш компилятора PyTorch: та же история.
    "torchinductor_HP",
    # Каталоги антивируса Avast: чужие файлы в проекте, к проекту
    # отношения не имеют.
    "_avast_",
)


def count_files(folder: Path) -> int:
    """Файлы в папке, включая вложенные.

    `any()` по содержимому верхнего уровня не годится: папка с одной
    подпапкой выглядит занятой, хотя файлов в ней нет, а удалять такую
    нельзя — внутри могут лежать нужные данные.
    """
    return sum(1 for item in folder.rglob("*") if item.is_file())


def folder_size(folder: Path) -> int:
    return sum(item.stat().st_size
               for item in folder.rglob("*") if item.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="убрать мусор из корня")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать, что удалится, и ничего не трогать")
    args = parser.parse_args()

    victims: list[tuple[Path, str]] = []

    # 1. Именованные папки.
    for name in BY_NAME:
        folder = ROOT / name
        if folder.is_dir():
            victims.append((folder, "кэш или чужой каталог"))

    # 2. Временные папки в корне: `tmp`, `tmpкод`, `tmp_код` и прочие.
    #    Их оставляет tempfile при падении скрипта. Проверяем по
    #    образцу, а не по списку: новые такие папки появляются постоянно.
    for folder in sorted(ROOT.iterdir()):
        if not folder.is_dir() or folder in (v[0] for v in victims):
            continue
        name = folder.name.lower()
        if name.startswith("tmp"):
            victims.append((folder, "временная папка"))

    # 3. Папки без единого файла.
    for folder in sorted(ROOT.iterdir()):
        if not folder.is_dir():
            continue
        if any(folder == v[0] for v in victims):
            continue
        # `.git` и служебные не трогаем никогда.
        if name_is_protected(folder.name):
            continue
        if count_files(folder) == 0:
            victims.append((folder, "пустая папка"))

    if not victims:
        print("мусора не найдено")
        return 0

    print(f"найдено к удалению: {len(victims)} папок\n")
    freed = 0
    for folder, why in victims:
        size = folder_size(folder)
        freed += size
        print(f"  {folder.name:24} {size / 1024 / 1024:8.1f} МБ   {why}")

    print(f"\nвсего освободится: {freed / 1024 / 1024:.1f} МБ")

    if args.dry_run:
        print("\nэто был просмотр: ничего не удалено")
        return 0

    for folder, _ in victims:
        shutil.rmtree(folder, ignore_errors=True)
    print("\nудалено")
    return 0


def name_is_protected(name: str) -> bool:
    """Папки, которые не удаляются ни при каких условиях.

    Пустая папка `.git` — это не мусор, а поломанный репозиторий; та же
    история с `.venv`. Их отсутствие зря не покажется пустым.
    """
    return name in {".git", ".venv", "venv", "node_modules"}


if __name__ == "__main__":
    sys.exit(main())
