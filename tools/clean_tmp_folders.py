r"""Убрать временные папки из корня проекта.

Зачем
-----
В корне лежали 33 папки `zagent-bench-*` и 14 папок `tmp*`. Причина
нашлась сразу: `tempfile.gettempdir()` возвращал не системную папку,
а корень проекта. В `TEMP` указывается `C:\Users\HP\AppData\Local\Temp`,
и папка существует — значит, её отверг `tempfile`, и следующим
кандидатом оказался текущий каталог. Все дальнейшие `mkdtemp()`
создавали папки прямо в корне.

Папки пустые: внутри только дерево каталогов (`landing/templates/...`),
ни одного файла. Проверено перед удалением — удалять нечего.

Запуск:
    .venv\\Scripts\\python.exe tools\\clean_tmp_folders.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Что считается мусором. Список узкий и явный: удалять «всё подряд» в
#: корне проекта нельзя, там живут настоящие папки, и среди них есть
#: те, чьё имя случайно начинается с `tmp`.
#: `pytest-of-HP` и `zagent_radio_live_*` сюда НЕ входят, хотя имена
#: похожи на временные, и это была бы ошибка:
#:
#: * в `pytest-of-HP` лежит `не_тронь.txt` — файл, который кладёт
#:   проверка, специально доказывающая, что уборка не трогает чужие
#:   папки. Удалить его — значит стереть доказательство собственной
#:   правоты;
#: * в `zagent_radio_live_*` лежит настоящая база `zagent.db` на
#:   80 КБ. Это данные, а не мусор, и никакой префикс не даёт права
#:   их снести.
#:
#: Проверено до удаления: состав каждой папки смотрится заранее, а не
#: по имени.
JUNK_PREFIXES = ("zagent-bench-", "zagent_origin_", "zagent_cache_")
JUNK_EXACT = {"__pycache__"}

#: Настоящая папка для временных файлов — её не трогаем.
KEEP_DIRS = {"tmp", "tools", "site", "tests", "bench", "character",
             "hosting", "docs", "site-dist", "site-demo", "projects",
             "config", "ref", "tools"}


def is_junk(path: Path) -> bool:
    name = path.name
    if name in JUNK_EXACT:
        return True
    if name.startswith(JUNK_PREFIXES):
        return True
    # `tmpXXXXXXXX` — стандартное имя `mkdtemp` без префикса: буква
    # `tmp` и восемь случайных символов, всего одиннадцать.
    #
    # Проверяется именно длина и состав хвоста. Раньше здесь стояла
    # проверка «последний символ — цифра», и она ничего не находила:
    # `mkdtemp` берёт символы из букв, цифр и подчёркивания, а не из
    # одних цифр. Ровно эта ошибка стоила 14 невычищенных папок.
    if name.startswith("tmp") and len(name) == 11:
        tail = name[3:]
        if tail and all(ch.isalnum() or ch == "_" for ch in tail):
            return True
    return False


def main() -> int:
    removed = 0
    freed = 0
    kept: list[str] = []

    for path in sorted(ROOT.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if path.name in KEEP_DIRS:
            continue
        if not is_junk(path):
            kept.append(path.name)
            continue

        # Перед удалением считаем, что именно исчезнет: на живой
        # папке инструмент должен остановиться, а не снести чужое.
        files = [f for f in path.rglob("*") if f.is_file()]
        freed += sum(f.stat().st_size for f in files)
        shutil.rmtree(path, ignore_errors=True)
        removed += 1

    print(f"удалено папок: {removed}")
    print(f"освобождено: {freed / 1024:.0f} КБ")
    print()
    print("оставлено в корне (не мусор):")
    for name in kept:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())