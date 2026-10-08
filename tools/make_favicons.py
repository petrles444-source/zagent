r"""Собрать favicon.ico для страницы, которой иконки ещё нет.

Зачем
----
У трёх новых подач (`aurum`, `lumen`, `onyx`) иконки не было: папка
создавалась целиком, а `tools/make_icons.py` рисует иконки для
конкретного набора страниц. Здесь — тот же подход, но для одной папки
и без жёсткой привязки к списку.

Как устроено
------------
Иконка рисуется кодом в Pillow: круглый диск в фоне страницы, тонкая
рамка и буква названия. Файл собирается сразу из шести размеров, иначе
браузер на маленьком размере возьмёт первый доступный и мыло получится.

Запуск:
    .venv\Scripts\python.exe tools\make_favicons.py aurum
    .venv\Scripts\python.exe tools\make_favicons.py --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIOS = ROOT / "portfolios"

#: Размеры, которые кладутся в .ico. Первые три — то, что браузер
#: выбирает для вкладки и для закладки, остальные — для крупных значков.
ICO_SIZES = (16, 32, 48, 64, 128, 256)

#: Как выглядит каждая подача: буква, рамка и заливка. Цвета взяты из
#: переменных её style.css — иначе иконка была бы чужеродной странице.
STYLES = {
    "aurum": {"letter": "A", "ring": (184, 150, 90), "disc": (251, 250, 247),
              "ink": (33, 29, 22)},
    "lumen": {"letter": "L", "ring": (91, 124, 153), "disc": (252, 253, 254),
              "ink": (27, 32, 38)},
    "onyx": {"letter": "O", "ring": (217, 196, 163), "disc": (20, 22, 26),
             "ink": (236, 234, 230)},
    # Steel рисуется не буквой в круге, а срезом листа: страница
    # называется «сталь и стекло», и буква «S» рядом с пятью другими
    # буквами её ничем не отличала бы. Две скошенные пластины —
    # узнаваемый знак и честная метафора замысла.
    "steel": {"shape": "plate", "ring": (154, 163, 170),
              "disc": (247, 248, 249), "ink": (35, 40, 44)},
}

#: Подачи, у которых иконка рисуется не буквой.
PLATE = "plate"


def build(style: dict[str, object], path: Path) -> bool:
    """Нарисовать и сохранить .ico. Возвращает удалось ли."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Нет Pillow: .venv\\Scripts\\python.exe -m pip install Pillow",
              file=sys.stderr)
        return False

    largest = max(ICO_SIZES)
    ring = tuple(style["ring"])
    disc = tuple(style["disc"])
    ink = tuple(style["ink"])

    # Рисуем ОДИН кадр максимального размера и отдаём его Pillow с
    # перечнем размеров: библиотека сама уменьшит и запишет все шесть.
    #
    # Так делать нельзя: собрать шесть отдельных картинок и сохранить
    # первую. Pillow при сохранении в ICO берёт ровно один кадр, и в
    # файл попадал только 16x16 — остальные пять молча терялись.
    # Иконка выглядела мылом на вкладке, а большого значка не было
    # вовсе, при этом скрипт рапортовал об успехе.
    scale = 4                      # запас для гладких краёв при уменьшении
    big = Image.new("RGBA", (largest * scale, largest * scale),
                    (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    pad = int(largest * scale * 0.08)
    box = [pad, pad, largest * scale - pad - 1, largest * scale - pad - 1]
    draw.ellipse(box, fill=disc + (255,), outline=ring + (255,),
                 width=max(1, largest * scale // 24))

    if style.get("shape") == PLATE:
        draw_plate(draw, largest * scale, ring, ink)
    else:
        font = None
        try:
            from PIL import ImageFont
            font_path = Path("C:/Windows/Fonts/georgiab.ttf")
            if not font_path.is_file():
                font_path = Path("C:/Windows/Fonts/arialbd.ttf")
            if font_path.is_file():
                font = ImageFont.truetype(
                    str(font_path), int(largest * scale * 0.52))
        except Exception:
            font = None
        if font is not None:
            letter = str(style["letter"])
            left, top, right, bottom = draw.textbbox((0, 0), letter,
                                                      font=font)
            x = (largest * scale - (right - left)) / 2 - left
            y = (largest * scale - (bottom - top)) / 2 - top
            draw.text((x, y), letter, fill=ink + (255,), font=font)

    # От большего к меньшему: Pillow полагается на порядок размеров.
    big.save(path, format="ICO",
             sizes=[(s, s) for s in sorted(ICO_SIZES, reverse=True)])
    return True


def draw_plate(draw: object, size: int, ring: tuple, ink: tuple) -> None:
    """Срез листа вместо буквы.

    Две пластины, у которых верхний и нижний края скошены в одну
    сторону. Скос здесь и есть смысл знака: ровные прямоугольники
    читаются как кнопка «пауза», а скошенные — как снятая фаска,
    то есть кусок металла, из которого вырезали деталь.

    Направление скоса у пластин противоположное: от этого появляется
    щель между ними, и она читается как срез, а не как зазор.

    Форма рассчитана на все шесть размеров иконки: на 16 пикселях
    линия тоньше пикселя рассыпается, поэтому пластины широкие и
    без мелких деталей.
    """
    cx = cy = size / 2
    half = size * 0.22           # половина высоты пластины
    width = size * 0.20          # ширина пластины
    slant = size * 0.11          # величина скоса по горизонтали

    # Левая пластина: наклон вправо-верх.
    draw.polygon([
        (cx - size * 0.264 + slant, cy - half),
        (cx - size * 0.264 + slant + width, cy - half),
        (cx - size * 0.264 + width, cy + half),
        (cx - size * 0.264, cy + half),
    ], fill=ink + (255,))

    # Правая пластина: зеркальный наклон. Между пластинами остаётся
    # щель одинаковой ширины сверху и снизу — это и есть срез.
    draw.polygon([
        (cx + size * 0.110, cy - half),
        (cx + size * 0.110 + width, cy - half),
        (cx + size * 0.110 + width - slant, cy + half),
        (cx + size * 0.110 - slant, cy + half),
    ], fill=ring + (255,))


def verify(path: Path) -> bool:
    """Проверить, что в .ico лежат все шесть размеров.

    Pillow пишет в ICO столько кадров, сколько попросили в `sizes`,
    но если отдать ему список уже готовых картинок, возьмёт он ровно
    одну. Ошибка молчаливая: файл создан, скрипт отчитался об успехе,
    а на вкладке мыло. Поэтому проверяем заголовок самого файла, а не
    доверяем возвращённому значению.
    """
    import struct

    data = path.read_bytes()
    if data[:4] != b"\x00\x00\x01\x00":
        print(f"  ПРОБЛЕМА: {path.name} не ICO", file=sys.stderr)
        return False

    count = struct.unpack("<H", data[4:6])[0]
    found = set()
    for i in range(count):
        offset = 6 + i * 16
        width = data[offset] or 256
        found.add(width)

    missing = [s for s in ICO_SIZES if s not in found]
    if missing:
        print(f"  ПРОБЛЕМА: {path.name} без размеров {missing}",
              file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="иконки для портфолио")
    parser.add_argument("names", nargs="*", help="папки портфолио")
    parser.add_argument("--all", action="store_true", help="все известные")
    args = parser.parse_args()

    targets = list(STYLES) if args.all else args.names
    if not targets:
        targets = list(STYLES)

    failed = 0
    for name in targets:
        style = STYLES.get(name)
        if style is None:
            print(f"нет стиля для «{name}»: известны {', '.join(STYLES)}",
                  file=sys.stderr)
            failed += 1
            continue
        folder = PORTFOLIOS / name
        if not folder.is_dir():
            print(f"нет папки portfolios/{name}")
            failed += 1
            continue
        target = folder / "favicon.ico"
        if build(style, target):
            # Проверяем файл, а не верим «сохранилось»: ошибка с
            # количеством кадров молчаливая, и без проверки иконка
            # мылила на вкладке при «успешной» сборке.
            if verify(target):
                print(f"записан {target.relative_to(ROOT)}  "
                      f"({target.stat().st_size} байт, "
                      f"размеры {ICO_SIZES})")
            else:
                failed += 1
        else:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())