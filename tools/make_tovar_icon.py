r"""Нарисовать иконку для NovaTech Store.

Зачем
----
У страницы не было значка: в разметке стоял `<link rel="icon"
href="favicon.ico">`, а файла не существовало — вкладка оставалась со
стандартной иконкой GitHub, и страница выглядела чужеродно.

Рисуем кодом, а не берём из интернета: правило проекта запрещает
внешние загрузки, и картинка из сети была бы тем же нарушением.

Знак
----
Не «магазин» и не «корзина»: витрина продаёт сайты, а не товар.
Знак — три наложенных окна, как стопка файлов проекта. Он читается
на 16 пикселях и не путается с буквой.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_tovar_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "tovar"

# Палитра из :root страницы: иконка обязана совпадать со стилем.
BG = (10, 10, 15)
CYAN = (0, 224, 255)
BLUE = (88, 86, 214)
PURPLE = (168, 85, 247)

ICO_SIZES = (16, 32, 48, 64, 128, 256)


def build() -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Нет Pillow: .venv\\Scripts\\python.exe -m pip install Pillow",
              file=sys.stderr)
        return False

    if not SITE.is_dir():
        print(f"нет папки {SITE}", file=sys.stderr)
        return False

    biggest = max(ICO_SIZES)
    scale = 4
    side = biggest * scale
    image = Image.new("RGBA", (side, side), BG + (255,))
    draw = ImageDraw.Draw(image)

    # Три окна, каждое сдвинуто вправо и вниз: стопка файлов.
    widths = (0.62, 0.54, 0.46)      # доля от ширины холста
    heights = (0.34, 0.30, 0.26)
    colors = (CYAN, PURPLE, BLUE)

    for i, (wf, hf, color) in enumerate(zip(widths, heights, colors)):
        w = side * wf
        h = side * hf
        x = side * 0.10 + i * side * 0.11
        y = side * 0.22 + i * side * 0.10
        draw.rectangle([x, y, x + w, y + h], outline=color + (255,),
                       width=max(2, side // 96))

    # Отдельная иконка для страницы: PNG того же знака.
    icon = SITE / "favicon.ico"
    image.save(icon, format="ICO",
               sizes=[(s, s) for s in sorted(ICO_SIZES, reverse=True)])

    # Проверка: должно быть шесть размеров. Pillow при переданном
    # списке готовых картинок берёт только первую, и иконка мылит
    # на вкладке при «успешной» сборке.
    import struct
    count = struct.unpack("<H", icon.read_bytes()[4:6])[0]
    if count != len(ICO_SIZES):
        print(f"ВНИМАНИЕ: в ico {count} размеров вместо {len(ICO_SIZES)}",
              file=sys.stderr)
        return False

    print(f"записан {icon.relative_to(ROOT)}  ({icon.stat().st_size} байт, "
          f"{ICO_SIZES})")
    return True


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
