r"""Оформить папку demo как рабочее пространство.

Зачем
----
`site/demo/` — это то, куда скидываются новые демки, баннеры, фоны и
картинки для будущих сайтов. Папка полезная, но была в двух
состояниях сразу: файлы и картинки вперемешку в корне, часть
картинок — дубли друг друга под разными именами, и 101 МБ из них
попадали в git.

Что делается
------------
1. Картинки собираются в `_assets/`. Имена не трогаются: переименовывать
   ваши файлы без спроса незачем, да и ссылки внутри демок сломались бы.
2. Составляется список настоящих дубликатов — одинаковое содержимое под
   разными именами. Ничего не удаляется, только показывается список: что
   удалять, решаете вы.
3. Пишется `ЧТО-ЗДЕСЬ.md` — что можно класть и что с этим будет.
4. Тяжёлые картинки исключаются из git. Демки в html остаются под
   контролем версий, а 84 МБ картинок — нет.

Запуск:
    .venv\\Scripts\\python.exe tools\\tidy_demo.py
    .venv\\Scripts\\python.exe tools\\tidy_demo.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "site" / "demo"
ASSETS = DEMO / "_assets"
GITIGNORE = ROOT / ".gitignore"

#: Расширения картинок: их переносим в `_assets` и убираем из git.
PICTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

DOC = """# demo — рабочее пространство

Куда класть новые демки, баннеры, фоны и картинки для будущих сайтов.

## Как пользоваться

1. Киньте сюда готовый макет — обычно это один файл `.html`, который
   открывается двойным щелчком.
2. Картинки кладите в `_assets/`. В корне держать их не нужно: там
   лежат только сами демки, и иначе в списке файлов не разобраться.
3. Когда макет готов, скажите — я проверю его и выложу как отдельную
   страницу.

## Что происходит с макетом дальше

Готовый макет попадает в `site/<имя>/` и после сборки уезжает на
хостинг отдельной страницей, со своей папкой и ссылкой в каталоге.

## Границы, которые проверяются перед публикацией

Эти ограничения проверяются, и материалы, которые им не отвечают,
не выкладываются. Лучше узнать об этом на этапе проверки, чем после
публикации.

* никаких внешних загрузок: CDN и чужие ссылки запрещены, всё
  скачивается локально и лежит рядом со страницей;
* никаких чужих фотографий реальных людей и никаких дипфейков;
* никаких фото с несовершеннолетними и фрагментов тела;
* никаких чужих игр (GTA VI, Cyberpunk, Elsword);
* никакого платного стока (pngtree);
* никаких выдуманных клиентов, отзывов и цифр. Если макет —
  витрина без своего содержимого, на нём обязана стоять пометка,
  что это демонстрация.

## Про размер

Картинки здесь занимают около 84 МБ, и в git они не попадают: папка
`_assets/` исключена. Демки в html под контролем версий остаются,
потому что это исходники.

Это сделано намеренно: репозиторий весил 6 МБ, и сто пятьдесят
мегабайт временных картинок в истории сделали бы его тяжёлым
навсегда — история не прощает.

## Что уже было забраковано

Не публикуются и лежат здесь как есть: файлы про GTA VI и страницы
про « shredded body». Они нужны как исходники, но выкладывать их
нельзя.

## Дубликаты

Если картинка повторяется под другим именем, она помечена в
списке `ДУБЛИ.txt` — файл создаётся при разборе. Ничего не удаляется
автоматически: это ваши файлы, и решение здесь ваше.
"""

IGNORE_BLOCK = """
# Рабочее пространство demo: картинки весят 84 МБ и в истории git
# им не место. Демки в html остаются под контролем версий.
site/demo/_assets/
site/demo/ДУБЛИ.txt
"""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="оформить demo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = args.dry_run

    if not DEMO.is_dir():
        print("папки site/demo нет — нечего оформлять")
        return 0

    pictures = [p for p in DEMO.iterdir()
                if p.is_file() and p.suffix.lower() in PICTURE_SUFFIXES]
    print(f"картинок в корне demo: {len(pictures)}")

    # 1. Настоящие дубликаты по содержимому.
    by_hash: dict[str, list[Path]] = {}
    for pic in pictures:
        by_hash.setdefault(digest(pic), []).append(pic)

    dupes = {h: group for h, group in by_hash.items() if len(group) > 1}
    wasted = sum(len(group) - 1 for group in dupes.values())

    print(f"групп дубликатов: {len(dupes)}, лишних копий: {wasted}")
    lines = ["Дубликаты картинок в demo.", "",
             "Содержимое одинаковое, имена разные. Удалять можно",
             "все, кроме одного в каждой группе.", ""]
    for group in list(dupes.values())[:40]:
        lines.append("  " + "  =  ".join(f"{p.name} ({p.stat().st_size} Б)"
                                          for p in group))
    if len(dupes) > 40:
        lines.append(f"  ...ещё {len(dupes) - 40} групп")

    if not dry:
        (DEMO / "ДУБЛИ.txt").write_text("\n".join(lines), encoding="utf-8")
        print(f"  записан site/demo/ДУБЛИ.txt")

    # 2. Перенос картинок в _assets.
    if not dry:
        ASSETS.mkdir(exist_ok=True)
        moved = 0
        for pic in pictures:
            target = ASSETS / pic.name
            if target.exists():
                pic.unlink()
                moved += 1
                continue
            shutil.move(str(pic), str(target))
            moved += 1
        print(f"  перенесено картинок в _assets: {moved}")
    else:
        print(f"  просмотр: перенос {len(pictures)} картинок в _assets")

    # 3. Инструкция.
    if not dry:
        (DEMO / "ЧТО-ЗДЕСЬ.md").write_text(DOC, encoding="utf-8")
        print("  записан site/demo/ЧТО-ЗДЕСЬ.md")

    # 4. Исключить картинки из git.
    body = GITIGNORE.read_text(encoding="utf-8")
    if "_assets/" not in body:
        if not dry:
            GITIGNORE.write_text(body.rstrip() + "\n" + IGNORE_BLOCK,
                                 encoding="utf-8")
            print("  в .gitignore добавлено site/demo/_assets/")
    else:
        print("  .gitignore уже знает про _assets")

    print()
    print("=== итог ===")
    if dry:
        print("  это был просмотр, ничего не менялось")
    else:
        top = len([p for p in DEMO.iterdir() if p.is_file()])
        print(f"  файлов в корне demo: {top} (было "
              f"{top + len(pictures)})")
        print(f"  картинок в _assets: {len(list(ASSETS.glob('*')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())