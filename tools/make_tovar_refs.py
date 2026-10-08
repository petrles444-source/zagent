r"""Сделать три референс-листа для сайта NovaTech Store.

Зачем
----
К трём сгенерированным макетам нужен провод: без него непонятно, что
именно снимать и куда ставить. Референс отвечает на три вопроса, на
которые макет не отвечает:

1. **hero** — где в кадре находится объект, что оставлять пустым под
   текст, какая часть кадра обязана попасть в маленькую превьюшку.
2. **карточки** — три предмета съёмки и разный характер кадра для
   каждого, потому что одинаковые три картинки подряд читаются как
   копипаст.
3. **стиль** — палитра, шрифты, отступы: значения, а не «красиво».

Почему схемы, а не фотографии
------------------------------
Фотографию сгенерировать здесь нечем, и подменять её чем-то
похожим значило бы выдать чужую работу за свою. Референсный лист
рисуется кодом, лежит рядом со страницей, весит килограмма и
правится числами.

Куда класть результат
---------------------
    site/tovar/ref-hero.png
    site/tovar/ref-cards.png
    site/tovar/ref-style.png

Это черновики для согласования, а не часть страницы: в разметку они
не подключаются и на хостинг не выкладываются.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_tovar_refs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "tovar"

# Палитра берётся из style.css магазина: референс должен совпадать
# со страницей, иначе согласование пойдёт по второму кругу.
BG = (10, 10, 15)
PANEL = (22, 22, 32)
LINE = (46, 42, 74)
INK = (244, 244, 250)
MUTED = (150, 146, 178)
CYAN = (0, 224, 255)
BLUE = (88, 86, 214)
PURPLE = (168, 85, 247)
PINK = (236, 72, 153)

W, H = 1200, 800


def base(title: str, subtitle: str):
    """Тёмный холст с шапкой. Возвращает картинку и объект рисования."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)

    face = None
    try:
        from PIL import ImageFont
        for name in ("segoeuib.ttf", "arialbd.ttf"):
            path = Path("C:/Windows/Fonts") / name
            if path.is_file():
                face = ImageFont.truetype(str(path), 30)
                break
    except Exception:
        face = None

    draw.text((56, 48), title, fill=INK, font=face)
    draw.text((56, 92), subtitle, fill=MUTED,
              font=ImageFont.truetype(
                  str(Path("C:/Windows/Fonts/segoeui.ttf")), 19)
              if Path("C:/Windows/Fonts/segoeui.ttf").is_file() else None)
    draw.line([(56, 132), (W - 56, 132)], fill=LINE, width=2)
    return image, draw


def small(size: int = 17, *, bold: bool = False):
    from PIL import ImageFont
    name = "arialbd.ttf" if bold else "arial.ttf"
    path = Path("C:/Windows/Fonts") / name
    if path.is_file():
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return None


