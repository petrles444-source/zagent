r"""Дожать перенос: снять ReadOnly и переместить остальное.

Зачем
----
`shutil.move` переносит папку одним `os.rename`, и на Windows он
падает с `Access is denied`, если внутри есть каталоги с атрибутом
ReadOnly. Именно так встал перенос `vpn`: папка появилась в
родителе, но исходная осталась на месте, то есть перенос был
частичным.

Ровно та же причина, что и с папками `zagent-bench-*`: там помог
`os.chmod` по всему дереву, а `icacls /reset` и `/grant` не помогли,
хотя возвращали код 0.

Порядок важен: права снимаются **до** перемещения. Обратный порядок
просто вернёт тот же самый отказ.

Запуск:
    .venv\\Scripts\\python.exe tools\\finish_moves.py
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTSIDE = ROOT.parent

#: Что ещё осталось перенести.
REMAINING = (
    ("content/Photopost", "photopost"),
    ("vpn", "vpn"),
    ("colab", "colab"),
)

#: Папки, которые придётся дочистить вручную: родитель уже есть, но
#: исходник не пропал.
MERGE = (("vpn", "vpn"),)


def clear_readonly(path: Path) -> int:
    """Снять ReadOnly со всего дерева."""
    cleared = 0
    for item in [path, *path.rglob("*")]:
        if not item.is_dir():
            continue
        try:
            os.chmod(item, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            cleared += 1
        except OSError:
            pass
    return cleared


def main() -> int:
    print("=== дожимаю перенос ===\n")

    # 1. Дописать то, что ещё не переехало.
    for src_rel, dst_name in REMAINING:
        src = ROOT / src_rel
        dst = OUTSIDE / dst_name
        if not src.exists():
            print(f"  {src_rel} уже уехал — пропускаю")
            continue
        if dst.exists() and any(dst.iterdir()):
            print(f"  {dst_name} в родителе уже не пуст — пропускаю, "
                  "разбираться вручную")
            continue
        cleared = clear_readonly(src)
        try:
            shutil.move(str(src), str(dst))
            print(f"  {src_rel} → {dst}  (снято прав: {cleared})")
        except OSError as exc:
            print(f"  {src_rel} НЕ ПЕРЕНЕСЁН: {exc}")

    # 2. Дочистить частичный перенос `vpn`.
    for src_name, dst_name in MERGE:
        src = ROOT / src_name
        dst = OUTSIDE / dst_name
        if not src.exists() or not src.is_dir():
            continue
        files = [f for f in src.rglob("*") if f.is_file()]
        if not files:
            print(f"  {src_name}: пустая, убираю")
            shutil.rmtree(src, ignore_errors=True)
            continue
        print(f"  {src_name}: осталось {len(files)} файлов, "
              f"дописываю в {dst_name}")
        for item in sorted(src.rglob("*"), reverse=True):
            target = dst / item.relative_to(src)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                shutil.copy2(item, target)
        clear_readonly(src)
        shutil.rmtree(src, ignore_errors=True)
        print(f"  {src_name}: дочищено, исходник убран")

    # 3. Пустая папка `content` больше не нужна.
    content = ROOT / "content"
    if content.is_dir() and not any(content.iterdir()):
        content.rmdir()
        print("  content/: пустая, убрана")

    print()
    print("=== проверка ===")
    for src_rel, dst_name in REMAINING:
        src = ROOT / src_rel.split("/")[0]
        print(f"  {'ок ' if not src.exists() else 'ОСТАЛОСЬ'} "
              f"zagent/{src_rel}   →   ../{dst_name}: "
              f"{'есть' if (OUTSIDE / dst_name).exists() else 'НЕТ'}")

    left = [p.name for p in ROOT.iterdir()
            if p.is_dir() and p.name not in (
                "hub", "providers", "config", "bench", "tests", "tools",
                "hosting", "bot-worker", "projects", "site", "site-dist",
                "portfolios", "publish", "docs", "reports", "ref", "tasks",
                ".venv", ".git", ".hf-cache", "web", "web-static",
                "web-state", "music", "tmp", "assets")]
    print()
    print("неучтённые папки в корне:", left or "нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())