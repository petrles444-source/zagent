"""Бэкап в zip: ключи не попадают, архив целый, мусор не тащится.

Проверяется ровно то, что бэкап испортить может:

* **ключ в архиве** — самая дорогая ошибка этого инструмента; здесь ключ
  заведён по-настоящему и проверяется дважды: по имени файла и по
  содержимому готового архива;
* **повреждённый архив** — бэкап, который не открывается, хуже
  отсутствия бэкапа, поэтому чтение проверяется сразу после сборки;
* **мусор в архиве** — `.venv` весит сотни мегабайт и при этом
  восстанавливается одной командой; попадание его в архив делает
  бэкап бессмысленно тяжёлым;
* **потерянные файлы** — снимок без исходников бесполезен, поэтому
  проверяется, что в архиве есть и Python-модули, и конфигурация.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from tools.backup_zip import SKIP_DIRS, collect, should_skip_file, verify


def make_project(root: Path) -> Path:
    """Мини-проект с ключом, мусором и настоящими исходниками."""
    (root / "config").mkdir(parents=True)
    (root / "hub").mkdir(parents=True)
    (root / "web-state").mkdir(parents=True)
    (root / "update").mkdir(parents=True)
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / "__pycache__").mkdir(parents=True)

    (root / "hub" / "worker.py").write_text("print('привет')\n", encoding="utf-8")
    (root / "hub" / "store.py").write_text("# база\n", encoding="utf-8")
    (root / "config" / "gateways.json").write_text('{"gateways": []}', encoding="utf-8")
    # Ключ настоящий по форме и по содержанию — его и ловим.
    (root / "config" / "secrets.local.json").write_text(
        '{"openrouter": ["sk-or-v1-РЕАЛЬНЫЙКЛЮЧ0123456789"]}', encoding="utf-8")
    # То, что обязано попасть: локальное состояние и планы.
    # bytes-литерал умеет только ASCII — «данные» записываем через строку.
    (root / "web-state" / "zagent.db").write_bytes("sqlite-данные".encode("utf-8"))
    (root / "update" / "idea.txt").write_text("идея\n", encoding="utf-8")
    # Мусор.
    (root / ".venv" / "lib" / "big.py").write_text("x" * 100, encoding="utf-8")
    (root / "__pycache__" / "a.pyc").write_bytes(b"\x00\x01")
    (root / "hub" / "worker.pyc").write_bytes(b"\x00\x01")
    (root / "logs").mkdir(parents=True)
    (root / "logs" / "usage.jsonl").write_text("{}\n", encoding="utf-8")
    return root


# ------------------------------------------------------------------ ключи

def test_ключи_не_попадают_в_архив(tmp_path: Path) -> None:
    """Главное правило: в бэкапе ключей быть не должно.

    Проверяется содержимое готового архива, а не список намерений: ошибка
    где-нибудь в обходе папок выглядит снаружи совершенно безобидно.
    """
    root = make_project(tmp_path / "proj")
    from tools.backup_zip import build

    target = build(root, tmp_path / "out")

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        for name in names:
            assert "secrets.local.json" not in name, f"в архиве {name}"
        # Содержимое тоже: ключ мог попасть в другой файл.
        for name in names:
            body = archive.read(name).decode("utf-8", "replace")
            assert "РЕАЛЬНЫЙКЛЮЧ" not in body, f"ключ утёк в {name}"
            assert "sk-or-v1" not in body, f"ключ утёк в {name}"


def test_файл_с_ключом_отсекается_по_имени(tmp_path: Path) -> None:
    """Проверка на уровне одной строки — тот запрет, который легко снять."""
    path = tmp_path / "config" / "secrets.local.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    assert should_skip_file(path, tmp_path) is True


# --------------------------------------------------------------- целостность

def test_архив_читается_и_не_повреждён(tmp_path: Path) -> None:
    from tools.backup_zip import build

    root = make_project(tmp_path / "proj")
    target = build(root, tmp_path / "out")
    assert verify(target) is True, "verify должен подтвердить целостность"


def test_повреждённый_архив_обнаруживается(tmp_path: Path) -> None:
    """Проверка обязана ловить битый архив, а не радоваться первому файлу.

    Раньше бы это прошло: zip умеет читать оглавление и часть файлов
    даже после порчи. Надёжная проверка читает файл целиком.
    """
    from tools.backup_zip import build

    root = make_project(tmp_path / "proj")
    target = build(root, tmp_path / "out")

    # Портим середину архива.
    raw = bytearray(target.read_bytes())
    for i in range(len(raw) // 2, min(len(raw) // 2 + 64, len(raw))):
        raw[i] ^= 0xFF
    broken = tmp_path / "broken.zip"
    broken.write_bytes(bytes(raw))

    assert verify(broken) is False, "битый архив прошёл как целый"


# ---------------------------------------------------------------- содержимое

def test_мусор_в_архив_не_попадает(tmp_path: Path) -> None:
    """.venv и кеши восстанавливаются, а весят сотни мегабайт."""
    root = make_project(tmp_path / "proj")
    names = {arc for _p, arc in collect(root)}
    for junk in (".venv", "__pycache__"):
        assert not any(junk in n for n in names), f"{junk} попал в архив"
    assert not any(n.endswith(".pyc") for n in names), "*.pyc попал в архив"


def test_исходники_и_локальное_состояние_попадают(tmp_path: Path) -> None:
    """Бэкап без исходников и без базы — не бэкап."""
    root = make_project(tmp_path / "proj")
    names = {arc for _p, arc in collect(root)}
    assert "hub/worker.py" in names
    assert "hub/store.py" in names
    assert "config/gateways.json" in names
    # Локальное состояние в git не едет, но для восстановления нужно.
    assert "web-state/zagent.db" in names
    assert "update/idea.txt" in names


def test_список_пропускает_каталоги_рекурсии(tmp_path: Path) -> None:
    """backup/ внутри backup/ — это архив в архиве, а бэкап."""
    root = make_project(tmp_path / "proj")
    (root / "backup").mkdir(parents=True)
    (root / "backup" / "старый.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    names = {arc for _p, arc in collect(root)}
    assert not any(n.startswith("backup/") for n in names)


def test_проверка_пропускает_пустой_корень(tmp_path: Path) -> None:
    """Пустой корень — не ошибка, а «нечего архивировать»."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert collect(empty) == []