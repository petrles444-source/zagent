r"""Дать расширения файлам, которые скачались без него.

Зачем
----
Хостинг отдаёт 553 «Prohibited file name» на файлы без расширения:
такое имя он считает служебным и не отдаёт. Имена пришли прямо из
ссылок Unsplash — там путь заканчивается на идентификаторе фотографии
без точки: `photo-1517849845537-969583325d29`.

Ошибка выглядела как «файлы залились с ошибкой», а на деле страница
собралась и ссылается на файлы, которые сервер физически не хранит:
картинок нет, вёрстка рассыпается.

Почему не качать заново
----------------------
Файлы уже на диске, и они верные. Переименование и правка ссылок
занимают секунды, повторная загрузка пятнадцати мегабайт — минуты.
Тип определяется по содержимому, а не по догадке: расширение должно
соответствовать файлу, иначе браузер не поймёт, как его показывать.

Что делается
------------
1. У каждого файла без расширения определяется тип по содержимому.
2. Файл переименовывается, добавление типа — точка, иначе диск
   воспримет это как часть имени.
3. Ссылки в `index.html` переписываются на новое имя.

Запуск:
    .venv\\Scripts\\python.exe tools\\fix_extensions.py
    .venv\\Scripts\\python.exe tools\\fix_extensions.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

#: Расширение по содержимому. Порядок важен: сначала то, что
#: опознаётся однозначно, потом текст, потому что текст определяется
#: по признакам, которые есть и у картинок.
DETECT = (
    ("png", b"\x89PNG\r\n\x1a\n"),
    ("jpg", b"\xff\xd8\xff"),
    ("gif", b"GIF8"),
    ("webp", b"RIFF"),
)


def detect(path: Path) -> str:
    """Расширение по первым байтам файла."""
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return ""

    for ext, magic in DETECT:
        if head.startswith(magic):
            # RIFF бывает и у WAV: у картинки webp на четвёртом месте
            # лежит строка "WEBP".
            if ext == "webp" and b"WEBP" not in path.read_bytes()[:16]:
                continue
            return ext

    # Не картинка. Тогда по содержимому это таблица стилей или
    # скрипт: оба текстовые, и различать их не нужно — расширение
    # нужно лишь затем, чтобы имя прошло проверку хостинга.
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        return "bin"
    return "css" if "@" in text[:200] else "js"


def main() -> int:
    parser = argparse.ArgumentParser(description="расширения файлов")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    fixed = 0
    checked = 0

    for folder in sorted(SITE.iterdir()):
        if not folder.is_dir():
            continue
        index = folder / "index.html"
        if not index.is_file():
            continue

        renames: dict[str, str] = {}
        for item in sorted(folder.iterdir()):
            if not item.is_file() or item.suffix:
                continue
            checked += 1
            ext = detect(item)
            if not ext:
                print(f"  {folder.name}/{item.name}: не определил тип")
                continue
            new_name = f"{item.name}.{ext}"
            renames[item.name] = new_name
            if not args.check:
                item.replace(folder / new_name)
            fixed += 1

        if renames and not args.check:
            text = index.read_text(encoding="utf-8")
            for old, new in renames.items():
                text = text.replace(f'"{old}"', f'"{new}"')
                text = text.replace(f"'{old}'", f"'{new}'")
            index.write_text(text, encoding="utf-8")

    print(f"файлов без расширения: {checked}")
    print(f"исправлено: {fixed}")
    if args.check:
        print("это был просмотр: ничего не менялось")

    # Проверка: после правки безымянных файлов быть не должно.
    left = []
    for folder in sorted(SITE.iterdir()):
        if not folder.is_dir() or not (folder / "index.html").is_file():
            continue
        for item in folder.iterdir():
            if item.is_file() and not item.suffix:
                left.append(f"{folder.name}/{item.name}")
    if left and not args.check:
        print()
        print(f"ОСТАЛИСЬ БЕЗ РАСШИРЕНИЯ: {len(left)}")
        for name in left[:10]:
            print(f"  {name}")
        return 1

    print("проверка: файлов без расширения не осталось")
    return 0


if __name__ == "__main__":
    sys.exit(main())
