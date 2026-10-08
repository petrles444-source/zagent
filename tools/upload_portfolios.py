r"""Выложить портфолио на хостинг: папки, файлы, без сжатия.

Зачем отдельно от tools\upload_site.py
-------------------------------------
Тот грузит готовую плоскую сборку в корень. Здесь каждый портфолио —
отдельный каталог со своими файлами, поэтому нужно создавать папки.

Про создание папок
------------------
Раньше `STOR portal/index.html` с `--create-dirs` отвечал отказом, и
вывод был «папки по FTP не создаются». Вывод неверный: явная команда
`MKD` проходит, а отказ касался вложенного пути сразу. Поэтому шаг
создания папки здесь отдельный и проверяемый: папка создаётся, потом
в неё кладутся файлы.

Учётные данные
--------------
Токен и логин читаются из переменных окружения, как в upload_site.py.
В коде их нет, и в репозиторий они не попадают.

Запуск:
    set ZAGENT_FTP_HOST=s726.ucoz.net
    set ZAGENT_FTP_USER=8zagent
    set ZAGENT_FTP_PASS=...
    .venv\Scripts\python.exe tools\upload_portfolios.py
    .venv\Scripts\python.exe tools\upload_portfolios.py --dry-run
"""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIOS = ROOT / "portfolios"

#: Хост и логин — не секреты. Пароль только из окружения.
DEFAULTS = {"ZAGENT_FTP_HOST": "s726.ucoz.net", "ZAGENT_FTP_USER": "8zagent"}

#: Расширения, которые сервер принимает. Всё остальное лучше не
#: заливать: часть имён он отклоняет, а толку от отказа мало.
SKIP_SUFFIXES = {".map", ".pyc"}


def human(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} МБ"
    if size >= 1024:
        return f"{size / 1024:.0f} КБ"
    return f"{size} Б"


def build_mark(source: Path) -> str:
    """Метка сборки портфолио: хэш имён и содержимого css/js.

    Хостинг отдаёт документы с кэшем в 20 дней, поэтому после правки
    страница продолжает работать на старой версии файла: загруженный
    заново `app.js` браузер не спрашивает. Метка `?v=…` в ссылках
    считается от содержимого самих файлов, поэтому меняется ровно тогда,
    когда меняется файл, и поддерживать её вручную не нужно.

    Шрифты в метку не входят: на них ссылается css, и его новая метка
    уже тянет за собой новый адрес шрифта.
    """
    digest = hashlib.sha256()
    for item in sorted(source.rglob("*")):
        if item.is_file() and item.suffix in (".css", ".js"):
            digest.update(item.name.encode("utf-8"))
            digest.update(item.read_bytes())
    return digest.hexdigest()[:10]


def stamp_html(text: str, mark: str) -> str:
    """Дописать метку к ссылкам на локальные скрипты и стили.

    Метка ставится только на локальные файлы: внешних адресов на странице
    быть не должно, а они живут своей жизнью и метку не получают.
    """
    text = re.sub(
        r'(<(?:script|link)[^>]*?\b(?:src|href)=")([A-Za-z0-9_.-]+\.(?:js|css))(")',
        lambda m: f"{m.group(1)}{m.group(2)}?v={mark}{m.group(3)}",
        text,
    )
    # Ссылка «обновить» в подвале. Кэш документа у хостинга длинный, и
    # без неё посетитель увидит старую разметку вместе со старыми
    # ссылками на скрипты: метки внутри неё ещё не было.
    text = re.sub(r'(<a class="ver-link" href=")[^"]*(")',
                  lambda m: f"{m.group(1)}?v={mark}{m.group(2)}", text)
    text = re.sub(r'(<a class="ver-link"[^>]*>)обновить',
                  rf'\g<1>сборка {mark} · обновить', text)
    return text


def stamp_dir(source: Path) -> Path | None:
    """Положить рядом копию каталога с метками. None — меток не нужно.

    Копия делается в памяти и в отдельную временную папку: исходники
    должны остаться без `?v=` в разметке, иначе при следующей загрузке
    метки начнут накапливаться одна на другой. Временная папка нужна
    потому, что `storbinary` читает файл, а не байты из памяти.
    """
    mark = build_mark(source)
    target = Path(tempfile.mkdtemp(prefix="portfolio-stamp-"))
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        if item.is_dir():
            (target / rel).mkdir(parents=True, exist_ok=True)
            continue
        if item.suffix == ".html":
            text = item.read_text(encoding="utf-8")
            stamped = stamp_html(text, mark)
            if stamped != text:
                (target / rel).write_text(stamped, encoding="utf-8")
                continue
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target / rel)
    return target if mark else None


