r"""Убрать из demo то, что уже стало страницей, и почистить дубли.

Зачем
----
В `site/demo/` копятся макеты. Часть из них когда-то стала
реализованной страницей в `site/` и уже выложена на хостинг, но
исходник продолжает лежать в корне demo. Оттуда он и путается: при
выборе, что выкладывать, попадаются файлы, которые уже выложены.

Разбор (`tools/find_demo_duplicates.py`) нашёл 11 таких и 2 группы
дубликатов внутри demo.

Что делается и почему именно так
--------------------------------
Дубликаты **удаляются**: это ошибка выгрузки, два одинаковых файла
под разными именами, ничего уникального в них нет.

Стали страницей — **переносятся** в `demo/_готовое/`, а не
удаляются. И это осознанно: готовая страница переписана при переносе
(добавлены шрифты, расширения, `ai.json`), и исходник отличается от
того, что лежит на хостинге. Удалить его — значит потерять
«до». Корень demo при этом становится чистым, где лежат только
настоящие новые демки.

Ложные совпадения отсеиваются
-----------------------------
Папка считается страницей, только если в ней есть файл `.html`.
Без этого правила «SWF Forge · генератор и минимальный плеер» попал
бы в список: в папке `site/swf/` лежат три `.swf`, а никакой
страницы там нет, совпало только слово «swf». Проверено глазами:
это тот же файл, что и `deepseek_html_20261007_96025c.html`.

Запуск:
    .venv\\Scripts\\python.exe tools\\clean_demo_dupes.py
    .venv\\Scripts\\python.exe tools\\clean_demo_dupes.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "site" / "demo"
SITE = ROOT / "site"
ARCHIVE = DEMO / "_готовое"

SERVICE_DIRS = {"_assets", "abstration", "HTML‑3 - Kimi_files",
                "NovaStudio", "_готовое"}

#: Слова, слишком общие, чтобы судить по ним о совпадении.
GENERIC = {"swf", "html", "demo", "site", "page", "index", "main"}


def words_in(name: str) -> set[str]:
    parts = re.split(r"[^0-9A-Za-zА-Яа-я]+", name.lower())
    return {p for p in parts if len(p) >= 4 and p not in GENERIC}


def glued(name: str) -> str:
    parts = re.split(r"[^0-9A-Za-zА-Яа-я]+", name.lower())
    return "".join(p for p in parts if p)


def digest(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_real_page(folder: Path) -> bool:
    """Есть ли в папке страница, а не только вспомогательные файлы."""
    return any(f.suffix.lower() in (".html", ".htm")
               for f in folder.rglob("*") if f.is_file())


def find_duplicates() -> list[list[Path]]:
    """Группы одинаковых файлов внутри demo."""
    demos = [p for p in DEMO.iterdir()
             if p.is_file() and p.suffix.lower() in (".html", ".htm")]
    groups: dict[str, list[Path]] = {}
    for demo in demos:
        groups.setdefault(digest(demo), []).append(demo)
    return [g for g in groups.values() if len(g) > 1]


def pick_survivor(group: list[Path]) -> Path:
    """Кого оставить из группы одинаковых файлов.

    Порядок приоритетов, от важного к пустому:

    1. **Осмысленное имя против машинного.** Файл
       `SWF Forge · генератор и минимальный плеер.html` и файл
       `deepseek_html_20261007_96025c.html` оказались байт в байт
       одинаковыми. По длине имени побеждал второй — и он остался
       бы, то есть осталось бы бессмысленное имя. Машинное имя выдаёт
       себя меткой времени и служебным префиксом.
    2. **Нет скобки с номером.** `(1)` и `(2)` — верный признак копии
       от повторной выгрузки.
    3. **Короче.** Просто чтобы выбор был определён.
    """
    def score(path: Path) -> tuple[int, int, int, str]:
        stem = path.stem.lower()
        generated = bool(re.search(r"deepseek|chatgpt|gemini|artifact",
                                   stem) or re.search(r"\d{6,}", stem))
        has_copy_mark = bool(re.search(r"\(\d+\)", stem))
        return (int(generated), int(has_copy_mark), len(stem), path.name)

    return sorted(group, key=score)[0]


def remove(path: Path) -> None:
    """Удалить файл, сняв атрибут ReadOnly.

    Windows отказывается удалять файл с этим флагом, и он выставляется
    при загрузке из браузера. Та же беда была с папками `zagent-bench`
    и с картинками в `site/demo/_assets`.
    """
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    except OSError:
        pass
    path.unlink(missing_ok=True)


def find_became_pages() -> list[tuple[Path, str]]:
    """Демки, для которых в `site/` уже есть реализованная страница."""
    demos = [p for p in DEMO.iterdir()
             if p.is_file() and p.suffix.lower() in (".html", ".htm")]

    pages: dict[str, Path] = {}
    for folder in sorted(SITE.iterdir()):
        if not folder.is_dir() or folder.name == "demo":
            continue
        if not is_real_page(folder):
            continue
        pages[folder.name] = folder

    result: list[tuple[Path, str]] = []
    for demo in demos:
        words = words_in(demo.stem)
        if not words:
            continue
        demo_glued = glued(demo.stem)
        for name in pages:
            if words & words_in(name) or (
                    glued(name) and demo_glued.startswith(glued(name))):
                result.append((demo, name))
                break
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="чистка demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = args.dry_run

    if not DEMO.is_dir():
        print("папки demo нет")
        return 1

    # 1. Дубликаты внутри demo.
    groups = find_duplicates()
    print(f"=== 1. дубликаты внутри demo: {len(groups)} групп ===")
    deleted = 0
    for group in groups:
        keep = pick_survivor(group)
        print(f"  оставляю: {keep.name}")
        for item in group:
            if item == keep:
                continue
            print(f"  удаляю:   {item.name}  ({item.stat().st_size} Б)")
            if not dry:
                remove(item)
            deleted += 1

    # 2. Демки, ставшие страницами.
    became = find_became_pages()
    print()
    print(f"=== 2. стали страницами: {len(became)} ===")
    moved = 0
    for demo, page in became:
        print(f"  {demo.name}")
        print(f"      уже есть страница: site/{page}/")
        if dry:
            continue
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        target = ARCHIVE / f"{page}__{demo.name}"
        if target.exists():
            print(f"      в архиве уже есть такой — пропускаю")
            continue
        shutil.move(str(demo), str(target))
        moved += 1

    # 3. Записка в архиве.
    if not dry and moved:
        (ARCHIVE / "ЧТО-ЗДЕСЯ.md").write_text(
            "# Готовое\n\n"
            "Здесь лежат демки, которые уже стали страницами на сайте.\n\n"
            "Перенесены, а не удалены: готовая страница переписана при\n"
            "выкладке (добавлены шрифты, расширения, `ai.json`), и исходник\n"
            "от неё отличается. Имя файла начинается с названия страницы,\n"
            "чтобы было видно, откуда он.\n\n"
            "Если страницу придётся переделывать, исходник здесь.\n",
            encoding="utf-8")
        print()
        print(f"  записан _готовое/ЧТО-ЗДЕСЯ.md")

    print()
    print("=" * 62)
    print(f"удалено дубликатов: {deleted}")
    print(f"перенесено в архив: {moved}")
    if not dry:
        left = len([p for p in DEMO.iterdir()
                    if p.is_file() and p.suffix.lower() in (".html", ".htm")])
        print(f"демок в корне demo осталось: {left}")
    else:
        print("это был просмотр, ничего не менялось")
    return 0


if __name__ == "__main__":
    sys.exit(main())
