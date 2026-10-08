r"""Найти демки из `demo`, которые уже реализованы на сайте.

Зачем
----
В `site/demo/` копятся готовые макеты, а в `site/` — уже
реализованные и выложенные страницы. Часть демок когда-то стала
страницей, и теперь лежит в двух местах: как исходник в корне
`demo/` и как готовая страница в папке своего имени.

Человек спросил, какие дубли можно удалить. Отвечать на глаз нельзя:
файлы называются по-разному (`aetheris_next_gen_crypto_protocol.html`
против `aetheris/index.html`), и по имени они не находятся.

Поэтому сравнение идёт по содержимому, и это единственный способ
сказать правду:

1. у страницы в `site/` вычисляется отпечаток всех её файлов;
2. у каждой демки — свой;
3. демка считается реализованной, если совпали название страницы в
   адресе и отпечаток ключевых файлов.

Отдельно ловятся дубли внутри самой `demo`: один и тот же файл под
двумя именами — такие удаляются без вопросов, потому что это ошибка
выгрузки, а не два разных макета.

Запуск:
    .venv\\Scripts\\python.exe tools\\find_demo_duplicates.py
    .venv\\Scripts\\python.exe tools\\find_demo_duplicates.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "site" / "demo"
SITE = ROOT / "site"

#: Служебные папки внутри demo: их содержимое — не демки.
SERVICE_DIRS = {"_assets", "abstration", "HTML‑3 - Kimi_files",
                "NovaStudio"}

#: Ключевые слова, по которым имя демки сопоставляется со страницей.
#:
#: Имя файла часто не совпадает с папкой страницы: `iskra_...html`
#: попадает в папку `iskra`, а `NovaTechStore.html` — в `novastore`.
#: Поэтому сравнение идёт по кускам имени, а не по точному совпадению.
def glued(name: str) -> str:
    """Имя без разделителей, куски в исходном порядке.

    Порядок обязателен. По алфавиту `aura` + `spin` даёт
    `auraspin` только случайно, а вот `sort` ломает всё, что длиннее
    двух слов: `sora` + `moku` превращалось в `mo rasora`.
    """
    parts = re.split(r"[^0-9A-Za-zА-Яа-я]+", name.lower())
    return "".join(p for p in parts if p)


def words_in(name: str) -> set[str]:
    """Значимые куски имени.

    Разделитель — не `\\w`, а «не буква и не цифра». В `\\w` Python
    включает подчёркивание, поэтому `aetheris_next_gen_crypto_protocol`
    оставалось одним куском и не совпадало ни с чем: страница называлась
    `aetheris`. На первый взгляд сравнение работало правильно и молча
    показывало ноль совпадений.
    """
    parts = re.split(r"[^0-9A-Za-zА-Яа-я]+", name.lower())
    return {p for p in parts if len(p) >= 4}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_real_page(folder: Path) -> bool:
    """Есть ли в папке страница, а не только вспомогательные файлы.

    Правило обязательное, иначе «SWF Forge · генератор и минимальный
    плеер» попадает в список как уже сделанная страница: папка
    `site/swf/` называется похоже, но в ней три файла `.swf` и никакой
    страницы. Совпадение было только по слову «swf».
    """
    return any(f.suffix.lower() in (".html", ".htm")
               for f in folder.rglob("*") if f.is_file())


def site_pages() -> dict[str, dict]:
    """Отпечатки реализованных страниц: имя папки -> отпечаток."""
    pages: dict[str, dict] = {}
    for folder in sorted(SITE.iterdir()):
        if not folder.is_dir() or folder.name == "demo":
            continue
        if not is_real_page(folder):
            continue
        files = [f for f in folder.rglob("*") if f.is_file()]
        if not files:
            continue
        pages[folder.name] = {
            "files": len(files),
            "size": sum(f.stat().st_size for f in files),
            "hashes": {digest(f) for f in files},
        }
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description="дубли демок")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not DEMO.is_dir():
        print("папки demo нет")
        return 1

    demos = [p for p in DEMO.iterdir()
             if p.is_file() and p.suffix.lower() in (".html", ".htm")]
    pages = site_pages()

    # 1. Демка целиком совпадает с файлом на сайте — точный дубль.
    by_hash: dict[str, list[Path]] = {}
    site_hashes: dict[str, str] = {}
    for name, info in pages.items():
        for file in sorted((SITE / name).rglob("*")):
            if file.is_file():
                site_hashes[digest(file)] = f"{name}/" + \
                    file.relative_to(SITE / name).as_posix()

    for demo in demos:
        by_hash.setdefault(digest(demo), []).append(demo)

    exact: list[tuple[Path, str]] = []
    for demo in demos:
        hit = site_hashes.get(digest(demo))
        if hit:
            exact.append((demo, hit))

    # 2. Демка сделана страницей: имя совпадает, но файл переписан при
    #    переносе. Такие — кандидаты на удаление, но помечаются
    #    отдельно: их исходник может отличаться от готовой страницы.
    #
    #    Имя сравнивается в двух видах, и второй обязателен. Страницы
    #    называются склеенными: `auraspin` вместо `aura_spin`,
    #    `naturespace` вместо `nature_space`, `soramoku` вместо
    #    `sora_moku`. По кускам такое не находилось, и пять готовых
    #    демок числились новыми.
    same_name: list[tuple[Path, str]] = []
    for demo in demos:
        if site_hashes.get(digest(demo)):
            continue
        words = words_in(demo.stem)
        if not words:
            continue
        demo_glued = glued(demo.stem)
        for name, info in pages.items():
            page_words = words_in(name)
            page_glued = glued(name)
            #: Три признака совпадения, и все три нужны:
            #:
            #: * общий кусок слова — `aetheris` против `aetheris_...`;
            #: * папка целиком совпала — `horology` в имени демки;
            #: * папка стоит в начале склейки — `auraspin` против
            #:   `aura_spin_analog_sound_experience`. Без третьего
            #:   пять готовых страниц числились новыми демками.
            same_part = bool(words & page_words)
            glued_same = bool(page_glued) and (
                demo_glued.startswith(page_glued)
                or page_glued.startswith(demo_glued))
            if same_part or glued_same:
                same_name.append((demo, name))
                break

    # 3. Дубли внутри demo: один файл под двумя именами.
    internal: dict[str, list[Path]] = {}
    for demo in demos:
        internal.setdefault(digest(demo), []).append(demo)
    inside = [group for group in internal.values() if len(group) > 1]

    if args.json:
        print(json.dumps({
            "exact": [{"demo": str(d.relative_to(ROOT)), "site": s}
                      for d, s in exact],
            "same_name": [{"demo": str(d.relative_to(ROOT)), "page": s}
                          for d, s in same_name],
            "internal": [[str(x.relative_to(ROOT)) for x in g]
                         for g in inside],
            "pages": len(pages), "demos": len(demos),
        }, ensure_ascii=False, indent=1))
        return 0

    print(f"демок в demo: {len(demos)}, страниц на сайте: {len(pages)}")

    print()
    print(f"=== 1. ТОЧНЫЕ ДУБЛИ: файл демки есть на сайте ({len(exact)}) ===")
    for demo, where in exact:
        print(f"  {demo.name}")
        print(f"      уже лежит как: {where}")
        print(f"      БЕЗОПАСНО УДАЛИТЬ")

    print()
    print(f"=== 2. СДЕЛАНО СТРАНИЦЕЙ: имя совпало, файл переписан "
          f"({len(same_name)}) ===")
    for demo, page in same_name:
        info = pages[page]
        print(f"  {demo.name}")
        print(f"      страница: {page}/  ({info['files']} файлов, "
              f"{info['size'] / 1024:.0f} КБ)")
        print(f"      демка {demo.stat().st_size / 1024:.0f} КБ — "
              f"это исходник, он может отличаться")

    print()
    print(f"=== 3. ДУБЛИ ВНУТРИ DEMO ({len(inside)}) ===")
    for group in inside:
        print(f"  одинаковое содержимое:")
        for item in group:
            print(f"      {item.name}  ({item.stat().st_size} Б)")

    print()
    print("=" * 66)
    print("Безопасного удаления: " + str(len(exact)))
    print("Осознанных решений нужно: " + str(len(same_name)))
    print("Ошибок выгрузки: " + str(len(inside)))
    return 0


if __name__ == "__main__":
    sys.exit(main())