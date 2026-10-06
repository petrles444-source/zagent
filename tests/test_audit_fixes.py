"""Граница воркспейса не должна обходиться через shell и через картинку.

Три находки аудита:

* `capture_screen` считался операцией чтения, хотя перезаписывает файл по
  любому пути. Агент с уровнем «только чтение» мог затереть чужой `.py`
  данными PNG без всякого вопроса.
* Проверка путей в shell-команде искала только `> файл` и `--output`.
  `del C:\\Users\\HP\\файл`, `python -c "open(...)"` и `powershell
  Set-Content` проходили мимо, а жёсткая граница давала ложное чувство стены.
* `edit_file` читал с `errors="replace"` и перезаписывал файл целиком:
  безобидная правка необратимо портила .bat в cp1251 и возвращала `ok=True`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.autonomy import AccessLevel, Autonomy, Guard  # noqa: E402
from hub.tools import (  # noqa: E402
    _paths_in_command,
    _read_text_preserving,
    run_tool,
)


def guard_for(root: Path, access: AccessLevel = AccessLevel.FULL,
              soft: bool = False) -> Guard:
    g = Guard(access=access, autonomy=Autonomy.YOLO, workspace_root=root.resolve())
    g.set_workspace(root, "ws", soft_boundary=soft)
    return g


# =============================================================== H2 скриншот


def test_скриншот_считается_записью(tmp_path: Path) -> None:
    """Путь снимка проверяется на запись, иначе граница обходится картинкой."""
    outside = tmp_path.parent / "чужая-папка.py"
    res = run_tool("capture_screen", guard_for(tmp_path, AccessLevel.FULL),
                   output=str(outside))
    # Жёсткая граница: отказ без вопроса.
    assert res.ok is False, "файл вне воркспейса записан при жёсткой границе"
    assert not outside.exists()


def test_скриншот_не_перезаписывает_существующий(tmp_path: Path) -> None:
    """Даже внутри воркспейса чужой файл нельзя затереть молча."""
    target = tmp_path / "код.py"
    target.write_text("print('важное')", encoding="utf-8")
    res = run_tool("capture_screen", guard_for(tmp_path), output="код.py")
    assert res.ok is False
    assert target.read_text(encoding="utf-8") == "print('важное')"
    assert res.needs_user is True, "нужен вопрос пользователю"


def test_скриншот_разрешён_в_новый_файл(tmp_path: Path) -> None:
    res = run_tool("capture_screen", guard_for(tmp_path),
                   output="screenshots/снимок.png")
    # Pillow может быть не установлен — тогда ошибка про Pillow, а не про путь.
    if not res.ok:
        assert "Pillow" in res.error or "pillow" in res.error.lower(), res.error


# =============================================================== H4 edit_file


def test_правка_cp125и_отказывает(tmp_path: Path) -> None:
    """Крякозябры не должны попадать обратно в файл."""
    target = tmp_path / "старый.bat"
    original = "@echo off\r\nREM привет мир\r\n".encode("cp1251")
    target.write_bytes(original)

    res = run_tool("edit_file", guard_for(tmp_path), path="старый.bat",
                   old="привет", new="пока")
    assert res.ok is False
    assert "UTF-8" in res.error or "utf-8" in res.error.lower()
    assert target.read_bytes() == original, "файл изменился несмотря на отказ"
    assert res.needs_user is True


def test_правка_utf8_работает(tmp_path: Path) -> None:
    target = tmp_path / "обычный.py"
    target.write_text("a = 1\nb = 2\n", encoding="utf-8")
    res = run_tool("edit_file", guard_for(tmp_path), path="обычный.py",
                   old="a = 1", new="a = 99")
    assert res.ok, res.error
    assert target.read_text(encoding="utf-8") == "a = 99\nb = 2\n"


def test_bom_не_ломает_правку(tmp_path: Path) -> None:
    """BOM — метка кодировки, а не повод отказывать."""
    target = tmp_path / "с_bom.py"
    target.write_text("﻿a = 1\n", encoding="utf-8")
    res = run_tool("edit_file", guard_for(tmp_path), path="с_bom.py",
                   old="a = 1", new="a = 2")
    assert res.ok, res.error
    # BOM обязан сохраниться: иначе файл поменяет кодировку.
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_правка_не_оставляет_временных_файлов(tmp_path: Path) -> None:
    target = tmp_path / "файл.py"
    target.write_text("x = 1\n", encoding="utf-8")
    run_tool("edit_file", guard_for(tmp_path), path="файл.py",
             old="x = 1", new="x = 2")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith("-tmp")]
    assert not leftovers, f"остались временные файлы: {leftovers}"


def test_чтение_сохраняет_кодировку(tmp_path: Path) -> None:
    """Функция чтения обязана отличать UTF-8 от прочих."""
    utf8 = tmp_path / "a.py"
    utf8.write_text("да", encoding="utf-8")
    text, enc = _read_text_preserving(utf8)
    assert text == "да" and "utf-8" in enc.lower()

    legacy = tmp_path / "b.bat"
    legacy.write_bytes("да".encode("cp1251"))
    text, enc = _read_text_preserving(legacy)
    assert text == "да" and enc == "cp1251"

    binary = tmp_path / "c.bin"
    binary.write_bytes(bytes([0x00, 0xFF, 0xFE, 0x80, 0x81]))
    text, enc = _read_text_preserving(binary)
    assert text is None, "двоичный файл не должен читаться как текст"


# =============================================================== H1 shell


def test_del_с_абсолютным_путём_ловится(tmp_path: Path) -> None:
    victim = tmp_path.parent / "важное.txt"
    paths = _paths_in_command(f'del "{victim}"', tmp_path)
    assert any(str(victim).lower() in p.lower() for p in paths), paths


def test_python_c_ловится(tmp_path: Path) -> None:
    """Раньше python не был в списке непрозрачных, и граница проходила."""
    command = f'python -c "open(r\'{tmp_path.parent}\\hack.txt\',\'w\').write(\'x\')"'
    paths = _paths_in_command(command, tmp_path)
    assert paths, "python -c с абсолютным путём не замечен"


def test_powershell_ловится(tmp_path: Path) -> None:
    paths = _paths_in_command(
        f'powershell Set-Content {tmp_path.parent}\\ps1.txt "x"', tmp_path)
    assert paths


def test_переменная_окружения_ловится(tmp_path: Path) -> None:
    paths = _paths_in_command('echo hi > "%USERPROFILE%\\x.txt"', tmp_path)
    assert paths, "подстановка переменной окружения не замечена"


def test_команда_внутри_воркспейса_не_тревожит(tmp_path: Path) -> None:
    """Ложных тревог быть не должно: обычная работа идёт без вопросов."""
    assert _paths_in_command("python -m pytest -q", tmp_path) == []
    assert _paths_in_command("dir", tmp_path) == []
    assert _paths_in_command("echo готово", tmp_path) == []
    assert _paths_in_command("git status", tmp_path) == []
    assert _paths_in_command("npm run build", tmp_path) == []
    assert _paths_in_command("mkdir подпапка/глубже", tmp_path) == []
    assert _paths_in_command('python -c "print(1)"', tmp_path) == []


def test_путь_вверх_ловится(tmp_path: Path) -> None:
    """`..` не абсолютный путь, но уводит за границу воркспейса."""
    paths = _paths_in_command(r"del ..\..\..\Windows\System32\config", tmp_path)
    assert paths, "путь вверх через .. не замечен"
    assert not all(str(tmp_path).lower() in p.lower() for p in paths), paths


def test_жёсткая_граница_блокирует_путь_вверх(tmp_path: Path) -> None:
    victim = tmp_path.parent.parent / "не_тронь.txt"
    victim.write_text("данные", encoding="utf-8")
    guard = guard_for(tmp_path, AccessLevel.FULL, soft=False)
    rel = "..\\..\\" + victim.name
    res = run_tool("run_shell", guard, command=f'del "{rel}"')
    assert res.ok is False
    assert victim.exists(), "путь вверх обошёл границу"


def test_жёсткая_граница_блокирует_del(tmp_path: Path) -> None:
    """Сценарий из аудита: файл вне воркспейса не удаляется."""
    victim = tmp_path.parent / "не_тронь.txt"
    victim.write_text("данные", encoding="utf-8")
    guard = guard_for(tmp_path, AccessLevel.FULL, soft=False)
    res = run_tool("run_shell", guard, command=f'del "{victim}"')
    assert res.ok is False
    assert victim.exists(), "файл вне воркспейса удалён при жёсткой границе"


def test_жёсткая_граница_блокирует_перенаправление(tmp_path: Path) -> None:
    outside = tmp_path.parent / "dump.txt"
    guard = guard_for(tmp_path, AccessLevel.FULL, soft=False)
    res = run_tool("run_shell", guard, command=f'echo данные > "{outside}"')
    assert res.ok is False
    assert not outside.exists()