"""Относительные пути инструментов относятся к воркспейсу, а не к каталогу запуска.

Регрессия: ``run_tool`` брал ``Path.cwd()`` за основу для относительных путей.
Агент, работавший в отдельной папке (стенд, тест, другой проект), писал в
каталог, из которого был запущен zagent, и получал отказ «путь вне воркспейса»
на файле, который сам же только что открыл. На живом прогоне стенда это
выглядело так: агент говорил «у меня нет прав на запись», не вызвав ни одного
инструмента записи.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hub.agent import AgentConfig, make_guard
from hub.autonomy import AccessLevel, Autonomy
from hub.tools import _default_base, _resolve, run_tool

#: Корень проекта: он же каталог запуска в тестах.
LAUNCH_DIR = Path(__file__).resolve().parent.parent


def _guard(workspace: Path, access: AccessLevel = AccessLevel.WRITE):
    config = AgentConfig(access=access, autonomy=Autonomy.NORMAL, base_dir=str(workspace))
    return make_guard(config)


def test_база_это_корень_воркспейса(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    assert _default_base(guard) == tmp_path


def test_без_воркспейса_берётся_каталог_запуска() -> None:
    assert _default_base(None) == Path.cwd()


def test_пустой_base_не_молча_становится_cwd() -> None:
    """Guard без корня — это аномалия, но подставлять cwd молча опаснее."""
    guard = _guard(LAUNCH_DIR)
    guard.workspace_root = None
    # cwd остаётся запасным вариантом, но он не должен влиять на нормальный
    # случай с заданным воркспейсом.
    assert _default_base(guard) == Path.cwd()


def test_относительный_путь_идёт_в_воркспейс(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("старый", encoding="utf-8")
    guard = _guard(tmp_path)

    result = run_tool("write_file", guard, path="index.html", content="новый",
                      base=tmp_path)

    assert result.ok, result.error
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == "новый"


def test_относительный_путь_не_попадает_в_проект(tmp_path: Path) -> None:
    """Файл с тем же именем в каталоге запуска не должен измениться."""
    marker = LAUNCH_DIR / "_не_трогай_меня.txt"
    guard = _guard(tmp_path)

    # Базовый каталог намеренно не передаём — как это делает агент.
    result = run_tool("write_file", guard, path="_не_трогай_меня.txt", content="x")

    assert result.ok, result.error
    assert (tmp_path / "_не_трогай_меня.txt").exists(), "файл должен быть в воркспейсе"
    assert not marker.exists(), "файл не должен появиться в каталоге запуска"


def test_абсолютный_путь_в_другой_папке_всё_ещё_отвергается(tmp_path: Path) -> None:
    """Исправление не должно снимать границу воркспейса."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outsider = tmp_path / "чужое.txt"
    guard = _guard(workspace)

    result = run_tool("write_file", guard, path=str(outsider), content="x",
                      base=workspace)

    assert not result.ok
    assert not outsider.exists(), "файл за границей создавать нельзя"


def test_чтение_относительного_пути_тоже_в_воркспейсе(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("данные", encoding="utf-8")
    guard = _guard(tmp_path)

    result = run_tool("read_file", guard, path="a.txt")

    assert result.ok, result.error
    assert "данные" in str(result.data or result.output or result)


def test_вложенный_относительный_путь(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    guard = _guard(tmp_path)

    result = run_tool("write_file", guard, path="src/app.py", content="x = 1")

    assert result.ok, result.error
    assert (tmp_path / "src" / "app.py").exists()


def test_base_не_открывает_путь_мимо_границы(tmp_path: Path) -> None:
    """Явно переданный base не шире воркспейса.

    Границу держит guard, а не каталог. Если бы base мог увести запись за
    пределы воркспейса, границу можно было бы обойти одной передачей
    аргумента — а это ровно то, чего она не должна позволять.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    guard = _guard(workspace)

    result = run_tool("write_file", guard, path="a.txt", content="x", base=target)

    assert not result.ok
    assert "вне воркспейса" in (result.error or "")
    assert not (target / "a.txt").exists()


def test_base_внутри_воркспейса_меняет_разрешение_пути(tmp_path: Path) -> None:
    """Если base указывает на подпапку воркспейса, путь разрешается в ней."""
    workspace = tmp_path / "ws"
    (workspace / "src").mkdir(parents=True)
    guard = _guard(workspace)

    result = run_tool("write_file", guard, path="a.txt", content="x",
                      base=workspace / "src")

    assert result.ok, result.error
    assert (workspace / "src" / "a.txt").exists()


def test_resolve_оставляет_абсолютный_путь(tmp_path: Path) -> None:
    absolute = tmp_path / "a.txt"
    assert _resolve(str(absolute), Path("C:/другое")) == absolute.resolve()


def test_resolve_домысливает_основу(tmp_path: Path) -> None:
    base = tmp_path / "ws"
    base.mkdir()
    assert _resolve("a/b.txt", base) == (base / "a" / "b.txt").resolve()


def test_list_видит_относительный_путь(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    guard = _guard(tmp_path)

    result = run_tool("list_dir", guard, path=".")

    assert result.ok, result.error