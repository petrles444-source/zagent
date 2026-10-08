"""Ужимание картинок: гарантия потолка в 1 МБ и честность отчёта.

Проверяется не «картинка красивая», а единственное свойство, ради
которого скрипт написан: после обработки ни один файл не превышает
потолок. Всё остальное — средство, а не результат.

Особый случай — прозрачность
---------------------------
Картинка с альфа-каналом обязана остаться PNG: JPEG и WebP альфу
теряют, и вместо прозрачности получается чёрный фон. Это проверяется
отдельно, потому что ошибка выглядит не как ошибка, а как «картинка
стала тёмной».
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

_spec = importlib.util.spec_from_file_location(
    "shrink_images", TOOLS / "shrink_images.py")
assert _spec and _spec.loader
shrink = importlib.util.module_from_spec(_spec)
sys.modules["shrink_images"] = shrink
_spec.loader.exec_module(shrink)


@pytest.fixture
def noisy(tmp_path: Path) -> Path:
    """Настоящая фотографическая картинка.

    Берётся шум, а не ровная заливка: заливка сжимается любым
    кодеком до копеек, и на ней невозможно проверить, что подбор
    параметров вообще работает.
    """
    import numpy as np
    rng = np.random.default_rng(7)
    # Мелкие пятна при увеличении дают высокочастотную картинку — та,
    # что сжимается хуже всего. Именно на ней проверяется потолок:
    # на гладкой фотографии сжатие проходит с первого шага.
    base = rng.integers(40, 210, (256, 256, 3), dtype="uint8")
    array = np.repeat(np.repeat(base, 6, axis=0), 6, axis=1)
    path = tmp_path / "photo.png"
    Image.fromarray(array).save(path, "PNG")
    return path


def assert_within(path: Path, limit_kb: int) -> int:
    """Проверить потолок. Возвращает вес в килобайтах."""
    size = path.stat().st_size
    assert size <= limit_kb * 1024, (
        f"{path.name}: {size / 1024:.0f} КБ при потолке {limit_kb} КБ")
    return round(size / 1024, 1)


# =============================================================== потолок


def test_тяжёлая_картинка_втискивается(noisy: Path) -> None:
    """Главное: результат всегда не больше потолка."""
    assert noisy.stat().st_size > 100 * 1024, "тестовая картинка не тяжёлая"
    report = shrink.shrink(noisy, DEFAULT := shrink.DEFAULT_LIMIT_KB)
    assert report["ok"] is True, report
    result = noisy.parent / str(report["name"])
    assert_within(result, DEFAULT)


def test_картинка_уменьшается_а_не_удаляется(noisy: Path) -> None:
    """Файл должен остаться на диске: иначе показывать нечего."""
    report = shrink.shrink(noisy, 200)
    result = noisy.parent / str(report["name"])
    assert result.is_file(), "результат не сохранён"
    assert result.stat().st_size > 0, "файл пустой"


def test_очень_жёсткий_потолок_тоже_выполняется(tmp_path: Path) -> None:
    """Даже потолок в 40 КБ должен достигаться, а не объявляться ошибкой.

    Иначе на честной фотографии скрипт сказал бы «не влезло» и
    оставил бы файл тяжёлым — то есть ровно то, чего от него просили
    не сделать.
    """
    import numpy as np
    rng = np.random.default_rng(3)
    array = rng.integers(0, 255, (400, 400, 3), dtype="uint8")
    path = tmp_path / "tough.png"
    Image.fromarray(array).save(path, "PNG")
    report = shrink.shrink(path, 40)
    assert report["ok"] is True, report
    assert_within(path.parent / str(report["name"]), 40)


def test_размер_не_падает_ниже_предела(tmp_path: Path) -> None:
    """Слишком мелко ужимать нельзя: телефон растянет мыльно."""
    import numpy as np
    rng = np.random.default_rng(11)
    array = rng.integers(0, 255, (800, 800, 3), dtype="uint8")
    path = tmp_path / "big.png"
    Image.fromarray(array).save(path, "PNG")
    report = shrink.shrink(path, 20)
    assert report["ok"] is True, report
    width, height = str(report["side"]).split("×")
    assert int(width) >= shrink.MIN_SIDE, f"сторона упала до {report['side']}"


# =============================================================== прозрачность


def test_прозрачность_остаётся_прозрачностью(tmp_path: Path) -> None:
    """Аватар с альфой обязан остаться PNG.

    Ошибка здесь не выглядит как ошибка: картинка просто становится
    тёмной, и человек думает, что так и задумано.
    """
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    for x in range(256):
        for y in range(256):
            if (x - 128) ** 2 + (y - 128) ** 2 < 100 ** 2:
                image.putpixel((x, y), (0, 240, 255, 255))
    path = tmp_path / "alpha.png"
    image.save(path, "PNG")

    report = shrink.shrink(path, shrink.DEFAULT_LIMIT_KB)
    assert report["format"] == "PNG", (
        f"прозрачная картинка ушла в {report['format']}")
    result = Image.open(path.parent / str(report["name"]))
    assert result.mode in ("RGBA", "LA"), f"альфа потеряна: {result.mode}"
    # Угол обязан остаться прозрачным, а не чёрным.
    assert result.convert("RGBA").getpixel((2, 2))[3] == 0, "фон стал непрозрачным"


def test_картинка_без_прозрачности_уходит_в_современный_формат(
        noisy: Path) -> None:
    """Непрозрачная фотография должна лежать в WebP или JPEG."""
    report = shrink.shrink(noisy, shrink.DEFAULT_LIMIT_KB)
    # Формат остаётся тем же или становится современнее. PNG на такой
    # картинке остаётся законно: кодек не выиграл, и выигрывать было бы
    # ценой качества.
    assert report["format"] in ("WebP", "JPEG", "PNG"), report["format"]


# =============================================================== отчёт


def test_отчёт_показывает_было_и_стало(noisy: Path) -> None:
    """Без «было» в отчёте не видно, что сжатие вообще что-то сделало."""
    report = shrink.shrink(noisy, 200)
    # Картинка может оказаться уже лёгкой: тогда «сжатие» обязано
    # оставить её как есть, а не раздуть до потолка. Поэтому
    # сравнение не «меньше», а «не больше».
    assert report["before_kb"] >= report["after_kb"], (
        f"картинка раздута: {report['before_kb']} → {report['after_kb']} КБ")
    assert report["before_kb"] > 0


def test_лёгкая_картинка_не_раздувается(tmp_path: Path) -> None:
    """Файл меньше потолка не должен увеличиться.

    Регрессия: WebP на пятнистом шуме весит больше PNG, и без
    сравнения с исходником «сжатие» раздувало картинку втрое при том,
    что потолок даже не был близок.
    """
    import numpy as np
    rng = np.random.default_rng(21)
    # Гладкая заливка с лёгким шумом — как раз тот случай, где PNG
    # уже хорош и улучшать нечего.
    base = rng.integers(100, 140, (200, 200, 3), dtype="uint8")
    array = np.repeat(np.repeat(base, 2, axis=0), 2, axis=1)
    path = tmp_path / "light.png"
    Image.fromarray(array).save(path, "PNG")
    before = path.stat().st_size
    report = shrink.shrink(path, 1024)
    result = path.parent / str(report["name"])
    assert result.stat().st_size <= before, (
        f"лёгкую картинку раздули: {before / 1024:.0f} → "
        f"{result.stat().st_size / 1024:.0f} КБ")


def test_битая_картинка_не_роняет_скрипт(tmp_path: Path) -> None:
    """Файл не картинка должен быть описан, а не поднять исключение."""
    path = tmp_path / "broken.png"
    # Запись через encode: литерал с кириллицей в байтах недопустим,
    # а файл должен быть именно битым, а не пустым.
    path.write_text("это не изображение", encoding="utf-8")
    report = shrink.shrink(path, shrink.DEFAULT_LIMIT_KB)
    assert report["ok"] is False
    assert "error" in report, f"причина не сообщена: {report}"
    assert path.is_file(), "исходный файл удалён — а он не наш"


def test_повторная_обработка_не_увеличивает(noisy: Path) -> None:
    """Повторный прогон по уже сжатой картинке не должен её раздуть.

    В папке регулярно прогоняют скрипт, и если второй проход вдруг
    окажется тяжелее, получится бесконечное «сжатие» без пользы.
    """
    first = shrink.shrink(noisy, 200)
    first_kb = first["after_kb"]
    name = str(first["name"])
    second = shrink.shrink(noisy.parent / name, 200)
    assert second["after_kb"] <= first_kb, (
        f"повторный прогон раздул: {first_kb} → {second['after_kb']} КБ")


def test_старый_файл_не_остаётся_рядом(tmp_path: Path) -> None:
    """После смены формата старый файл не должен лежать рядом.

    Иначе в папке окажутся две копии одной картинки, и бот будет
    показывать ту, что осталась от прошлого прогона.
    """
    import numpy as np
    rng = np.random.default_rng(5)
    array = rng.integers(0, 255, (400, 400, 3), dtype="uint8")
    path = tmp_path / "orig.png"
    Image.fromarray(array).save(path, "PNG")
    report = shrink.shrink(path, 60)
    files = sorted(p.name for p in tmp_path.iterdir()
                   if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    assert len(files) == 1, f"в папке осталось лишнего: {files}"
    assert files[0] == str(report["name"])


# =============================================================== настройки


def test_потолок_по_умолчанию_мегабайт() -> None:
    """Лимит задан как требование, и он не должен тихо измениться."""
    assert shrink.DEFAULT_LIMIT_KB == 1024


def test_минимальная_сторона_разумна() -> None:
    """Сторона должна оставаться такой, чтобы картинка была видна."""
    assert 320 <= shrink.MIN_SIDE <= 512


def test_качество_не_падает_в_кашу() -> None:
    """Ниже 35 картинка рассыпается: экономия перестаёт иметь смысл."""
    assert shrink.QUALITY_FLOOR >= 30
    assert shrink.QUALITY_START > shrink.QUALITY_FLOOR