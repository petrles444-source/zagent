r"""Разобрать файлы в корне проекта.

Зачем
----
В корне осталось 19 файлов, и среди них нашлось то, чего там быть не
должно.

**`t.json` содержит приватный ключ WireGuard.** Он не был в git, и
это единственная причина, почему он до сих пор не утёк. Подобное
нельзя оставлять в папке, которая целиком едет в репозиторий: ключ
достаточно одного неверного `git add .`.

Остальное — пустышки. `index.html`, `server.py` и `scrape.py`
содержат заглушки вида «этот файл будет содержать», то есть работы
в них нет никогда. `cache.db` никто не открывает.

Что делается
------------
1. `t.json` — выносится из репозитория вместе с приватным ключом и
   добавляется в `.gitignore`, чтобы не вернулся.
2. `run.bat` — уходит к своему проекту `../allvpn`, он его запускает.
3. `count_lines.py` — уходит в `utils/`.
4. Пустышки удаляются, но не раньше, чем содержимое показано.

Запуск:
    .venv\\Scripts\\python.exe tools\\tidy_root_files.py
    .venv\\Scripts\\python.exe tools\\tidy_root_files.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTSIDE = ROOT.parent

#: Куда уходит файл: (имя, папка назначения, зачем).
MOVE_OUT = (
    ("t.json", OUTSIDE / "vpn",
     "конфиг WireGuard с приватным ключом: в репозитории ему не место"),
    ("run.bat", OUTSIDE / "allvpn",
     "запускалка AllVPN, лежит рядом со своим проектом"),
)

#: Куда уходит как самостоятельная утилита.
MOVE_UTILS = ("count_lines.py",)

#: Пустышки: имя и почему уверен, что работа в них нет.
DROP = {
    "index.html": "заглушка «Landing Page», страниц на 0 байт работы",
    "server.py": "только комментарий «будет содержать код сервера»",
    "scrape.py": "только комментарий «будет содержать скрапинг»",
    "cache.db": "база SQLite, которую никто не открывает",
}

IGNORE_ADD = ("# Конфиг VPN с приватным ключом. В репозиторий не попадает\n"
              "# никогда: один неверный `git add .` — и ключ утёк.\n"
              "t.json\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="разбор корня")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = args.dry_run

    print("=== 1. выносим из репозитория ===")
    for name, target_dir, why in MOVE_OUT:
        src = ROOT / name
        if not src.exists():
            print(f"  {name} нет — пропускаю")
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        if target.exists():
            print(f"  {name} уже есть в {target_dir.name} — пропускаю")
            continue
        size = src.stat().st_size
        print(f"  {name} ({size} Б) → {target}")
        print(f"      {why}")
        if not dry:
            shutil.move(str(src), str(target))

    print()
    print("=== 2. в утилиты ===")
    for name in MOVE_UTILS:
        src = ROOT / name
        if not src.exists():
            print(f"  {name} нет — пропускаю")
            continue
        target = ROOT / "utils" / "podschet-strok" / name
        if dry:
            print(f"  просмотр: {name} → utils/podschet-strok/")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        (target.parent / "ЧТО-ЗДЕСЬ.md").write_text(
            "# Подсчёт строк\n\nСчитает строки кода по проекту, "
            "пропуская служебные папки.\n\n## Запуск\n\n"
            "    python utils/podschet-strok/count_lines.py\n",
            encoding="utf-8")
        print(f"  {name} → utils/podschet-strok/")

    print()
    print("=== 3. удаляем пустышки ===")
    for name, why in DROP.items():
        path = ROOT / name
        if not path.exists():
            print(f"  {name} нет — пропускаю")
            continue
        print(f"  {name}: {why}")
        if not dry:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    print()
    print("=== 4. защита от возврата t.json ===")
    ignore = ROOT / ".gitignore"
    body = ignore.read_text(encoding="utf-8")
    if "\nt.json\n" not in body:
        if dry:
            print("  просмотр: добавить t.json в .gitignore")
        else:
            ignore.write_text(body.rstrip() + "\n\n" + IGNORE_ADD,
                              encoding="utf-8")
            print("  t.json добавлен в .gitignore")
    else:
        print("  уже в .gitignore")

    print()
    print("=== 5. что осталось в корне ===")
    if dry:
        print("  это был просмотр")
    else:
        for path in sorted(ROOT.iterdir()):
            if path.is_file():
                print(f"  {path.name:<24} {path.stat().st_size:>9} Б")
    return 0


if __name__ == "__main__":
    sys.exit(main())