r"""Нарисовать картинку для сайта PINK ÉLITE.

Зачем
----
У сайта нет ни одной картинки: ни логотипа, ни превью, ни иконки.
А нужны все три — они и есть визитная карточка страницы в выдаче
поиска, в закладках и на экране телефона.

Почему рисуем кодом, а не берём фото
------------------------------------
Своих фотографий ногтей в проекте нет, а кадры из принесённых видео
принадлежат другим людям: публиковать чужие работы нельзя. Поэтому
картинка строится из цветов палитры страницы и текста — это честно,
лежит в проекте, весит мало и не нарушает ничьих прав.

Что на картинке
---------------
Розово-золотая плашка с названием салона и подписью «демо-заготовка»:
без этой подписи страницу можно принять за действующий салон.

Размеры
-------
`poster.png` — 1200×630, размер превью в соцсетях и поиске.
`favicon.ico` — тот же рисунок в шести размерах, от 16 до 256.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_barbie_art.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "barbie"

#: Палитра страницы: розовый фон, золото акцента, тёмный текст.
PINK_DEEP = (201, 79, 124)
PINK_SOFT = (245, 214, 228)
PINK_PALE = (253, 240, 245)
GOLD = (201, 162, 39)
INK = (58, 20, 38)
WHITE = (255, 255, 255)

#: Превью в соцсетях и поиске принимает 1200×630 — это не украшение,
#: а требование площадок: другое соотношение обрезается по краям.
POSTER = (1200, 630)

#: Размеры иконки. Первые три берёт браузер для вкладки и закладки.
ICO_SIZES = (16, 32, 48, 64, 128, 256)


def font(size: int, *, bold: bool = False, serif: bool = False) -> object:
    """Найти шрифт. Без него Pillow нарисует квадраты вместо букв."""
    from PIL import ImageFont

    if serif:
        names = (["georgiab.ttf", "georgia.ttf"] if bold
                 else ["georgiai.ttf", "times.ttf"])
    else:
        names = (["seguibl.ttf", "arialbd.ttf"] if bold
                 else ["segoeui.ttf", "arial.ttf"])
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return None


def draw_poster() -> "object":
    """Квадратная основа плашки: розовый фон и золотая рамка."""
    from PIL import Image, ImageDraw

    width, height = POSTER
    image = Image.new("RGB", (width, height), PINK_PALE)
    draw = ImageDraw.Draw(image)

    # Мягкий розовый градиент сверху вниз. Рисуем полосами: градиент
    # средствами Pillow не сделать, а полосы при 630 строках не видно.
    for y in range(height):
        ratio = y / height
        shade = tuple(
            int(PINK_PALE[i] + (PINK_SOFT[i] - PINK_PALE[i]) * (1 - ratio))
            for i in range(3)
        )
        draw.line([(0, y), (width, y)], fill=shade)

    # Золотая рамка в 6 пикселей от края: на превью её почти не видно,
    # но в крупной карточке она отделяет плашку от фона страницы.
    inset = 6
    draw.rectangle(
        [inset, inset, width - inset - 1, height - inset - 1],
        outline=GOLD, width=6)

    # Тонкие угловые засечки — отсылка к «премиальности», как в вёрстке.
    arm = 64
    for x, y, dx, dy in ((inset + 40, inset + 40, 1, 1),
                         (width - inset - 40, inset + 40, -1, 1),
                         (inset + 40, height - inset - 40, 1, -1),
                         (width - inset - 40, height - inset - 40, -1, -1)):
        draw.line([(x, y), (x + arm * dx, y)], fill=GOLD, width=3)
        draw.line([(x, y), (x, y + arm * dy)], fill=GOLD, width=3)

    return image


def place_text(image: "object", text: str, y: int, size: int, *,
               fill: tuple, serif: bool = False, bold: bool = False,
               tracking: int = 0) -> int:
    """Написать строку по центру. Возвращает нижнюю границу текста.

    Трекинг задаётся вручную: заглавные буквы с большим разрядом
    разъезжаются, а Pillow межбуквенного интервала не умеет.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    face = font(size, bold=bold, serif=serif)
    if face is None:
        return y

    widths = []
    for ch in text:
        left, top, right, bottom = draw.textbbox((0, 0), ch, font=face)
        widths.append(right - left)

    total = sum(widths) + tracking * max(0, len(text) - 1)
    x = (image.width - total) / 2

    for ch, w in zip(text, widths):
        draw.text((x, y), ch, fill=fill, font=face)
        x += w + tracking

    left, top, right, bottom = draw.textbbox((0, 0), text[0], font=face)
    return y + (bottom - top)


def build() -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Нет Pillow: .venv\\Scripts\\python.exe -m pip install Pillow",
              file=sys.stderr)
        return False

    SITE.mkdir(parents=True, exist_ok=True)
    image = draw_poster()

    # Название салона — крупно, с разрядом: премиальный стиль требует
    # воздуха между буквами, иначе надпись выглядит как плашка из объявления.
    place_text(image, "PINK ÉLITE", 190, 108, fill=PINK_DEEP,
               serif=True, bold=True, tracking=14)

    # Тонкая золотая линия под названием — разделитель, как в вёрстке.
    draw = ImageDraw.Draw(image)
    line_y = 344
    half = 200
    draw.line([(image.width / 2 - half, line_y), (image.width / 2 + half, line_y)],
              fill=GOLD, width=3)

    place_text(image, "НЕЙЛ-САЛОН · ШАБЛОН", 372, 40, fill=INK,
               serif=True, tracking=6)
    place_text(image, "демо-заготовка", 440, 34, fill=PINK_DEEP,
               serif=True, tracking=4)

    poster = SITE / "poster.png"
    image.save(poster, "PNG", optimize=True)
    print(f"записан {poster.relative_to(ROOT)}  "
          f"({poster.stat().st_size} байт, {POSTER[0]}x{POSTER[1]})")

    # Иконка: та же плашка, уменьшенная. Рисуем крупно с запасом и
    # отдаём Pillow все шесть размеров — он возьмёт ровно один кадр,
    # если передать ему список готовых картинок.
    biggest = max(ICO_SIZES)
    scale = 4
    big = image.resize((biggest * scale, int(biggest * scale * POSTER[1]
                                            / POSTER[0])), Image.LANCZOS)
    # Иконка должна быть квадратной: обрезаем по центру.
    side = big.height
    left = (big.width - side) // 2
    square = big.crop((left, 0, left + side, side))

    # На квадрате крупный текст не читается, оставляем только знак.
    from PIL import ImageDraw as Draw
    d = Draw.Draw(square)
    face = font(int(side * 0.34), bold=True, serif=True)
    if face is not None:
        d.text((side * 0.06, side * 0.18), "P", fill=PINK_DEEP, font=face)

    ico = SITE / "favicon.ico"
    square.save(ico, format="ICO",
                sizes=[(s, s) for s in sorted(ICO_SIZES, reverse=True)])
    print(f"записан {ico.relative_to(ROOT)}  ({ico.stat().st_size} байт)")

    # Проверка: в .ico должно быть шесть записей, иначе Pillow тихо
    # записал одну — иконка будет мылом на вкладке.
    import struct
    count = struct.unpack("<H", ico.read_bytes()[4:6])[0]
    if count != len(ICO_SIZES):
        print(f"ВНИМАНИЕ: в ico {count} размеров вместо {len(ICO_SIZES)}",
              file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    sys.exit(0 if build() else 1)
