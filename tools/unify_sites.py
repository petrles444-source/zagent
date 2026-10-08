r"""Свести sites и site к одному проекту без копий.

Зачем
----
В проекте две папки про сайты, и они означали разное:

* `site/` — настоящие исходники: 41 папка, 1099 файлов, 330 МБ;
* `sites/` — папка, созданная при разборке корня, куда положили
  **копию** `portfolios/`.

То есть `sites/` не содержал ничего своего, а дублировал то, что
и так лежит рядом. Человек справедливо спросил: за две папки.

Почему `site/` не переносится внутрь `sites/`
--------------------------------------------
Путь `site/` зашит в код минимум десяти инструментов:
`build_site.py`, `upload_site.py`, `make_catalog.py`, `add_ai.py`,
`add_guides.py`, `bot_proxy.py` и другие. Перенос сломает их все разом,
а проверить каждый можно только прогоном.

Поэтому `sites/` становится **точкой входа проекта**: инструкция,
копии инструментов и ничего больше. Копий данных в ней не остаётся
вовсе — это и было целью.

Что удаляется и почему
----------------------
Копия `portfolios/` внутри `sites/`: те же 76 файлов лежат в
`portfolios/`, откуда их и грузит загрузчик портфолио. Держать
вторую копию — значит через полгода править не ту.

Запуск:
    .venv\\Scripts\\python.exe tools\\unify_sites.py
    .venv\\Scripts\\python.exe tools\\unify_sites.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "sites"
TOOLS = ROOT / "tools"

#: Копии, которые точно не нужны: они дублируют то, что лежит рядом.
DROP = ("sites/portfolios",)

#: Инструменты проекта сайтов. Копируются в `sites/инструменты/`,
#: чтобы проект запускался сам, из своей папки.
TOOL_FILES = (
    "build_site.py",
    "upload_site.py",
    "check_host.py",
    "make_catalog.py",
    "make_shots.py",
    "fix_extensions.py",
    "publish_demo.py",
    "scan_demo.py",
)

DOC = """# Сайты и портфолио — один проект

* Адрес: `https://zagent.do.am/`
* Каталог: `https://zagent.do.am/catalog.html`

## Где что лежит на самом деле

| Что | Где |
|---|---|
| Исходники сайтов, 41 папка | `../site/` |
| Исходники портфолио | `../portfolios/` |
| Собранная версия, едет на хостинг | `../site-dist/` |
| Готовые архивы | `../publish/` |
| Новые демки | `../site/demo/` |
| Инструменты, копии | `инструменты/` |

**Копий данных здесь нет и не будет.** Папка `sites` — это вход в
проект: инструкция и инструменты. Исходники лежат в `site/` и
`portfolios/`, потому что путь `site/` зашит в коде десяти
инструментов. Перенос сломал бы их все разом, а проверить каждый
можно только прогоном.

## Три команды

Сборка — из исходников в `site-dist`:

```powershell
..\\.venv\\Scripts\\python.exe ..\\tools\\build_site.py
```

Заливка на хостинг:

```powershell
$env:ZAGENT_FTP_HOST='s726.ucoz.net'
$env:ZAGENT_FTP_USER='...'
$env:ZAGENT_FTP_PASS='...'
..\\.venv\\Scripts\\python.exe ..\\tools\\upload_site.py
```

Проверка, что всё живо:

```powershell
..\\.venv\\Scripts\\python.exe ..\\tools\\check_host.py
```

Проверка настоящая, а не «просто код 200»: она ищет в теле страницы
заглушку хостинга и отсеивает слишком короткие ответы.

## Новые демки

Класть в `../site/demo/`. Подробности — в
`../site/demo/ЧТО-ЗДЕСЯ.md`.

Там же лежит `_готовое/` — демки, которые уже стали страницами.
Они перенесены, а не удалены: готовая страница переписана при
выкладке, и исходник отличается от того, что лежит на хостинге.

## Проверка на дубли

```powershell
..\\.venv\\Scripts\\python.exe ..\\tools\\find_demo_duplicates.py
```

Показывает, какие демки уже реализованы как страницы, и какие
файлы повторяются внутри demo.

## Радио

Скрипт для вставки радио на любую страницу:
`../radio/вставка/radio-widget.html`. Подключение — одна строка
`iframe`, инструкция в `../radio/ЧТО-ЗДЕСЯ.md`.

## Границы публикации

Проверяются перед выкладкой, материалы не отвечающие — не
выкладываются:

* никаких внешних загрузок: CDN и чужие ссылки запрещены;
* никаких чужих фотографий реальных людей и никаких дипфейков;
* никаких фото с несовершеннолетними и фрагментов тела;
* никаких чужих игр (GTA VI, Cyberpunk, Elsword);
* никакого платного стока (pngtree);
* никаких выдуманных клиентов, отзывов и цифр — на витрине без
  своего содержимого обязана стоять пометка, что это демонстрация.

## Известные особенности хостинга

* файл без расширения отдаётся с кодом 553 — расширения проставляет
  `fix_extensions.py`;
* кэш браузера держится 20 дней, поэтому сборка ставит метки `?v=`.
"""


def wipe(path: Path) -> None:
    for item in [path, *path.rglob("*")]:
        try:
            os.chmod(item, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="свести sites в один проект")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = args.dry_run

    print("=== 1. убираю копии ===")
    for rel in DROP:
        path = ROOT / rel
        if not path.exists():
            print(f"  {rel} нет — пропускаю")
            continue
        files = len([f for f in path.rglob("*") if f.is_file()])
        print(f"  {rel}: {files} файлов — копия, удаляю")
        if not dry:
            wipe(path)

    print()
    print("=== 2. инструменты проекта ===")
    target = SITES / "инструменты"
    if not dry:
        target.mkdir(parents=True, exist_ok=True)
    for name in TOOL_FILES:
        src = TOOLS / name
        if not src.is_file():
            print(f"  нет {name}")
            continue
        print(f"  {name}")
        if not dry:
            shutil.copy2(src, target / name)

    print()
    print("=== 3. инструкция ===")
    if dry:
        print("  просмотр: sites/ЧТО-ЗДЕСЬ.md")
    else:
        (SITES / "ЧТО-ЗДЕСЯ.md").write_text(DOC, encoding="utf-8")
        print("  записан sites/ЧТО-ЗДЕСЯ.md")

    print()
    print("=== 4. состояние ===")
    site_files = len([f for f in (ROOT / "site").rglob("*") if f.is_file()])
    port_files = len([f for f in (ROOT / "portfolios").rglob("*")
                      if f.is_file()])
    sites_files = len([f for f in SITES.rglob("*") if f.is_file()])
    print(f"  site/:        {site_files} файлов  (исходники, остаются)")
    print(f"  portfolios/:  {port_files} файлов  (исходники, остаются)")
    print(f"  sites/:       {sites_files} файлов  (вход в проект, без копий)")
    if dry:
        print()
        print("  это был просмотр")
    return 0


if __name__ == "__main__":
    sys.exit(main())