def ensure_dir(ftp: ftplib.FTP, path: str) -> bool:
    """Создать каталог. True — создан, False — уже был."""
    try:
        ftp.mkd(path)
        return True
    except ftplib.error_perm as exc:
        text = str(exc)
        # 550 — «уже существует» в большинстве серверов. Остальное —
        # настоящая ошибка, её надо показать, а не замолчать.
        if "550" in text:
            return False
        raise


def upload_site(ftp: ftplib.FTP, name: str, root: Path,
                dry_run: bool = False) -> tuple[int, int]:
    """Залить один портфолио. Возвращает (файлов, байт)."""
    source = root / name
    if not source.is_dir():
        print(f"  {name}: нет папки {source}")
        return 0, 0
    files = [p for p in sorted(source.rglob("*"))
             if p.is_file() and p.suffix.lower() not in SKIP_SUFFIXES]
    total = sum(p.stat().st_size for p in files)
    print(f"  {name}: {len(files)} файлов, {human(total)}")

    if dry_run:
        for item in files:
            print(f"      {item.relative_to(source).as_posix()}")
        return len(files), total

    created = ensure_dir(ftp, name)
    print(f"      папка {name}: {'создана' if created else 'уже была'}")

    # Заливаем с метками: исходники остаются чистыми, в сеть уходит
    # копия, у которой ссылки на css/js помечены содержимым.
    stamped = stamp_dir(source)
    if stamped is not None:
        print(f"      метка сборки: v={build_mark(source)}")
        try:
            for item in sorted(p for p in stamped.rglob("*") if p.is_dir()):
                ensure_dir(ftp, (name + "/" +
                                 item.relative_to(stamped).as_posix()).replace("\\", "/"))
            count = 0
            for index, item in enumerate(sorted(p for p in stamped.rglob("*")
                                                 if p.is_file()), 1):
                remote = (name + "/" +
                          item.relative_to(stamped).as_posix()).replace("\\", "/")
                try:
                    with item.open("rb") as stream:
                        ftp.storbinary(f"STOR {remote}", stream, blocksize=1 << 16)
                except ftplib.error_perm as exc:
                    print(f"      ОТКАЗ {remote}: {exc}")
                    continue
                count += 1
                print(f"      [{index}/{len(files)}] {remote}")
        finally:
            shutil.rmtree(stamped, ignore_errors=True)
        return count, total

    for index, item in enumerate(files, 1):
        remote = (name + "/" + item.relative_to(source).as_posix()).replace("\\", "/")
        try:
            with item.open("rb") as stream:
                ftp.storbinary(f"STOR {remote}", stream, blocksize=1 << 16)
        except ftplib.error_perm as exc:
            print(f"      ОТКАЗ {remote}: {exc}")
            continue
        print(f"      [{index}/{len(files)}] {remote}")
    return len(files), total


def main() -> int:
    parser = argparse.ArgumentParser(description="выложить портфолио")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать список и не загружать")
    parser.add_argument("--only", help="только этот портфолио")
    args = parser.parse_args()

    if not PORTFOLIOS.is_dir():
        print(f"нет папки {PORTFOLIOS}")
        return 2

    names = sorted(p.name for p in PORTFOLIOS.iterdir() if p.is_dir())
    if args.only:
        names = [args.only]
    if not names:
        print("в portfolios/ нет ни одной папки")
        return 2

    env = {**DEFAULTS, **{k: v for k, v in os.environ.items() if v}}
    host = env.get("ZAGENT_FTP_HOST", "")
    user = env.get("ZAGENT_FTP_USER", "")
    password = env.get("ZAGENT_FTP_PASS", "")

    print(f"портафолио: {', '.join(names)}")
    print(f"куда: {host}")
    if args.dry_run:
        ftp = None
    else:
        if not host or not user or not password:
            print("не хватает ZAGENT_FTP_HOST / USER / PASS")
            return 2

    started = time.monotonic()
    summary: list[tuple[str, int, int]] = []
    failed = 0
    # Соединение нужно только для реальной загрузки: в --dry-run сервер
    # не трогаем вообще. Переменная объявлена заранее — иначе обращение
    # к ней падает с UnboundLocalError, если ветка подключения не
    # выполнялась.
    ftp: ftplib.FTP | None = None
    if not args.dry_run:
        ftp = ftplib.FTP()
        ftp.connect(host, timeout=60)
        ftp.login(user, password)
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")
    try:
        for name in names:
            count, size = upload_site(ftp, name, PORTFOLIOS, args.dry_run)
            summary.append((name, count, size))
    except ftplib.all_errors as exc:
        print(f"связь прервана: {exc}")
        failed += 1
    finally:
        if ftp is not None and not args.dry_run:
            try:
                ftp.quit()
            except Exception:
                pass

    print("\nитого:")
    for name, count, size in summary:
        print(f"  {name:12} {count:3} файлов  {human(size):>9}")
    print(f"за {time.monotonic() - started:.0f} с")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
