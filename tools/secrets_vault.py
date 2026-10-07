#!/usr/bin/env python3
r"""Сейф для секретов: архив с настоящими ключами под паролем.

    python tools/secrets_vault.py pack --password 5555        # запаковать
    python tools/secrets_vault.py list --password 5555        # что внутри
    python tools/secrets_vault.py extract --password 5555     # распаковать

Пароль можно не писать в командной строке — тогда программа спросит его без
эха (в аргументах пароль остаётся в истории шелла и в `ps`).

Что кладётся в архив: `config/secrets.local.json` и `config/keys.json` —
файлы с настоящими ключами, которые и так вне гита. Архив (`config/secrets.zip`)
лежит рядом и тоже вне гита: правило `*.zip` есть в `.gitignore`.

Формат — ZIP со шифром WinZip AES-256, читается WinRAR, 7-Zip и `pyzipper`.
Обычный `zipfile` из стандартной библиотеки шифровать не умеет, поэтому
нужен `pyzipper` (он в requirements.txt).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import pyzipper
except ImportError:  # pragma: no cover - среда без зависимости
    pyzipper = None  # type: ignore[assignment]

#: Файлы с настоящими ключами. Относительно корня проекта.
SECRET_FILES = (
    "config/secrets.local.json",
    "config/keys.json",
)

#: Куда кладётся архив. `*.zip` в `.gitignore`, поэтому в репозиторий
#: он не попадает — проверка на это есть в тестах.
ARCHIVE = "config/secrets.zip"


class VaultError(RuntimeError):
    """Операция с архивом отклонена: нет зависимости, пароля или файлов."""


def _require_pyzipper() -> None:
    if pyzipper is None:
        raise VaultError(
            "Не установлен pyzipper: .venv\\Scripts\\python.exe -m pip install pyzipper"
        )


def _password(text: str | None, *, prompt: str = "Пароль архива: ") -> bytes:
    if not text:
        text = getpass.getpass(prompt)
    if not text:
        raise VaultError("Пустой пароль")
    return text.encode("utf-8")


def pack(
    root: Path | str,
    password: bytes,
    *,
    archive: Path | str | None = None,
    files: tuple[str, ...] = SECRET_FILES,
) -> Path:
    """Собрать файлы с ключами в зашифрованный архив.

    Пишем через временный файл и подменяем: если прервать посередине,
    на месте сейфа осталась бы обрезанная куча байтов вместо архива.
    """
    _require_pyzipper()
    root = Path(root)
    target = Path(archive) if archive else root / ARCHIVE
    target.parent.mkdir(parents=True, exist_ok=True)

    present = [name for name in files if (root / name).is_file()]
    if not present:
        raise VaultError(f"Ни одного файла из {', '.join(files)} нет в {root}")

    tmp = target.with_name(target.name + ".tmp")
    with pyzipper.AESZipFile(
        tmp, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
    ) as zf:
        zf.setpassword(password)
        for name in present:
            zf.write(root / name, arcname=name)
    tmp.replace(target)
    return target


def namelist(archive: Path | str, password: bytes) -> list[str]:
    """Имена файлов внутри архива (пароль нужен: без него список не читается)."""
    _require_pyzipper()
    with pyzipper.AESZipFile(archive) as zf:
        zf.setpassword(password)
        # Намеренно читаем по байту: у AESZipFile имена видны и без пароля,
        # но проверить, что пароль верный, важно уже здесь.
        for name in zf.namelist():
            with zf.open(name) as fh:
                fh.read(1)
        return list(zf.namelist())


def extract(archive: Path | str, password: bytes, out_dir: Path | str) -> list[Path]:
    """Распаковать архив в указанную папку."""
    _require_pyzipper()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with pyzipper.AESZipFile(archive) as zf:
        zf.setpassword(password)
        names = zf.namelist()
        zf.extractall(out)
    return [out / name for name in names]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Архив с ключами под паролем")
    parser.add_argument("action", choices=("pack", "list", "extract"))
    parser.add_argument("--password", help="пароль (спрашивается, если не дать)")
    parser.add_argument("--root", default=None, help="корень проекта")
    parser.add_argument("--archive", default=None, help=f"путь к архиву, по умолчанию {ARCHIVE}")
    parser.add_argument("--out", default=None, help="куда распаковать (list/extract)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    archive = Path(args.archive) if args.archive else root / ARCHIVE
    try:
        secret = _password(args.password)
        if args.action == "pack":
            made = pack(root, secret, archive=archive)
            print(f"запаковано: {made}")
            for name in namelist(made, secret):
                print("  внутри:", name)
        elif args.action == "list":
            for name in namelist(archive, secret):
                print(name)
        else:
            for path in extract(archive, secret, args.out or root):
                print("извлечено:", path)
    except VaultError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # битый пароль, битый архив — тоже ответ пользователю
        print(f"не получилось: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
