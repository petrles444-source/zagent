r"""Восстановить повреждённую регулярку в tools/make_palm.py.

Зачем
----
Правка через PowerShell-оболочку испортила в make_palm.py регулярное
выражение: `(?:src|href)` превратилось в `(??????:src|href)`, и скрипт
падал с `re.PatternError: unknown extension ??` — то есть переставал
работать вовсе, а не «что-то делал неверно».

Отдельным файлом, потому что оболочка и здесь может исказить не-ASCII:
строка правится целиком, а символы группы записываются через escape
`(?:` — так их нечем испортить.

Проверка не только «скрипт запустился», а что он находит то, что надо:
на куске разметки с тремя ссылками должны вернуться ровно три адреса,
а не кортежи и не пустой список.

Запуск:
    .venv\Scripts\python.exe tools\\fix_palm_regex.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "make_palm.py"

#: Нерабочая строка: `(?:` превратился в `??????:`.
BROKEN = re.compile(r"refs = re\.findall\(")

#: Как должно быть. Группа одна — тот адрес, который и проверяем.
#: `(?:src|href)` — группа без захвата, поэтому в выдаче её нет.
GOOD = (
    "    refs = re.findall("
    "r'(?:" + "src|href" + ')="([A-Za-z0-9_./-]+\\.(?:jpg|png|css|js|webp))"\','
)


def main() -> int:
    if not TARGET.is_file():
        print(f"нет файла {TARGET}")
        return 1

    lines = TARGET.read_text(encoding="utf-8").split("\n")
    changed = 0
    for i, line in enumerate(lines):
        if not BROKEN.search(line):
            continue
        # Сравнение с эталоном, а не поиск «сломанных» признаков.
        #
        # Раньше здесь стояло условие «и `(?:` нет в строке». Лишняя
        # группа `((?:src|href))` это условие проходила: `(?:` в ней
        # есть, строка выглядела неповреждённой, а скрипт на ней
        # падал позже — уже при проверке ссылок, где получал кортежи
        # вместо строк. Признак поломки надо искать сравнением с
        # правилом, а не догадкой о виде.
        if line == GOOD:
            continue
        lines[i] = GOOD
        changed += 1

    if not changed:
        print("исправлять нечего")
        return 0

    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(f"исправлено строк: {changed}")

    # Проверка на куске разметки: правило должно вернуть адреса, а не
    # кортежи. Раньше здесь была лишняя группа, и проверка молча
    # разваливалась бы дальше по коду.
    pattern = re.compile(
        r'(?:src|href)="([A-Za-z0-9_./-]+\.(?:jpg|png|css|js|webp))"')
    sample = ('<img src="chart.jpg"><link href="style.css">'
              '<a href="/palm/">домой</a><img src="a.webp">')
    found = pattern.findall(sample)
    expected = ["chart.jpg", "style.css", "a.webp"]

    if found != expected:
        print(f"проверка не прошла: {found} вместо {expected}")
        return 1

    print(f"правило находит: {found}")
    print("всё на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
