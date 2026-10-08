"""Правая панель: одно колесо на весь проект + читаемый локальный чат."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.ui import UI_HTML  # noqa: E402


def css() -> str:
    return (ROOT / "hub" / "ui.py").read_text(encoding="utf-8").partition("</style>")[0]


def script() -> str:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    _, _, rest = src.partition("</style>")
    return rest.partition("<script>")[2].partition("</script>")[0]


def panel_markup() -> str:
    start = UI_HTML.index('id="p-files"')
    return UI_HTML[start - 120:start + 400]


# ======================================================== правая панель


def test_у_панели_одна_прокрутка() -> None:
    """Два колеса в одной панели - причина «не могу прокрутить ниже»."""
    markup = panel_markup()
    assert 'id="p-files" style="overflow:auto"' in markup, (
        "панель должна прокручиваться целиком")
    assert "flex:0 0 46%" not in markup, "дерево снова зажато по высоте"


def test_у_дерева_нет_своей_прокрутки() -> None:
    """Иначе колесо крутит только дерево, а не всю панель."""
    markup = panel_markup()
    start = markup.index('id="ftree"')
    assert "overflow:auto" not in markup[start:start + 120], (
        "у дерева осталась своя прокрутка")


def test_у_просмотра_файла_нет_своей_прокрутки() -> None:
    markup = panel_markup()
    start = markup.index('id="fview"')
    assert "overflow:auto" not in markup[start:start + 120]


def test_в_коде_нет_жёсткой_доли_высоты() -> None:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    assert "flex:0 0 46%" not in src, "дерево снова ограничено долей панели"


def test_граница_между_древом_и_файлом_осталась() -> None:
    """Разделитель помогает понять, где кончается дерево."""
    markup = panel_markup()
    start = markup.index('id="ftree"')
    assert "border-bottom" in markup[start:start + 160]


def test_шапка_панели_осталась_вне_прокрутки() -> None:
    """Кнопки обновления и перехода не должны уезжать вниз."""
    assert markup_head() < UI_HTML.index('id="p-files"')


def markup_head() -> int:
    return UI_HTML.index('class="phead"', UI_HTML.index('id="right"'))


# ============================================== читаемый локальный чат


def test_пузырь_берёт_цвета_из_токенов() -> None:
    """Раньше были вбиты свои: тёмный текст по тёмному, читалось выделением."""
    block = css()[css().index(".lb {"):css().index(".lb.user")]
    assert "var(--text)" in block
    assert "var(--panel2)" in block


def test_в_пузырях_нет_своих_цветов() -> None:
    body = script()
    bubble = body[body.index("function localBubble("):][:600]
    assert "#2563eb" not in bubble, "цвет вопроса снова вбит"
    assert "#1b1f28" not in bubble, "цвет ответа снова вбит"


def test_пузырь_не_надевает_классы_основной_переписки() -> None:
    """Классы msg тянут за собой тёмный фон и снова гасят текст."""
    bubble = script()
    bubble = bubble[bubble.index("function localBubble("):][:600]
    assert "'lb '" in bubble
    assert "msg assistant" not in bubble


def test_вопрос_читаем_во_всех_темах() -> None:
    block = css()[css().index(".lb.user"):css().index(".lb.bot")]
    assert "var(--accent)" in block
    assert "var(--accent-text)" in block


def test_ответ_читаем_во_всех_темах() -> None:
    block = css()[css().index(".lb.bot"):css().index(".lb.bot") + 120]
    assert "var(--text)" in block