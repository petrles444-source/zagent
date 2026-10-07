"""Локальный бэкап проекта в zip: всё, что нужно, чтобы подняться заново.

Зачем отдельная штука, если есть git. Три причины:

* **Архив переживает плохой день.** `git checkout` требует корректного
  репозитория; zip требует только умения прочитать файл. Если сломалось
  состояние рабочей копии (запущенная правка, сорванный merge), архив
  остаётся целым.
* **В архив попадает то, что в git не едет.** `config/secrets.local.json`
  (ключи), `web-state/` (база с задачами и журналом), `update/` (планы и
  идеи) — всё это в `.gitignore` намеренно, но для восстановления рабочей
  машины оно нужно.
* **Один файл вместо тысячи.** Скопировать его на новый диск — и человек
  получил работающую установку.

Чего архив НЕ делает намеренно (и это важно):

* **Ключи в архив не кладутся.** Рядом живёт `config/secrets.zip`
  (зашифрованный, пароль известен владельцу), а сюда — только то, что
  можно распаковать на чужой машине и не получить чужой доступ.
* **Секреты из `env:` не кладутся** по той же причине.
* Ничего не удаляет: это снимок, а не операция.

Запуск: `python tools/backup_zip.py` (по умолчанию архив в `backup/`)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Куда складываем архивы. Вне гита: бэкапы не должны попадать в историю.
BACKUP_DIR = "backup"

#: Папки, которые полезно иметь в архиве, но которые никогда не едут в git.
#: Ключевая строка тут первая: `config/secrets.local.json` — это ключи.
LOCAL_ONLY_DIRS = ("web-state", "update", "projects", "logs")

#: Куда архив НЕ ходим никогда. Всё это либо воспроизводимо, либо чужие данные.
SKIP_DIRS = {
    ".git",          # история в git, а здесь только снимок файлов
    ".venv",         # виртуальное окружение качается заново и не переносится
    "__pycache__",
    "node_modules",
    "backup",        # архивы в архиве: рекурсия ради объёма
    "pytest-of-HP",  # мусор чужих прогонов тестов
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

#: Суффиксы, которые не имеют смысла хранить (восстанавливаются).
SKIP_SUFFIX = (".pyc", ".pyo", ".zip.tmp", ".log.1")

#: Файлы-исключения: состояние файловой панели и прогоны, которые не нужны.
SKIP_NAMES = {"desktop.ini", "Thumbs.db"}


def human(size: int) -> str:
    """Размер в привычных единицах: архив читают люди."""
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


def should_skip_file(path: Path, root: Path) -> bool:
    """Нужен ли файл в архиве.

    Самое важное здесь — `secrets.local.json`: без этой проверки архив
    уехал бы с ключами в открытом виде, а с ним можно было бы забыть,
    что ключи где-то лежат.
    """
    name = path.name
    if name in SKIP_NAMES:
        return True
    if name.endswith(SKIP_SUFFIX):
        return True
    if name == "secrets.local.json":
        # Явный запрет, а не «случайно забыли»: даже если файл уедет в
        # архив, ключи в git уже проверены, а тут — открытый zip.
        return True
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in rel.parts)


def collect(root: Path) -> list[tuple[Path, str]]:
    """Список файлов для архива: (путь, путь внутри архива)."""
    files: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Каталоги режем на месте: os.walk не спустится в отсечённое, и
        # в .venv мы даже не заходим — это десятки тысяч файлов.
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.endswith(".tmp")]
        current = Path(dirpath)
        for name in filenames:
            path = current / name
            if should_skip_file(path, root):
                continue
            try:
                if path.stat().st_size > 64 * 1024 * 1024:
                    # Файл в 64 МБ — это не исходник, а случайность
                    # (дамп, лог, кеш). В бэкап исходников он не нужен.
                    continue
            except OSError:
                continue
            files.append((path, str(path.relative_to(root)).replace("\\", "/")))
    return files


def build(root: Path, out_dir: Path) -> Path:
    """Собрать архив и вернуть его путь."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S")
    target = out_dir / f"zagent-{stamp}.zip"

    files = collect(root)
    # Второй проход по уже готовому списку: так мы точно знаем, что в
    # архив попало, и можем написать честный итог в консоль.
    written = 0
    total = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6) as archive:
        for path, arcname in files:
            try:
                archive.write(path, arcname)
            except OSError as exc:
                # Один нечитаемый файл не должен ронять бэкап: снимок
                # делается под давлением («сломалась программа — спаси»),
                # и частичный архив полезнее, чем никакого.
                print(f"  пропущен {arcname}: {type(exc).__name__}", file=sys.stderr)
                continue
            written += 1
            total += path.stat().st_size

    print(f"Архив: {target}")
    print(f"Файлов: {written} из {len(files)} запланированных")
    print(f"Исходный объём: {human(total)}")
    print(f"Архив весит: {human(target.stat().st_size)}")
    print(f"Ключи в архив НЕ попали (config/secrets.local.json исключён).")
    return target


def verify(path: Path) -> bool:
    """Проверить, что архив читается и ключей в нём нет.

    Архив, который не открывается, хуже отсутствия архива: человек
    узнаёт об этом только в момент, когда он понадобился. Поэтому после
    сборки читаем его обратно и убеждаемся, что он целый.
    """
    # Любое исключение здесь — это и есть ответ «архив битый».
    # Проверка обязана его пережить и вернуть False: вызывающий код
    # смотрит на возвращаемое значение, а исключение из проверки
    # выглядело бы как «инструмент сломался» вместо «снимок плохой».
    try:
        with zipfile.ZipFile(path) as archive:
            broken = archive.testzip()
            if broken:
                print(f"ПОВРЕЖДЁН файл внутри архива: {broken}", file=sys.stderr)
                return False
            names = archive.namelist()
            leaked = [n for n in names if n.endswith("secrets.local.json")]
            if leaked:
                print(f"В архиве ключи: {leaked}", file=sys.stderr)
                return False
            # Читаем содержимое целиком: zip умеет отдать оглавление даже
            # после порчи хвоста, и «архив открылся» ничего не значит.
            for name in names:
                archive.read(name)
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError,
            RuntimeError) as exc:
        print(f"Архив не читается: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    print(f"Проверка архива: целый, {len(names)} записей, ключей нет.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Бэкап проекта в zip")
    parser.add_argument("--root", default=str(ROOT), help="что архивировать")
    parser.add_argument("--out", default="", help="куда класть архив")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = Path(args.out).resolve() if args.out else root / BACKUP_DIR
    print(f"Архивирую {root}")
    target = build(root, out_dir)
    return 0 if verify(target) else 1


if __name__ == "__main__":
    raise SystemExit(main())