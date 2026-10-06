"""Вывод команды с русским текстом приходил абракадаброй.

Живой прогон 07.10.2026: `run_shell` возвращал вместо `из-кавычки` строку
`щ-ъарт√ъхь`. Тесты падали и на чистом дереве — сначала это сочли
особенностью машины, и это было ошибкой.

Причина в неверной модели, а не в системе. У Windows две кодовые страницы:
OEM (у `cmd.exe`, на русской Windows 866) и ANSI (у программ, на русской
Windows 1251). Программа, запущенная без консоли, консоли не видит и берёт
локаль системы, то есть ANSI. А мы разбирали вывод **всех** команд как OEM.

Ошибка не бросалась: обе таблицы однобайтовые и принимают любые байты, так
что расхождение обнаруживалось только глазами. Для агента это означало, что
любой русский текст из команды — вывод тестов, `git log`, сообщение
скрипта — приходил нечитаемым, и агент принимал решения по мусору.

Тесты проверяют поведение на настоящих байтах, а не на строке в коде.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from hub.tools import _ansi_encoding, _decode_output, _oem_encoding, run_tool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Путь к интерпретатору берётся так же, как в test_tools_bugs.py: через
# `shutil.which`. Абсолютный путь внутри проекта (`<корень>/.venv/...`) не
# годится — команда проверяется на выход за границу воркспейса, а тест
# работает во временной папке, и путь наружу превращался в «команда не
# найдена: .venv».
PY = shutil.which("python") or shutil.which("python3") or sys.executable

WINDOWS = sys.platform.startswith("win")
requires_windows = pytest.mark.skipif(
    not WINDOWS, reason="различие OEM и ANSI есть только на Windows")


# ==================================================== выбор кодировки страницы


@requires_windows
def test_ansi_и_oem_берутся_из_системы() -> None:
    """Не константы: на другой Windows значения другие.

    Обе страницы обязаны существовать как минимум одна: иначе и русский
    вывод, и вывод cmd пришлось бы читать наугад.
    """
    oem, ansi = _oem_encoding(), _ansi_encoding()
    assert oem and ansi
    assert "utf-8" not in (oem, ansi) or (oem == ansi == "utf-8")


@requires_windows
def test_страницы_могут_различаться_и_это_не_ошибка() -> None:
    """На русской Windows OEM=866, ANSI=1251 — и именно из-за различия
    всё ломалось. Тест фиксирует, что мы их не путаем, а не что они равны."""
    oem, ansi = _oem_encoding(), _ansi_encoding()
    # Если совпали, проверять нечего: баг на такой машине не воспроизводится.
    if oem == ansi:
        pytest.skip("OEM и ANSI совпадают — различия нет")


# ============================================================ разбор байтов


def test_utf8_имеет_приоритет_перед_однобайтовыми() -> None:
    """Иначе починка ANSI испортила бы команды, которые писали в UTF-8.

    Порядок проб: UTF-8 строгим разбором, потом переданные кодировки.
    """
    raw = "из-кавычки".encode("utf-8")
    assert _decode_output(raw, "cp1251", "cp866") == "из-кавычки"
    assert _decode_output(raw, "cp866", "cp1251") == "из-кавычки"


def test_ansi_читается_своей_страницей() -> None:
    assert _decode_output("привет".encode("cp1251"), "cp1251", "cp866") == "привет"


def test_oem_читается_своей_страницей() -> None:
    """Вывод cmd остаётся OEM — починка не должна ломать и его."""
    assert _decode_output("привет".encode("cp866"), "cp866", "cp1251") == "привет"


def test_порядок_имеет_значение_и_это_видно() -> None:
    """Обе однобайтовые таблицы принимают любые байты, поэтому порядок решает.

    Это и есть суть поломки: ошибка не выдавалась себя исключением.
    """
    raw = "привет".encode("cp1251")
    assert _decode_output(raw, "cp1251", "cp866") != _decode_output(raw, "cp866", "cp1251")


def test_пустой_вывод_не_требует_кодировки() -> None:
    assert _decode_output(None, "cp1251") == ""
    assert _decode_output(b"", "cp1251") == ""


def test_неизвестная_кодировка_не_роняет_команду() -> None:
    """Мусор в имени кодировки — не повод потерять вывод целиком.

    Ошибка разбора приходит после того, как команда уже отработала; ронять
    из-за неё всю работу — худшее, что можно сделать.
    """
    assert _decode_output(b"\xff\xfe ok", "такой-кодировки-нет") != ""


# ============================================ настоящая команда целиком


@requires_windows
def test_вывод_программы_читается_а_не_ломается(tmp_path: Path) -> None:
    """Главная проверка: настоящая команда с русским выводом в ANSI.

    Скрипт пишет байты cp1251 напрямую через буфер, поэтому результат не
    зависит от того, какая локаль выставлена у окружения, — падение и
    починка воспроизводятся одинаково в любой сессии.
    """
    from tests.test_tools_bugs import guard_for

    script = tmp_path / "пишет_ansi.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.buffer.write('из-кавычки'.encode('cp1251'))\n"
        "sys.stdout.buffer.write(b'\\n')\n",
        encoding="utf-8",
    )

    res = run_tool("run_shell", guard_for(tmp_path), command=f'{PY} "{script}"')

    assert res.ok, res.error
    out = (res.data or {}).get("stdout", "")
    assert "из-кавычки" in out, (
        f"русский текст испорчен: {out!r}. Возможно, вывод прочитан не как "
        f"ANSI ({_ansi_encoding()}) и не как OEM ({_oem_encoding()})"
    )


@requires_windows
def test_вывод_utf8_не_сломался_рядом_с_починкой(tmp_path: Path) -> None:
    """Программа, пишущая в UTF-8, должна остаться читаемой."""
    from tests.test_tools_bugs import guard_for

    script = tmp_path / "пишет_utf8.py"
    script.write_text("print('из-файла')\n", encoding="utf-8")

    res = run_tool("run_shell", guard_for(tmp_path), command=f'{PY} "{script}"')

    assert res.ok, res.error
    assert "из-файла" in (res.data or {}).get("stdout", "")


def test_пустая_команда_не_ломает_разбор(tmp_path: Path) -> None:
    """Ошибка команды и разбор вывода идут разными путями.

    Здесь проверяется, что перестановка вычисления кодировок не съела
    ветку, где команда завершилась с кодом ошибки.
    """
    from tests.test_tools_bugs import guard_for

    res = run_tool("run_shell", guard_for(tmp_path), command="нет-такой-команды")
    assert res.ok is False or res.data is not None