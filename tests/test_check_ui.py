"""Проверка самого check_ui: ловит ли он поломки, которые уже случались.

Каждая поломка из истории повторена здесь в уменьшенном виде. Разбор отдан
node, поэтому тесты требуют node — иначе проверка не отличила бы поломку от
рабочего кода.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# `tools` в `sys.path` не добавляется намеренно. Каталог содержит `bench.py`,
# и после добавления `import bench` начал находить `tools/bench.py` вместо
# пакета `bench/`: тот файл импортирует сам себя, и сборка тестов падала с
# «circular import» — но только если check_ui проверялся раньше bench.
# Порядок коллекции не должен решать, работают ли тесты.
_spec = importlib.util.spec_from_file_location(
    "zagent_check_ui", ROOT / "tools" / "check_ui.py"
)
assert _spec and _spec.loader
check_ui = importlib.util.module_from_spec(_spec)
sys.modules["zagent_check_ui"] = check_ui
_spec.loader.exec_module(check_ui)

check_js_syntax = check_ui.check_js_syntax
node_available = check_ui.node_available

TICK = "`"

needs_node = pytest.mark.skipif(
    not node_available(), reason="node не установлен: разбор отдан ему"
)


def code(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# =============================================================== что ловим


@needs_node
def test_нормальный_скрипт() -> None:
    src = code(
        "function f(a) {",
        "  const s = " + TICK + "hi ${a} there" + TICK + ";",
        "  return {a: s};",
        "}",
    )
    assert check_js_syntax(src) == ""


@needs_node
def test_лишняя_скобка() -> None:
    err = check_js_syntax(code("function f() {", "  return 1;", "}}"))
    assert "}" in err, err


@needs_node
def test_не_хватает_скобки() -> None:
    err = check_js_syntax(code("function f() {", "  return 1;"))
    assert err, "незакрытая функция обязана быть замечена"


@needs_node
def test_незакрытая_обратная_кавычка() -> None:
    """Ровно та поломка, что выключила весь скрипт в браузере.

    Шаблонная строка тянется до следующей кавычки через пол-экрана кода,
    синтаксис после неё перестаёт существовать — и проверка обязана сказать
    об этом, а не отчитаться «скобки сошлись».
    """
    src = code(
        "const s = " + TICK + "начало",
        "  + 'ещё строка'",
        "  + 'и третья';",
        "function f() { return 1; }",
        "const t = " + TICK + "закрыто" + TICK + ";",
    )
    assert check_js_syntax(src), "незакрытая кавычка прошла незамеченной"


@needs_node
def test_незакрытая_обычная_кавычка() -> None:
    assert check_js_syntax(code('const s = "начало', "function f() { return 1; }"))


@needs_node
def test_вложенный_шаблон_в_интерполяции() -> None:
    """Конструкция, на которой свой парсер и объявлял поломку."""
    src = code(
        "const s = " + TICK + "${ " + TICK + "вложенный ${1}" + TICK
        + " } конец" + TICK + ";",
        "function f() { return 1; }",
    )
    assert check_js_syntax(src) == "", "рабочий код объявлен сломанным"


@needs_node
def test_интерполяция_с_условием_и_кавычками() -> None:
    """Ровно та строка из интерфейса, что сбивала парность скобок."""
    src = code(
        "function f(v) {",
        "  return "
        + TICK + '<div class="verify ${v.ok?\'\':\'bad\'}">'
        + "${v.ok?'ok':'no'}</div>" + TICK + ";",
        "}",
    )
    assert check_js_syntax(src) == "", "рабочий код объявлен сломанным"


@needs_node
def test_многострочный_текст_в_апострофах() -> None:
    src = code(
        "const hint = 'Лимит запросов'",
        "  + ' сброшен: попробуйте позже';",
        "function f() { return 1; }",
    )
    assert check_js_syntax(src) == ""


@needs_node
def test_скобки_в_строке_не_считаются() -> None:
    src = code("const s = '}{';", "function f() { return 1; }")
    assert check_js_syntax(src) == ""


@needs_node
def test_скобка_в_интерполяции() -> None:
    src = code(
        "const s = " + TICK + "a ${'{'}} b" + TICK + ";",
        "function f() { return 1; }",
    )
    assert check_js_syntax(src) == ""


@needs_node
def test_экранированная_кавычка_не_закрывает() -> None:
    src = code("const s = 'а \\' б';", "function f() { return 1; }")
    assert check_js_syntax(src) == ""


@needs_node
def test_пустой_скрипт() -> None:
    assert check_js_syntax("") == ""


@needs_node
def test_комментарий_в_строке_не_комментарий() -> None:
    src = code("const s = 'http://example.test // путь';", "function f() {}")
    assert check_js_syntax(src) == ""


@needs_node
def test_незакрытый_блоковый_комментарий() -> None:
    assert check_js_syntax(code("/* начало", "function f() {}"))


# =============================================================== боевой файл


@needs_node
def test_боевой_интерфейс_разбирается() -> None:
    """Настоящий скрипт из hub/ui.py обязан проходить проверку."""
    from hub.ui import UI_HTML

    # Скрипт в UI_HTML короткий: основной блок лежит в исходнике, а
    # UI_HTML собирается из куска после </style>. Проверяем именно то, что
    # реально отдаётся серверу.
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    _, _, rest = src.partition("</style>")
    main = rest.partition("<script>")[2].partition("</script>")[0]
    assert main.strip(), "скрипт не найден"
    assert len(main.splitlines()) > 100, "извлекся не тот кусок"
    err = check_js_syntax(main)
    assert err == "", f"скрипт интерфейса сломан: {err}"


@needs_node
def test_страница_собирается_целиком() -> None:
    """UI_HTML должен содержать разметку и оба блока скриптов."""
    from hub.ui import UI_HTML

    assert "<!doctype html>" in UI_HTML.lower()
    assert UI_HTML.count("<script>") >= 2, "часть скриптов потерялась"
    assert UI_HTML.count("</script>") == UI_HTML.count("<script>")


def test_запасная_проверка_молчит_о_строках() -> None:
    """Без node скобки проверяются грубо, и о незакрытой строке не врём.

    Раньше вместо молчания возвращалась строка «(проверка скобок без node:
    строки не разбирались)», а вызывающий считал любую непустую строку
    проблемой. Итог: на машине без node проверка интерфейса находила хотя
    бы одну проблему всегда, независимо от состояния интерфейса.
    """
    check_js_braces = check_ui.check_js_braces

    # Специально сломанная шаблонная строка: без node мы не знаем, что она
    # сломана, и молчим — но молчание должно быть пустой строкой, а не
    # «проблемой».
    src = code("const s = " + TICK + "начало", "function f() { return 1; }")
    out = check_js_braces(src)
    assert "скобки не сошлись" not in out
    assert out == "", f"молчание выдано за проблему: {out!r}"


def test_запасная_проверка_ловит_лишнюю_скобку() -> None:
    assert "лишняя" in check_ui.check_js_braces(
        code("function f() {", "  return 1;", "}}"))


# ==================================================== имена из Python в JS


def test_ловится_имя_из_python() -> None:
    """`KEY_RING.snapshot()` в JS падает с ReferenceError, а node молчит.

    Так в интерфейсе уже ломалось вычисление числа аккаунтов: `refresh()`
    ронял страницу, режимы выглядели нерабочими, и в консоли лежал
    ReferenceError, который никто не смотрел.
    """
    found = check_ui.python_names_in_js(
        code("function tune() {", "  const k = KEY_RING.snapshot();", "}"))
    assert "KEY_RING" in found


def test_комментарий_не_считается() -> None:
    """Имя в комментарии — это объяснение, а не обращение к переменной."""
    found = check_ui.python_names_in_js(
        code("// раньше было KEY_RING.snapshot()", "const x = 1;"))
    assert not found


def test_своя_константа_не_считается() -> None:
    found = check_ui.python_names_in_js(
        code("const TASK_FLAGS = {};", "function f() { return TASK_FLAGS; }"))
    assert not found


def test_обычный_js_чист() -> None:
    assert not check_ui.python_names_in_js(
        code("const MODES = {plain: 1};", "function f() { return Math.max(1, 2); }"))


def test_текущий_интерфейс_без_python_имён() -> None:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    _, _, rest = src.partition("</style>")
    main_script = rest.partition("<script>")[2].partition("</script>")[0]
    found = check_ui.python_names_in_js(main_script)
    assert not found, f"в браузерный скрипт попали имена Python: {found}"