"""Инструменты, которые не могли выполниться никогда (аудит 1.1 и 1.2).

`run_tool` безусловно передаёт `base` каждому инструменту, и инструменты без
такого параметра в подписи падали с `TypeError`, который гасился общим
обработчиком и превращался в «неверные аргументы» — вечную ошибку, из-за
которой агент тратил шаги, не понимая причины. Vision-конвейер был мёртв.

Дополнительно проверяется `delete_path(".")`: список `protected` смотрит на
строку пути, а не на содержимое каталога, поэтому удаление корня воркспейса
проходило мимо защиты и сносило `.git` вместе с `.venv`.
"""

from __future__ import annotations

import inspect
import shutil
import sys
from pathlib import Path

import pytest

from hub.autonomy import AccessLevel, Autonomy, Guard
from hub.tools import TOOLS, _split_command, image_to_data_url, run_tool

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63f8cfc0000003010100"
    "18dd8db00000000049454e44ae426082"
)

PY = shutil.which("python") or shutil.which("python3") or sys.executable


def guard_for(root: Path) -> Guard:
    return Guard(access=AccessLevel.FULL, autonomy=Autonomy.NORMAL,
                 workspace_root=root.resolve())


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    work = tmp_path / "ворк"
    (work / ".git").mkdir(parents=True)
    (work / ".git" / "config").write_text("x", encoding="utf-8")
    (work / "файл.txt").write_text("данные", encoding="utf-8")
    (work / "папка").mkdir()
    return work


# =============================================================== 1.1 base


def test_base_есть_у_инструментов_с_файлами() -> None:
    """Инструмент над файлами обязан знать, от какой папки считать пути."""
    from hub.tools import WEB_TOOLS

    missing = []
    for name, spec in sorted(TOOLS.items()):
        if name in WEB_TOOLS:
            continue
        params = inspect.signature(spec["fn"]).parameters
        accepts_var = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if "base" not in params and not accepts_var:
            missing.append(name)
    assert not missing, f"нет параметра base: {', '.join(missing)}"


def test_run_tool_передаёт_base_только_нужным() -> None:
    """Инструменты без `base` тоже должны работать.

    Раньше `base` подставлялся всем подряд, и инструмент, которому он не
    нужен, падал с «неверные аргументы» — то есть был недоступен в принципе.
    """
    from hub.tools import _takes_base

    assert _takes_base(TOOLS["read_file"]["fn"]) is True
    assert _takes_base(TOOLS["web_fetch"]["fn"]) is False

    result = run_tool("web_fetch", guard_for(Path.cwd()), url="http://127.0.0.1/x")
    assert "неверные аргументы" not in (result.error or "").lower(), result.error


def test_run_shell_выполняется(tmp_path: Path) -> None:
    res = run_tool("run_shell", guard_for(tmp_path),
                   command=f"{PY} -c \"print(1+1)\"")
    assert res.ok, res.error
    assert "2" in (res.data or {}).get("stdout", "")


def test_run_shell_идёт_от_воркспейса(tmp_path: Path) -> None:
    """cwd по умолчанию — корень воркспейса, а не каталог запуска процесса."""
    res = run_tool("run_shell", guard_for(tmp_path),
                   command=f"{PY} -c \"open('проба.txt','w').write('x')\"")
    assert res.ok, res.error
    assert (tmp_path / "проба.txt").exists(), "команда выполнилась не в воркспейсе"


def test_кавычки_не_попадают_в_аргумент(tmp_path: Path) -> None:
    """Раньше кавычки уходили в аргумент, и код молча не исполнялся."""
    res = run_tool("run_shell", guard_for(tmp_path),
                   command=f"{PY} -c \"print('из-кавычек')\"")
    assert res.ok, res.error
    assert "из-кавычек" in (res.data or {}).get("stdout", "")


def test_путь_с_пробелом(tmp_path: Path) -> None:
    res = run_tool("run_shell", guard_for(tmp_path),
                   command=f"{PY} -c \"open('имя файла.txt','w').write('x')\"")
    assert res.ok, res.error
    assert (tmp_path / "имя файла.txt").exists()


def test_встроенные_команды_windows() -> None:
    """`dir` и `echo` не программы: на Windows их выполняет только cmd."""
    from hub.tools import WINDOWS_BUILTINS

    assert {"dir", "echo", "type", "md", "del", "copy"} <= WINDOWS_BUILTINS
    if not sys.platform.startswith("win"):
        pytest.skip("проверка для Windows")
    for command in ("echo привет", "ver"):
        res = run_tool("run_shell", guard_for(Path.cwd()), command=command)
        assert res.ok, f"{command!r}: {res.error}"
    res = run_tool("run_shell", guard_for(Path.cwd()), command="echo привет")
    assert "привет" in (res.data or {}).get("stdout", ""), "вывод потерян"


