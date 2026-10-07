"""Сейф для секретов: архив с настоящими ключами под паролем.

Здесь проверяется то, что нельзя доверять на слово: пароль действительно
закрывает файл (не просто архив есть), байты после распаковки те же самые,
и архив с ключами не может попасть в git.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from tools.secrets_vault import (
    ARCHIVE,
    SECRET_FILES,
    VaultError,
    extract,
    main,
    namelist,
    pack,
)

PASSWORD = b"5555"


def make_root(tmp_path: Path, *, with_keys_json: bool = True) -> Path:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "secrets.local.json").write_text(
        '{"groq": ["gsk_REAL"], "cloudflare_token": "cfut_REAL"}',
        encoding="utf-8",
    )
    if with_keys_json:
        (tmp_path / "config" / "keys.json").write_text(
            '{"legacy": "REAL"}', encoding="utf-8"
        )
    return tmp_path


def test_архив_собирается_и_открывается_тем_же_паролем(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    arc = pack(root, PASSWORD)
    assert arc.is_file() and arc.name == Path(ARCHIVE).name

    names = namelist(arc, PASSWORD)
    assert set(names) == set(SECRET_FILES)

    out = tmp_path / "restored"
    restored = extract(arc, PASSWORD, out)
    assert len(restored) == 2
    original = (root / "config" / "secrets.local.json").read_bytes()
    assert (out / "config" / "secrets.local.json").read_bytes() == original


def test_неверный_пароль_ключ_не_отдаёт(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    arc = pack(root, PASSWORD)
    with pytest.raises(RuntimeError, match="[Bb]ad password"):
        namelist(arc, b"0000")
    # И распаковка тоже закрыта, а не только список файлов.
    with pytest.raises(RuntimeError, match="[Bb]ad password"):
        extract(arc, b"0000", tmp_path / "out")
    assert not (tmp_path / "out" / "config" / "secrets.local.json").exists()


def test_шифр_настоящий_а_не_прозрачный_zip(tmp_path: Path) -> None:
    """Стандартный `zipfile` видит архив, но не может его прочитать.

    Флаг 0x1 — «файл зашифрован», тип 99 — WinZip AES. Если хоть одно
    условие не выполнено, ключи лежат в архиве открытым текстом.
    """
    root = make_root(tmp_path)
    arc = pack(root, PASSWORD)
    with zipfile.ZipFile(arc) as zf:
        info = zf.infolist()[0]
        assert info.flag_bits & 0x1, "файл не помечен как зашифрованный"
        assert info.compress_type == 99, "ожидался WinZip AES, не deflate"
    with zipfile.ZipFile(arc) as zf:
        with pytest.raises(RuntimeError):
            zf.read(zf.namelist()[0])


def test_без_файлов_сейф_не_создаётся(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    with pytest.raises(VaultError, match="Ни одного файла"):
        pack(tmp_path, PASSWORD)
    assert not (tmp_path / ARCHIVE).exists()


def test_повторная_запись_перетирает_старый_архив(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    arc = pack(root, PASSWORD)
    size_old = arc.stat().st_size
    (root / "config" / "secrets.local.json").write_text(
        '{"groq": ["gsk_1", "gsk_2", "gsk_3", "gsk_4"]}', encoding="utf-8"
    )
    pack(root, PASSWORD)
    assert arc.stat().st_size != size_old
    assert not arc.with_name(arc.name + ".tmp").exists(), "остался хвост .tmp"
    # старого содержимого в новом архиве нет
    out = tmp_path / "check"
    extract(arc, PASSWORD, out)
    assert b"gsk_4" in (out / "config" / "secrets.local.json").read_bytes()


def test_архив_с_ключами_вне_гита() -> None:
    """Правило `*.zip` обязано быть в .gitignore: сейф не публикуется."""
    ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
        encoding="utf-8"
    )
    patterns = [
        line.strip() for line in ignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "*.zip" in patterns, "архив с ключами попадёт в репозиторий"
    assert "config/secrets.local.json" in patterns


def test_cli_с_паролем_и_без(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = make_root(tmp_path)
    assert main(["pack", "--password", "5555", "--root", str(root)]) == 0
    assert "запаковано" in capsys.readouterr().out

    assert main(["list", "--password", "5555", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "config/secrets.local.json" in out

    assert main(["list", "--password", "нет", "--root", str(root)]) == 1
    err = capsys.readouterr().err
    assert "не получилось" in err
