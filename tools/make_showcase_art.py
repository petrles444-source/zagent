r"""Нарисовать иконку витрины и подготовить файлы для GitHub Pages.

Зачем
----
Две вещи, без которых страница не откроется как задумано:

1. `icon.png` — без него вкладка остаётся со стандартной иконкой
   GitHub, и страница выглядит чужеродно рядом с остальными.
2. `.nojekyll` — служебный файл, который заставляет GitHub Pages
   отдавать содержимое папки как есть. Без него сборка Jekyll
   выбрасывает всё, начинающееся с подчёркивания, и молча портит
   ссылки. Файл пустой, но GitHub смотрит на имя, а не на размер.

Иконка рисуется кодом в Pillow: внешних загрузок на странице быть
не должно, и картинка, взятая из интернета, была бы нарушением
того же правила.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_showcase_art.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "publish" / "showcase"

BG = (251, 251, 252)
PANEL = (242, 243, 245)
LINE = (228, 230, 234)
INK = (20, 22, 26)

#: Размер иконки. 512 — с запасом: из него делаются все меньшие.
SIZE = 512


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

    image = Image.new("RGB", (SIZE, SIZE), BG)
    draw = ImageDraw.Draw(image)

    # Четыре плитки страницы — намёк на сетку карточек из вёрстки.
    # Иконка должна читаться в 16 пикселей, поэтому плитки крупные,
    # промежуток широкий, а линий всего две.
    margin = SIZE * 0.16
    gap = SIZE * 0.05
    cell = (SIZE - margin * 2 - gap) / 2

    for row in range(2):
        for col in range(2):
            x = margin + col * (cell + gap)
            y = margin + row * (cell + gap)
            # Одна плитка залита — как карточка с превью на странице.
            fill = INK if (row, col) == (0, 0) else PANEL
            outline = INK if (row, col) == (0, 0) else LINE
            draw.rectangle([x, y, x + cell, y + cell],
                           fill=fill, outline=outline, width=6)

    icon = SITE / "icon.png"
    image.save(icon, "PNG", optimize=True)
    print(f"записан {icon.relative_to(ROOT)}  ({icon.stat().st_size} байт, "
          f"{SIZE}x{SIZE})")

    # .nojekyll: пустой, но имя обязательно. GitHub решает по имени.
    nojekyll = SITE / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")
    print(f"записан {nojekyll.relative_to(ROOT)}  (0 байт)")

    return True


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
