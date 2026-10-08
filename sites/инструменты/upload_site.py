r"""Залить собранный портал на хостинг по FTP.

Прячемся на стандартной библиотеке: `ftplib` умеет всё нужное и не
тянет за собой зависимостей. Пароль в коде не хранится — читается из
переменных окружения, чтобы случайная отправка файла в репозиторий не
унесла доступ к сайту.

Переменные:
    ZAGENT_FTP_HOST   адрес сервера
    ZAGENT_FTP_USER   логин
    ZAGENT_FTP_PASS   пароль
    ZAGENT_FTP_DIR    каталог на сервере (по умолчанию корень)

Запуск (PowerShell):
    $env:ZAGENT_FTP_HOST='s726.ucoz.net'
    $env:ZAGENT_FTP_USER='8zagent'
    $env:ZAGENT_FTP_PASS='...'
    .venv\Scripts\python.exe tools\upload_site.py
    .venv\Scripts\python.exe tools\upload_site.py --dry-run
"""

from __future__ import annotations

import argparse
import ftplib
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "site-dist"

#: Хост и логин — не секреты, их удобно иметь под рукой. Пароль сюда
#: не вписывается принципиально.
DEFAULTS = {"ZAGENT_FTP_HOST": "s726.ucoz.net", "ZAGENT_FTP_USER": "8zagent"}


def human(size: int) -> str:
    """Размер файла словами: килобайты неудобно читать в списке из 53 строк."""
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} МБ"
    if size >= 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size} Б"


def upload(dry_run: bool = False) -> int:
    if not DIST.exists():
        print(f"Нет папки {DIST}. Сначала tools\\build_site.py", file=sys.stderr)
        return 2

    # Собираем файлы рекурсивно, а не только из корня: картинки лежат
    # в `img/`, и раньше они просто молча не выкладывались — страница
    # ссылалась на пустоту, а загрузчик рапортовал об успехе.
    files = sorted(p for p in DIST.rglob("*") if p.is_file())
    if not files:
        print(f"{DIST} пуста", file=sys.stderr)
        return 2

    # 1. Виджет агента без настроек молчит: он читает `ai.json`, и если
    #    файла нет, кнопка на страницах просто не появляется. Такой
    #    отказ виден только посетителю, поэтому ловим его здесь — до
    #    выкладки. Порядок «build_site.py, затем place_ai_config.py»
    #    каждый раз надо помнить руками, и однажды про него забывают.
    if not (DIST / "ai.json").is_file():
        print("В сборке нет ai.json — виджет агента не будет работать.",
              file=sys.stderr)
        print("  .venv\\Scripts\\python.exe tools\\place_ai_config.py",
              file=sys.stderr)
        return 2

    # 2. Удалённый путь каждого файла: подпапки сохраняются, и перед
    #    выкладкой их надо создать на сервере.
    rels = [p.relative_to(DIST) for p in files]

    env = {**DEFAULTS, **{k: v for k, v in os.environ.items() if v}}
    host = env.get("ZAGENT_FTP_HOST", "")
    user = env.get("ZAGENT_FTP_USER", "")
    password = env.get("ZAGENT_FTP_PASS", "")
    folder = env.get("ZAGENT_FTP_DIR", "").strip("/")

    if not host or not user or not password:
        print("Не хватает ZAGENT_FTP_HOST / USER / PASS", file=sys.stderr)
        return 2

    total = sum(p.stat().st_size for p in files)
    print(f"файлов: {len(files)}, объём: {human(total)}")
    print(f"куда: {host}/{folder}")
    if dry_run:
        for path, rel in zip(files, rels):
            print(f"  {rel.as_posix():42} {human(path.stat().st_size):>9}")
        return 0

    started = time.monotonic()
    failed: list[tuple[str, str]] = []
    with ftplib.FTP() as ftp:
        ftp.connect(host, timeout=60)
        ftp.login(user, password)
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")           # двоичный режим: без него портятся .wasm
        if folder:
            ftp.cwd(folder)

        # Папки создаём заранее и по одной: `MKD` проходит, а вот
        # вложенный путь в `STOR` сервер отклоняет, поэтому файлы из
        # подпапок уходят после перехода в неё.
        made: set[str] = set()
        for index, (path, rel) in enumerate(zip(files, rels), 1):
            remote = rel.as_posix()
            parent = str(Path(remote).parent.as_posix())
            try:
                if parent != "." and parent not in made:
                    for part in parent.split("/"):
                        try:
                            ftp.mkd(part)
                            print(f"  папка {part}: создана")
                        except ftplib.error_perm as exc:
                            # 550 — «уже существует», это не ошибка.
                            if "550" not in str(exc):
                                raise
                    made.add(parent)

                with path.open("rb") as stream:
                    ftp.storbinary(f"STOR {remote}", stream, blocksize=1 << 16)
                print(f"  [{index:2}/{len(files)}] {remote:42} ок")
            except Exception as exc:  # сеть может оборваться в любой момент
                failed.append((remote, f"{type(exc).__name__}: {exc}"))
                print(f"  [{index:2}/{len(files)}] {remote:42} ОШИБКА {exc}")
    spent = time.monotonic() - started
    speed = total / max(spent, 0.1) / 1024 / 1024
    print(f"готово за {spent:.0f} с ({speed:.1f} МБ/с)")
    if failed:
        print(f"не залито: {len(failed)}")
        for name, why in failed[:10]:
            print(f"   {name}: {why}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="залить портал на хостинг")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать список файлов и выйти")
    args = parser.parse_args()
    return upload(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
