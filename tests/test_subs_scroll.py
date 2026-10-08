"""Панель частей: автопрокрутка и уважение к прокрутке человека."""

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


def test_контейнер_прокручивается() -> None:
    """Без прокрутки десять частей не помещались и уезжали под поле ввода."""
    block = css()[css().index(".subsBox {"):css().index(".subsBox:empty")]
    assert "overflow-y: auto" in block
    assert "max-height" in block, "без предела по высоте панель тянет страницу"


def test_высота_ограничена_разумно() -> None:
    """Пол-экрана максимум: выше - панель съедает переписку."""
    block = css()[css().index(".subsBox {"):css().index(".subsBox:empty")]
    assert "vh" in block, "предел должен быть в долях экрана"


def follow_body() -> str:
    """Тело subsFollow — чтобы проверять условие, а не наличие функции."""
    body = script()
    start = body.index("function subsFollow(")
    end = body.index("\n}", start) + 2
    return body[start:end]


def test_автопрокрутка_вниз_есть() -> None:
    body = script()
    assert "function subsFollow(" in body
    assert "box.scrollTop = box.scrollHeight" in body
    # Прокрутка обязана происходить ВНУТРИ условия, а не безусловно после
    # него: иначе проверка «уважает человека» врёт, а список прыгает.
    assert "if (force || subsAtBottom(box)) {" in follow_body(), (
        "прокрутка не под условием - список будет прыгать под курсором")
    inner = follow_body()
    assert inner.index("if (force || subsAtBottom(box))") < inner.index(
        "box.scrollTop = box.scrollHeight")


def test_прокрутка_уважает_человека() -> None:
    """Если человек ушёл вверх, список не должен прыгать под курсором."""
    body = script()
    assert "function subsAtBottom(" in body
    condition = next(line for line in follow_body().splitlines()
                     if "if (" in line and "subsAtBottom" in line)
    assert "subsAtBottom(box)" in condition, (
        f"условие не спрашивает про положение списка: {condition}")
    assert "force || subsAtBottom(box)" in condition


def test_порог_вниз_не_строгий() -> None:
    """Крайние 48 пикселей считаем «вниз»: иначе список замирает."""
    body = script()
    assert "48" in body.split("function subsAtBottom")[1][:300]


def test_новое_состояние_запоминается_до_вставки() -> None:
    """После вставки «был ли внизу» уже не определить — длина изменилась."""
    body = script()
    ensure = body[body.index("function ensureSub("):][:1200]
    assert "wasBottom" in ensure
    assert ensure.index("wasBottom") < ensure.index("insertAdjacentHTML")


def test_новый_шаг_тоже_дотягивает_вниз() -> None:
    body = script()
    start = body.index("function subLiveStat(")
    end = body.index("\n}", start) + 2
    live = body[start:end]
    assert "subsFollow" in live, "шаг мог вырасти в блок и уехать вниз"


def test_кнопка_вниз_есть_и_вне_списка() -> None:
    """Кнопка внутри прокручиваемого списка уехала бы вниз вместе с ним."""
    assert 'class="subsMore"' in UI_HTML
    assert "subsScrollToEnd" in UI_HTML
    block = css()[css().index(".subsMore {"):css().index(".subsMore.on")]
    assert "position: sticky" in block or "position:sticky" in block


def test_кнопка_показывается_когда_список_длиннее() -> None:
    body = script()
    assert "more.classList.toggle('on'" in body


def test_прокрутка_отслеживается() -> None:
    """Событие scroll нужно один раз, а не на каждую карточку."""
    body = script()
    watch = body[body.index("function subsWatchScroll("):][:500]
    assert "box.dataset.watch" in watch, "слушатель будет навешен много раз"
    assert "addEventListener('scroll'" in watch