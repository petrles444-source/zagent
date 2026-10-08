"""Поведенческие проверки чистых функций клиента (вместо проверки текста)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load() -> object:
    spec = importlib.util.spec_from_file_location("zcli_mod2", ROOT / "tools" / "zcli.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


zcli = load()


# ============================================================ размер кадра


def test_обычный_экран_уменьшается_как_просили() -> None:
    assert zcli.scaled_size(1920, 1200, 0.65) == (1248, 780)


def test_без_уменьшения_размер_не_меняется() -> None:
    assert zcli.scaled_size(1920, 1200, 1.0) == (1920, 1200)
    assert zcli.scaled_size(1920, 1200, 0) == (1920, 1200)


def test_огромный_кадр_вписывается_в_предел_энкодера() -> None:
    """Мультимониторный рабочий стол всегда шире предела JPEG."""
    width, height = zcli.scaled_size(130000, 2000, 1.0)
    assert max(width, height) <= 65500
    assert width == 65000


def test_предел_не_превышается_ни_по_одной_стороне() -> None:
    for w, h in ((130000, 2000), (2000, 130000), (70000, 70000)):
        width, height = zcli.scaled_size(w, h, 1.0)
        assert max(width, height) <= 65500, f"{w}x{h} -> {width}x{height}"


def test_вырожденный_кадр_опознаётся() -> None:
    """Ровно то, что даёт np.frombuffer без reshape."""
    assert zcli.looks_degenerate((1, 6912000)) is True
    assert zcli.looks_degenerate((780, 4)) is True


def test_нормальный_кадр_не_считается_вырожденным() -> None:
    assert zcli.looks_degenerate((780, 1248)) is False
    assert zcli.looks_degenerate((1200, 1920)) is False


# ================================================================ подсказка


def test_подсказка_пуста_без_областей() -> None:
    assert zcli.vision_prompt("что тут?", [], (1248, 780)) == "что тут?"


def test_подсказка_содержит_настоящие_размеры() -> None:
    text = zcli.vision_prompt("что тут?", ["текст x=1 y=2"], (1248, 780))
    assert "1248x780" in text
    assert "1920x1080" not in text


def test_подсказка_перечисляет_области() -> None:
    text = zcli.vision_prompt("вопрос", ["текст x=1 y=2 w=3 h=4",
                                         "блок x=5"], (800, 600))
    assert "x=1 y=2" in text and "x=5" in text


# ================================================================= секреты


def test_отчёт_не_обращается_к_ключам(monkeypatch) -> None:
    """Отчёт собирается без единого обращения к секретам.

    Раньше проверялось только текстом функции; мутация «добавим ключ в
    отчёт» проходила, потому что текст проверялся на другое слово.
    Теперь подмена ключей бросает - и отчёт всё равно пишется.
    """
    def boom(*args, **kwargs):
        raise AssertionError("отчёт не должен трогать ключи")

    monkeypatch.setattr(zcli, "resolve_keys", boom)
    path = zcli.save_report("Проверка", "тело", directory=ROOT / "tmp" / "doc_t3")
    assert "тело" in path.read_text("utf-8")
    path.unlink()


def test_в_отчёте_нет_значений_ключей(tmp_path: Path) -> None:
    path = zcli.save_report("Проверка", "тело", meta={"шлюз": "openrouter"},
                            directory=ROOT / "tmp" / "doc_t3")
    body = path.read_text("utf-8")
    assert "sk-or-v1-" not in body
    assert "openrouter" in body
    path.unlink()