def wrap(draw, text: str, face, width: int) -> list[str]:
    """Разбить строку на строки, влезающие в `width` пикселей.

    Без этого текст просто уезжал за правый край холста и обрезался:
    заметка «...как у трёх готовых макетов» читалась до «готовых».
    """
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        probe = (current + " " + word).strip()
        if draw.textlength(probe, font=face) <= width:
            current = probe
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def sheet_hero() -> None:
    """Кадр для первого экрана: что снимать и где останется текст."""
    image, draw = base(
        "Референс 1 / 3 — главный экран",
        "Что снимать: неоновая вывеска или ноутбук с таким же экраном")

    # Рамка кадра.
    fx, fy, fw, fh = 56, 180, 700, 520
    draw.rectangle([fx, fy, fx + fw, fy + fh], outline=LINE, width=2)

    # Слева зона под заголовок: она перекрывается текстом, поэтому
    # в кадре там должен быть фон, а не лицо или важная деталь.
    draw.rectangle([fx, fy, fx + 300, fy + fh], fill=(14, 14, 21))
    draw.rectangle([fx, fy, fx + 300, fy + fh], outline=PINK, width=3)
    draw.text((fx + 22, fy + 24), "ЗОНА ТЕКСТА", fill=PINK, font=small(20, bold=True))
    draw.text((fx + 22, fy + 62), "сюда ложится заголовок", fill=MUTED, font=small(16))

    # Точка фокуса: куда смотрит взгляд при первом касании.
    cx, cy = fx + 500, fy + 240
    draw.ellipse([cx - 54, cy - 54, cx + 54, cy + 54], outline=CYAN, width=3)
    draw.line([(cx - 70, cy), (cx + 70, cy)], fill=CYAN, width=2)
    draw.line([(cx, cy - 70), (cx, cy + 70)], fill=CYAN, width=2)
    draw.text((cx - 58, cy + 84), "ФОКУС", fill=CYAN, font=small(18, bold=True))

    # Мелкая превьюшка: снимок обрезается по центру, поэтому центр
    # кадра обязан содержать смысл, а не пустоту.
    px, py, ps = 800, 560, 180
    draw.rectangle([px, py, px + ps, py + ps], fill=PANEL, outline=LINE, width=2)
    draw.rectangle([px + ps * 0.3, py + ps * 0.3, px + ps * 0.7, py + ps * 0.7],
                   outline=CYAN, width=2)
    draw.text((px, py + ps + 14), "превью 180×180: центр кадра", fill=MUTED,
              font=small(15))

    notes = [
        "Соотношение сторон кадра — 4:3, как у трёх готовых макетов.",
        "Неон — единственный источник света: тёмный фон, светящиеся "
        "линии, никакого дневного освещения.",
        "Фокус на неоне, а не на лице: лицо в кадре не участвует.",
        "Тёмная зона слева обязательна, иначе белый заголовок "
        "не читается.",
        "Не обрезать по центру для превью: смысл должен быть в "
        "центре кадра.",
    ]
    y = 186
    face = small(16)
    for line in notes:
        for chunk in wrap(draw, "— " + line, face, 330):
            draw.text((800, y), chunk, fill=INK, font=face)
            y += 26
        y += 12

    image.save(SITE / "ref-hero.png", "PNG", optimize=True)


def sheet_cards() -> None:
    """Три предмета съёмки: что снимать для каждой карточки."""
    image, draw = base(
        "Референс 2 / 3 — три карточки",
        "Разный характер кадра в каждой: одинаковые три картинки "
        "читаются как копипаст")

    cards = [
        (PURPLE, "Карточка 1 — «Готовый сайт»",
         "Папка с распахнутыми файлами на тёмном столе,",
         "свет изнутри папки, рядом — экран с макетом."),
        (CYAN, "Карточка 2 — «Бесплатный сайт»",
         "Ноутбук под углом, на экране — неоновый макет,",
         "вокруг темнота, контур корпуса подсвечен."),
        (BLUE, "Карточка 3 — «Консультация»",
         "Стол, два ноутбука, между ними — блокнот.",
         "Лица не показывать: кадр о людях, а не о людях."),
    ]

    x = 56
    for color, title, line1, line2 in cards:
        cw, ch = 348, 470
        draw.rectangle([x, 180, x + cw, 180 + ch], fill=PANEL,
                       outline=LINE, width=2)
        draw.rectangle([x, 180, x + cw, 186], fill=color)

        # Схематичная миниатюра: рамка с диагональными лучами.
        ix, iy, iw = x + 20, 210, cw - 40
        draw.rectangle([ix, iy, ix + iw, iy + 210], fill=(15, 15, 24),
                       outline=LINE, width=1)
        draw.polygon([(ix + 30, iy + 180), (ix + iw - 30, iy + 40),
                      (ix + iw - 30, iy + 180)], fill=color)

        draw.text((ix, iy + 232), title, fill=INK, font=small(17, bold=True))
        y = iy + 266
        for line in (line1, line2):
            draw.text((ix, y), line, fill=MUTED, font=small(14))
            y += 24
        x += cw + 20

    draw.text((56, 690),
              "Все три кадра — 4:3, тёмная база, один источник света. "
              "Различие — в предмете и в ракурсе, не в обработке.",
              fill=INK, font=small(16))
    draw.text((56, 726),
              "Формат файлов: webp или png, до 400 КБ на карточку. "
              "Больше — страница тяжелеет, а на мобильном это 3 секунды ожидания.",
              fill=MUTED, font=small(16))

    image.save(SITE / "ref-cards.png", "PNG", optimize=True)


