"""zagent.bat: аргументы доходят до подпрограмм.

`SHIFT` двигает `%0`–`%9`, но никогда `%*`. Из-за этого каждая ветка,
передающая `%*`, заново отдавала имя команды первым аргументом в argparse:
`zagent.bat ask "вопрос"` превращался в `agent.py ask ask "вопрос"`.

Девять команд из пятнадцати были сломаны, а двойной клик работал — он идёт
без аргументов. Поэтому поломку и не видели: проверяли ровно тот путь,
который был единственным целым.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BAT = ROOT / "zagent.bat"

#: Ветки, передающие аргументы дальше. Для каждой — что должно вызваться.
FORWARDING = {
    "ui": ("tools\\serve.py",),
    "ask": ("tools\\agent.py", "ask"),
    "agent": ("tools\\agent.py",),
    "sanity": ("tools\\agent.py", "sanity"),
    "consult": ("tools\\agent.py", "consult"),
    "connect": ("tools\\connect_guide.py",),
    "export": ("tools\\cli.py", "export"),
    "geo": ("tools\\geo.py",),
    "ws": ("tools\\workspace.py",),
    "bench": ("tools\\bench.py",),
}


def read_bat() -> str:
    return BAT.read_text(encoding="utf-8", errors="replace")


def branch_body(text: str, label: str) -> str:
    """Текст ветки от метки до следующей метки."""
    match = re.search(
        rf"^:{label}\b(.*?)(?=^:[a-z]|\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"метка :{label} не найдена"
    return match.group(1)


@pytest.fixture(scope="module")
def bat() -> str:
    return read_bat()


# =============================================================== shift


def test_star_не_используется_нигде(bat: str) -> None:
    """`%*` здесь и есть корень поломки: SHIFT на него не действует."""
    offenders = [
        (n, line.strip())
        for n, line in enumerate(bat.splitlines(), start=1)
        if "%*" in line and not line.strip().upper().startswith("REM")
    ]
    assert not offenders, f"%* ещё используется: {offenders}"


def test_хвост_аргументов_собирается(bat: str) -> None:
    """Хвост собирается циклом со SHIFT — иначе команда уходит в подпарсер."""
    assert "set \"REST=" in bat
    assert ":collectargs" in bat
    assert ":argsready" in bat
    # Сдвиг обязан быть внутри цикла, иначе цикл не продвигается.
    assert re.search(r":collectargs.*?shift.*?:collectargs", bat, re.DOTALL)


def test_команда_берётся_до_сдвига(bat: str) -> None:
    """Имя команды нужно снять первым, до того как хвост начнёт собираться."""
    cmd_at = bat.index('set "CMD=%~1"')
    collect_at = bat.index(":collectargs")
    assert cmd_at < collect_at, "CMD должен задаваться до сбора аргументов"


# =============================================================== ветки


@pytest.mark.parametrize("label,expected", sorted(FORWARDING.items()))
def test_ветка_передаёт_rest(bat: str, label: str, expected: tuple[str, ...]) -> None:
    body = branch_body(bat, label)
    for needle in expected:
        assert needle in body, f":{label} не вызывает {needle}"
    assert "%REST%" in body, f":{label} не передаёт собранные аргументы"


def test_bench_берёт_первый_аргумент(bat: str) -> None:
    """Имя команды уже снято сдвигом, ветка должна смотреть на собранный хвост.

    Раньше здесь стоял `if "%~2"==""`: после shift имя команды ушло из
    %1, и проверка пустоты смотрела на чужую позицию. Сейчас аргументы
    собраны в %REST% циклом :collectargs, и emptiness проверяется именно
    по нему — так же, как во всех остальных ветках.
    """
    body = branch_body(bat, "bench")
    assert 'if "%REST%"==""' in body, "проверка пустоты должна смотреть на %REST%"
    assert "%~2" not in bat, "сдвиг уже снял имя команды, %~2 смотрит не туда"
    assert "%REST% %REST%" not in bat, "хвост не должен удваиваться при передаче"


# =============================================================== install


def test_install_передаёт_код_ошибки(bat: str) -> None:
    """Обе ошибки pip раньше проглатывались, и bat печатал «Готово»."""
    body = branch_body(bat, "install")
    assert body.count("if errorlevel 1 exit /b 1") >= 2, (
        "каждая установка pip обязана проверяться"
    )


def test_вызовы_install_проверяют_результат(bat: str) -> None:
    body = read_bat()
    for match in re.finditer(r"call :install", body):
        tail = body[match.end():match.end() + 200]
        assert "if errorlevel 1" in tail, (
            f"call :install не проверяется: {tail[:80]!r}"
        )


# =============================================================== живая проверка


@pytest.mark.skipif(not BAT.exists(), reason="нет zagent.bat")
def test_справка_работает() -> None:
    """Команда без сетевых обращений — на ней и проверяем разбор аргументов.

    Вывод читается как есть, без перекодировки: bat принудительно ставит
    `chcp 65001`, поэтому байты UTF-8, и любая догадка про кодовую страницу
    здесь превращала бы верный вывод в мусор.
    """
    env = {"ZAGENT_NO_PAUSE": "1", "PATH": _environ_path()}
    done = subprocess.run(
        ["cmd", "/c", str(BAT), "help"], capture_output=True,
        cwd=ROOT, env=env, timeout=120, check=False,
    )
    out = (done.stdout or b"").decode("utf-8", errors="replace")
    err = (done.stderr or b"").decode("utf-8", errors="replace")
    assert done.returncode == 0, out[-500:] + err[-500:]
    assert "zagent - команды" in out, out[:300]
    assert err.strip() == "", f"cmd что-то писала в stderr: {err[:200]}"


def test_файл_в_crlf() -> None:
    """cmd.exe читает batch-файл построчно по CRLF.

    При одиночных LF русский текст внутри `echo` частично попадает в разбор
    как команда: от «Панель» остаётся «нель», и cmd сообщает
    `'нель' is not recognized`. Вывод при этом выглядит почти правильным,
    и поломку легко пропустить.
    """
    raw = BAT.read_bytes()
    crlf = raw.count(b"\r\n")
    lone = raw.count(b"\n") - crlf
    assert lone == 0, f"одиночных LF: {lone} (CRLF: {crlf})"


def test_кодировка_консоли_переключается() -> None:
    """Без `chcp 65001` весь русский текст bat превращается в кашу."""
    text = BAT.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:8])
    assert "chcp 65001" in head, "chcp обязан идти до первого echo"


def _environ_path() -> str:
    """PATH для дочернего cmd.

    Отдельная функция с подчёркиванием: pytest собирает всё, что начинается
    с `test`, — вспомогательная функция иначе превратилась бы в тест.
    """
    import os

    return os.environ.get("PATH", "")