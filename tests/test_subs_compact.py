"""Части не должны съедать окно переписки."""

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


def subs_css() -> str:
    block = css()
    start = block.index(".subsBox {")
    return block[start:block.index(".subsMore.on")]


def test_панель_частей_ограничена_по_высоте() -> None:
    assert "max-height" in subs_css(), "без предела панель занимает всё окно"


def test_предел_меньше_половины_окна() -> None:
    """30vh вместо 42: переписка и поле ввода должны быть видны всегда."""
    block = subs_css()
    assert "30vh" in block, "панель снова слишком высокая"


def test_завершённая_часть_сворачивается_сама() -> None:
    """Главное: десять развёрнутых карточек и есть проблема со скриншота."""
    assert ".subCard.folded .subWhy" in css()
    assert ".subCard.folded .subFiles" in css()
    assert "function subLooksDone(" in script()


def test_развёрнуты_не_больше_трёх() -> None:
    """Одиннадцать частей в состоянии «думает» закрывали переписку целиком.

    Раньше сворачивались только завершённые части, а работающих всегда
    больше — значит на практике не сворачивалось ничего.
    """
    body = script()
    # Именно три: одиннадцать рабочих частей закрывали переписку,
    # и одна-три развёрнутые её не закрывают.
    assert "SUBS_OPEN_MAX = 3;" in body, "предел развёрнутых должен быть 3"
    assert "function subsApplyLimit(" in body
    limit = body[body.index("function subsApplyLimit("):][:1200]
    assert "kept < SUBS_OPEN_MAX" in limit
    assert "foldSub(sub, true)" in limit, "лимит ничего не сворачивает"


def test_лимит_не_трогает_то_что_открыл_человек() -> None:
    body = script()
    fold = body[body.index("function foldSub("):][:600]
    assert "if (folded && item.userOpened) return" in fold
    limit = body[body.index("function subsApplyLimit("):][:1200]
    assert "item.userOpened" in limit


def test_свежесть_части_отмечается() -> None:
    """По меткам «обновлено сейчас» выбираются те три, что развёрнуты."""
    body = script()
    live = body[body.index("function subLiveStat("):]
    live = live[:live.index("\n}")]
    assert "item.touched = Date.now()" in live
    assert "subsApplyLimit()" in live


def test_развернуть_все_помечает_открытыми() -> None:
    """Иначе лимит тут же сложил бы их обратно на следующем событии."""
    body = script()
    toggle = body[body.index("function subsToggleAll("):][:900]
    assert "SUBS[sub].userOpened = true" in toggle


def test_человека_не_сворачивают_против_желания() -> None:
    """Если он раскрыл след вручную, автосворачивание не мешает."""
    body = script()
    toggle = body[body.index("function toggleSub("):][:900]
    assert "userOpened = true" in toggle
    fold = body[body.index("function foldSub("):][:600]
    assert "userOpened" in fold


def test_свернуть_и_развернуть_все() -> None:
    """Одно движение вместо десяти щелчков."""
    assert "function subsToggleAll(" in script()
    assert "свернуть все" in UI_HTML
    assert "развернуть все" in UI_HTML


def test_кнопки_над_списком_а_не_внутри() -> None:
    """Внутри прокручиваемого списка они уехали бы вниз вместе с карточками."""
    assert 'class="subsTools"' in UI_HTML
    block = css()
    assert ".subsTools {" in block


def test_кнопка_вниз_осталась() -> None:
    """Прежнее требование не должно сломаться от новой правки."""
    assert "subsScrollToEnd" in UI_HTML
    assert "function subsFollow(" in script()