def sheet_style() -> None:
    """Палитра, шрифты, отступы: значения, а не пожелания."""
    image, draw = base(
        "Референс 3 / 3 — стиль и значения",
        "То, что нельзя угадать: цвет, кегль, отступ")

    # Палитра.
    draw.text((56, 168), "Палитра", fill=INK, font=small(20, bold=True))
    swatches = [
        (BG, "#0A0A0F", "фон"),
        (PANEL, "#161620", "панель"),
        (LINE, "#2E2A4A", "граница"),
        (CYAN, "#00E0FF", "циан"),
        (BLUE, "#5856D6", "синий"),
        (PURPLE, "#A855F7", "фиолетовый"),
        (PINK, "#EC4899", "розовый"),
        (INK, "#F4F4FA", "текст"),
    ]
    x = 56
    for color, hexcode, name in swatches:
        draw.rectangle([x, 202, x + 132, 262], fill=color, outline=LINE, width=1)
        draw.text((x, 272), hexcode, fill=INK, font=small(14))
        draw.text((x, 292), name, fill=MUTED, font=small(13))
        x += 142

    # Типографика.
    draw.text((56, 344), "Типографика", fill=INK, font=small(20, bold=True))
    rows = [
        ("Заголовок секции", 44, 300, INK),
        ("Заголовок карточки", 26, 600, CYAN),
        ("Основной текст", 17, 400, MUTED),
        ("Подпись и метка", 13, 400, LINE),
    ]
    y = 384
    for label, size, weight, color in rows:
        draw.text((56, y), f"{label} — {size}px", fill=MUTED, font=small(14))
        face = None
        try:
            from PIL import ImageFont
            name = "arialbd.ttf" if weight >= 600 else "arial.ttf"
            path = Path("C:/Windows/Fonts") / name
            if path.is_file():
                face = ImageFont.truetype(str(path), min(size, 40))
        except Exception:
            face = None
        if face is not None:
            draw.text((360, y - 4), "Aa Бб Вв Гг 0123", fill=color, font=face)
        y += 56

    # Сетка и отступы.
    draw.text((760, 344), "Сетка и отступы", fill=INK, font=small(20, bold=True))
    spacing = [
        "контейнер — 1200px, поля 32 / 20 / 16",
        "секция — отступ снизу 88px",
        "карточка — радиус 16px, граница 1px",
        "текстовая колонка — не шире 58 знаков",
        "радиус кнопки — 12px",
        "неоновое свечение — только на границах и заголовке,",
        "   не на заливке: иначе текст перестаёт читаться",
    ]
    y = 384
    for line in spacing:
        draw.text((760, y), "— " + line, fill=MUTED, font=small(15))
        y += 30

    draw.text((56, 748),
              "Шрифты — системные. Внешняя загрузка запрещена правилом "
              "проекта: страница обязана открываться без интернета.",
              fill=INK, font=small(16))

    image.save(SITE / "ref-style.png", "PNG", optimize=True)


def main() -> int:
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("Нет Pillow: .venv\\Scripts\\python.exe -m pip install Pillow",
              file=sys.stderr)
        return 1

    if not SITE.is_dir():
        print(f"нет папки {SITE}", file=sys.stderr)
        return 2

    sheet_hero()
    sheet_cards()
    sheet_style()

    for name in ("ref-hero.png", "ref-cards.png", "ref-style.png"):
        path = SITE / name
        print(f"записан {path.relative_to(ROOT)}  "
              f"({path.stat().st_size / 1024:.0f} КБ)")
    print("\nЭто черновики для согласования, не часть страницы:")
    print("в разметку они не подключены и на хостинг не выкладываются.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
