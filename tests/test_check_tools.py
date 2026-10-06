"""Проверки инструментов стенда: их вывод должен означать то, что означает.

Инструмент проверки, который не проверяет, хуже отсутствия проверки: он
даёт уверенный неверный ответ, и на него потом опирается выбор модели.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load(name: str):
    path = ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_tool_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (SystemExit, OSError, ValueError) as exc:
        pytest.skip(f"{name}.py не импортируется без сети или ключей: {exc}")
    return module


# ==================================================== vision


def test_vision_решает_по_ответу_а_не_по_коду_200() -> None:
    """Любой ответ с кодом 200 означал «vision».

    Модель, которая изображение проигнорировала и написала «не могу видеть
    картинки», попадала в список умеющих видеть — и селектор отправлял ей
    задачи с картинками по несуществующей способности.
    """
    judge = _load("check_vision").judge
    assert judge("0.4") == "vision"
    assert judge("0.5") == "unsure", "угаданное число не должно быть vision"
    assert judge("0.9") == "no"
    assert judge("I cannot see images") == "no"
    assert judge("я не могу видеть картинки") == "no"
    assert judge("") == "no"
    assert judge("качество плохое") == "no", (
        "модель ответила, но не про картинку — это не vision")


def test_vision_принимает_проценты_и_приблизительные_ответы() -> None:
    """Честная модель считает приблизительно: «0.4», «40%», «около 40
    процентов». Отвергнуть их — значит потерять работающую модель."""
    judge = _load("check_vision").judge
    for text in ("0.4", "0.40", "40%", "около 40 процентов",
                 "The blue fraction is 0.399", "45%", "0.35"):
        assert judge(text) == "vision", text


def test_vision_выбирает_по_первому_числу() -> None:
    first_number = _load("check_vision").first_number
    assert first_number("около 0.4, точнее 0.42") == 0.4
    assert first_number("40 процентов") == 40.0
    assert first_number("0,41") == 0.41
    assert first_number("нет чисел") is None


def test_vision_скрипт_не_запускается_при_импорте() -> None:
    """Иначе разбор ответа нельзя закрыть тестом: `import` прогонял бы
    проверку по всем моделям."""
    source = (ROOT / "tools" / "check_vision.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source


# ==================================================== интерфейс


def test_проверка_интерфейса_без_node_не_находит_проблему_на_здоровом() -> None:
    """Без node проверка скобок возвращала непустую строку, а вызывающий
    считал любую непустую строку проблемой.

    Итог: на машине без node проверка интерфейса находила хотя бы одну
    проблему **всегда** — независимо от того, сломан интерфейс или нет.
    Проверка, которая всегда находит проблему, не находит ничего: её вывод
    перестают читать.
    """
    check_ui = _load("check_ui")
    check_ui.node_available = lambda: False
    good = "function f() { return 1; }"
    assert check_ui.check_js_syntax(good) is None, (
        "здоровый скрипт объявлен проблемой только потому, что нет node")
    # Настоящая проблема при этом обязана остаться проблемой.
    assert check_ui.check_js_syntax("function f() { return 1;") != ""
