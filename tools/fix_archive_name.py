r"""Починить имя папки архива в `clean_demo_dupes.py`.

Зачем
----
Константа `ARCHIVE` содержала повреждённое имя: вместо `_готовое`
там оказалось `_готово<замена><замена>е`. Папка создалась с таким же
именем, и десять перенесённых исходников оказались в папке, имя
которой не набирается с клавиатуры.

Как вышло
---------
Правка вносилась подстановкой из heredoc в PowerShell, и PowerShell
исказил кириллицу в самом файле. То есть исправление чужой правки
сломало само исправление — и сделало это молча.

Здесь имя собирается по кускам, поэтому испортить его уже нечем:
кириллица не проходит через строку в командной оболочке целиком.

Запуск:
    .venv\\Scripts\\python.exe tools\\fix_archive_name.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "clean_demo_dupes.py"

#: Имя собирается из кусков: так его невозможно испортить оболочкой.
GOOD = "_" + "гот" + "ов" + "ое"

#: Совпадает с любым именем, начинающимся с подчёркивания и слова
#: «готово» — то есть и битое, и правильное.
MARK = "_" + "гот"


def main() -> int:
    if not SCRIPT.is_file():
        print("файл не найден", file=sys.stderr)
        return 1

    body = SCRIPT.read_text(encoding="utf-8")
    if f'ARCHIVE = DEMO / "{GOOD}"' in body:
        print("  имя уже правильное")
    else:
        lines = body.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("ARCHIVE = DEMO /"):
                lines[index] = f'ARCHIVE = DEMO / "{GOOD}"'
                print(f"  строка {index + 1} исправлена")
                break
        else:
            print("  строка ARCHIVE не найдена", file=sys.stderr)
            return 1
        SCRIPT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Проверка: имя в коде совпадает с папкой на диске.
    archive = ROOT / "site" / "demo" / GOOD
    print(f"  в коде:      {GOOD!r}")
    print(f"  папка есть:  {archive.is_dir()}")
    if archive.is_dir():
        files = len([f for f in archive.iterdir() if f.is_file()])
        print(f"  файлов:      {files}")

    # Битого имени быть не должно.
    broken = [p for p in (ROOT / "site" / "demo").iterdir()
              if p.is_dir() and p.name.startswith(MARK) and p.name != GOOD]
    if broken:
        print(f"  ОСТАЛОСЬ битых папок: {[p.name for p in broken]}")
        return 1
    print("  битых папок нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())