def test_split_убирает_кавычки() -> None:
    assert _split_command('py -c "print(1)"') == ("py", ["-c", "print(1)"])
    assert _split_command("py  -V") == ("py", ["-V"])
    assert _split_command('py "путь с пробелом"') == ("py", ["путь с пробелом"])
    assert _split_command("") == ("", [])


def test_split_пустая_кавычка_не_теряет_аргумент() -> None:
    """`--flag=""` — это настоящий аргумент, а не мусор."""
    head, tail = _split_command('py --flag=""')
    assert tail == ["--flag="], tail


# =============================================================== кодировки вывода


def test_русский_вывод_не_портится(tmp_path: Path) -> None:
    """cmd.exe пишет в OEM-866, а не в UTF-8: русский текст должен читаться.

    При чтении как utf-8 `echo привет` возвращал иероглифы, и агент получал
    «вывод команды», в котором нет ни одного узнаваемого слова.
    """
    if not sys.platform.startswith("win"):
        pytest.skip("проверка для Windows")
    res = run_tool("run_shell", guard_for(tmp_path), command="echo привет")
    assert res.ok, res.error
    assert "привет" in (res.data or {}).get("stdout", "")


def test_вывод_utf8_читается_как_utf8(tmp_path: Path) -> None:
    """Python пишет в UTF-8, и разбор не должен ломать его вывод."""
    res = run_tool("run_shell", guard_for(tmp_path),
                   command=f"{PY} -c \"print('из-кавычек')\"")
    assert res.ok, res.error
    assert "из-кавычек" in (res.data or {}).get("stdout", "")


def test_разбор_пустого_вывода() -> None:
    from hub.tools import _decode_output

    assert _decode_output(None, "cp866") == ""
    assert _decode_output(b"", "cp866") == ""


def test_разбор_берёт_oem_когда_utf8_невозможен() -> None:
    """Байты `echo привет` в OEM-866 не собираются в UTF-8 — значит, это 866."""
    from hub.tools import _decode_output

    raw = "привет".encode("cp866")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert _decode_output(raw, "cp866") == "привет"


# =============================================================== vision


def test_image_to_data_url_работает(tmp_path: Path) -> None:
    (tmp_path / "точка.png").write_bytes(PNG)
    res = run_tool("image_to_data_url", guard_for(tmp_path), path="точка.png")
    assert res.ok, res.error
    # data — сам data-URL строкой, а не словарём: так его и читает агент.
    assert str(res.data).startswith("data:image/png;base64,")


def test_image_относительный_путь(tmp_path: Path) -> None:
    (tmp_path / "точка.png").write_bytes(PNG)
    res = run_tool("image_to_data_url", guard_for(tmp_path), path="точка.png")
    assert res.ok, res.error


def test_image_прямой_вызов_без_base(tmp_path: Path) -> None:
    """base необязателен: инструмент можно звать и напрямую."""
    target = tmp_path / "нет.png"
    res = image_to_data_url(str(target))
    assert res.ok is False
    assert "не найдена" in res.error


# =============================================================== 1.2 удаление себя


def test_нельзя_удалить_корень_воркспейса(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path=".", recursive=True)
    assert res.ok is False, "воркспейс удалён, а инструмент отчитался успехом"
    assert ws.exists()
    assert (ws / "файл.txt").exists()


def test_нельзя_удалить_корень_через_двойную_точку(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path="./", recursive=True)
    assert res.ok is False
    assert ws.exists()


def test_нельзя_удалить_родителя_воркспейса(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path="..", recursive=True)
    assert res.ok is False
    assert ws.exists()


def test_нельзя_удалить_абсолютный_корень(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path=str(ws), recursive=True)
    assert res.ok is False
    assert ws.exists()


def test_обычное_удаление_работает(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path="файл.txt")
    assert res.ok, res.error
    assert not (ws / "файл.txt").exists()
    assert (ws / ".git" / "config").exists(), "проверка идёт не по той причине"


def test_удаление_подкаталога_работает(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path="папка", recursive=True)
    assert res.ok, res.error
    assert not (ws / "папка").exists()


def test_сообщение_объясняет_отказ(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path=".", recursive=True)
    assert "воркспейс" in res.error.lower() or "родител" in res.error.lower()


def test_удаление_несуществующего_не_считается_самоубийством(ws: Path) -> None:
    res = run_tool("delete_path", guard_for(ws), path="нет-такого.txt")
    assert res.ok is False
    assert "воркспейс" not in res.error.lower()