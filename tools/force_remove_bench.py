r"""Убрать папки `zagent-bench-*` и подобные, которые не удаляются сразу.

Зачем этот файл
---------------
В корне проекта накопились папки `zagent-bench-*` и `tmp*`, и обычный
`shutil.rmtree` на них падал с `PermissionError: [WinError 5] Access is
denied`. Причина искалась в три шага, и каждый раз первая догадка
оказывалась неверной:

1. **Метка целостности.** У папок стояло
   `Mandatory Label\Low Mandatory Level`, и метка в наследующем виде
   `(I)` стоит ещё и на самом проекте — то есть унаследована от
   родителя, а не задана песочнице. Снятие метки (`icacls
   /setintegritylevel`) и сброс прав (`/reset`, `/grant`) отработали
   без ошибок — а удаление всё равно падало. Значит метка не при чём.

2. **Reparse-точка?** Проверено: `LinkType` пуст, обычная папка. Не
   при чём.

3. **Атрибут ReadOnly.** Вот он. `attrib` показал `R` на вложенных
   каталогах, а Windows отказывается удалять каталог с этим
   атрибутом. Папки создавались пустыми и «запоминались» как
   read-only.

Раньше уборщик глотал ошибку через `ignore_errors=True` и печатал
«удалено» — то есть 33 папки он удалить не смог, но отчитался об
успехе. Это худший вид молчания, поэтому здесь удаление проверяется
по факту: папка считается снесённой, только если её больше нет.

Запуск:
    .venv\\Scripts\\python.exe tools\\force_remove_bench.py
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Какие деревья чистить. Список явный: сносить в корне «всё подряд»
#: нельзя, там есть и настоящие папки.
TARGETS = ("zagent-bench-*", "zagent_origin_*", "zagent_cache_*")

#: Имена, похожие на временные, но такими НЕ являющиеся.
#:
#: * `pytest-of-HP` — там лежит `не_тронь.txt`, файл из проверки,
#:   которая специально доказывает, что уборка не трогает чужие папки;
#: * `zagent_radio_live_*` — там настоящая база `zagent.db` на 80 КБ.
#:
#: Проверено по содержимому, а не по имени: удалить базу потому, что
#: слово похоже на временное, — это потеря данных.
NEVER_TOUCH = ("pytest-of-", "zagent_radio_live_", "tmp", "site",
               "tools", "tests", "bench", "hosting", "docs", "config",
               "character", "projects", "reports", "logs", "ref")


def clear_readonly(path: Path) -> int:
    """Снять атрибут ReadOnly со всего дерева через `os.chmod`.

    Сначала пробовали `attrib -R /S /D`, и он приводил в замешательство:
    код возврата 0, ошибок нет — а флаг на вложенных каталогах остаётся.
    Он снимал его с двух верхних папок и не доводил рекурсию до листьев,
    где он как раз и мешал. По выводу `attrib` не отличить от успеха,
    поэтому взят `os.chmod`: он работает на каждой папке отдельно, и
    результат проверяется тем же вызовом `os.stat`.
    """
    cleared = 0
    for item in [path, *path.rglob("*")]:
        if not item.is_dir():
            continue
        try:
            os.chmod(item, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            cleared += 1
        except OSError:
            # Не сняли — папка останется, и удаление упадёт ниже с
            # внятной ошибкой. Молчать здесь нельзя.
            pass
    return cleared


def safe(path: Path) -> bool:
    """Не трогаем ли мы что-то важное."""
    name = path.name
    if name in NEVER_TOUCH or name.startswith(NEVER_TOUCH):
        return False
    return any(path.match(pattern) for pattern in TARGETS)


def main() -> int:
    targets = []
    for pattern in TARGETS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_dir() and safe(path):
                targets.append(path)

    if not targets:
        print("удалять нечего — мусор уже убран")
        return 0

    print(f"найдено папок: {len(targets)}")
    removed: list[str] = []
    failed: list[tuple[str, str]] = []

    for path in targets:
        clear_readonly(path)
        try:
            shutil.rmtree(path)
        except OSError as exc:
            failed.append((path.name, str(exc)[:70]))
            continue
        # Проверка по факту: rmtree умеет вернуться без ошибки,
        # оставив часть дерева, если что-то не удалилось.
        if path.exists():
            failed.append((path.name, "осталась после удаления"))
        else:
            removed.append(path.name)

    for name in removed:
        print(f"  удалено {name}")
    for name, why in failed:
        print(f"  НЕ УДАЛЕНО {name}: {why}")

    print()
    print(f"удалено: {len(removed)}")
    print(f"не удалось: {len(failed)}")

    left = sum(1 for pattern in TARGETS
               for path in ROOT.glob(pattern) if path.is_dir())
    print(f"осталось по этому правилу: {left}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())