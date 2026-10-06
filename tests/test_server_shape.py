"""hub/server.py не должен терять обработчики при правках.

Из-за неудачной вставки класс `Handler` разорвался на два: в первом остались
`do_GET` и `_stream`, во втором — все POST-обработчики. Программа при этом
импортировалась и даже отвечала на часть маршрутов, поэтому поломка прошла
незамеченной: маршруты `/api/events` и `/` просто переставали существовать.

Проверки ниже ловят именно эту форму повреждения.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "hub" / "server.py"

#: Обработчики, без которых программа не работает. Список — из роутов
#: do_POST/do_GET: если хоть один исчез, соответствующий маршрут мёртв.
REQUIRED_HANDLERS = {
    "do_GET", "do_POST", "_stream", "_json", "_html", "_error",
    "_reject", "_body", "_same_origin", "_write_event",
    "_scan", "_ping", "_ping_status", "_sanity", "_ask", "_mode",
    "_config", "_enqueue", "_region", "_sessions", "_answer", "_cancel",
    "_pause", "_shot", "_connect", "_permissions", "_workspaces",
    "_files", "_read_view_file",
}


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(SERVER.read_text(encoding="utf-8"))


def handler_classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "Handler"
    ]


def test_класс_один(tree: ast.Module) -> None:
    classes = handler_classes(tree)
    assert len(classes) == 1, (
        f"класс Handler разорван на {len(classes)} частей: "
        f"строки {[c.lineno for c in classes]}"
    )


def test_все_обработчики_на_месте(tree: ast.Module) -> None:
    classes = handler_classes(tree)
    assert classes, "класс Handler не найден"
    names = {
        item.name for item in classes[0].body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = REQUIRED_HANDLERS - names
    assert not missing, f"потеряны обработчики: {sorted(missing)}"


def test_роуты_указывают_на_существующие(tree: ast.Module) -> None:
    """Каждый маршрут должен вести в метод, который реально есть.

    Словарь роутов собирался из `self._...`; если метод исчезал, он
    подставлялся как `None` и маршрут молча отдавал 404.
    """
    classes = handler_classes(tree)
    names = {
        item.name for item in classes[0].body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for value in node.values:
                if (isinstance(value, ast.Attribute)
                        and isinstance(value.value, ast.Name)
                        and value.value.id == "self"):
                    used.add(value.attr)
    dangling = {name for name in used if name not in names and name != "api"}
    assert not dangling, f"роуты ссылаются на несуществующие методы: {sorted(dangling)}"


def test_нет_пустых_классов(tree: ast.Module) -> None:
    """`_PostMixin` с одним docstring — след неудачной вставки."""
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        methods = [
            item for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if node.name.startswith("_"):
            assert methods, f"класс {node.name} пуст — вероятный мусор"


def test_все_маршруты_объявлены() -> None:
    """Каждый путь из /api, который зовёт интерфейс, должен обрабатываться."""
    source = SERVER.read_text(encoding="utf-8")
    assert '"/api/events"' in source
    assert '"/api/state"' in source
    assert '"/api/files"' in source
    assert '"/api/sessions"' in source
    assert '"/api/workspaces"' in source


def test_origin_проверяется_до_чтения_тела() -> None:
    """Отказ обязан происходить до чтения тела: иначе чужой запрос зависнет."""
    source = SERVER.read_text(encoding="utf-8")
    post = source[source.index("def do_POST"):]
    origin_at = post.index("_same_origin")
    body_at = post.index("self._body()")
    assert origin_at < body_at, "тело читается раньше проверки Origin"