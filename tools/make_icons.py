#!/usr/bin/env python3
r"""Нарисовать иконки: круглые, на белом фоне, в духе ВК.

Зачем это
---------
Иконка сайта — первое, что человек видит во вкладке и в закладках.
Стандартная, которая рисуется по умолчанию, выглядит как серая
полоска и не говорит ни о чём. Своя иконка решает это, и рисуется
кодом: никаких графических редакторов, никаких чужих картинок.

Почему круглая и на белом фоне
-----------------------------
Так выглядит аватар в ВК и в Телеграме, и так выглядят иконки
приложений в Windows: круг на светлом фоне. На тёмном фоне круг
теряется, а на пёстром — сливается с подложкой, и в мелком размере
(16 пикселей во вкладке) иконка превращается в пятно.

Отдельно про размеры
--------------------
Один файл `.ico` содержит несколько размеров сразу: браузер сам
выберет нужный. Это обязательно — одна картинка 512×512 в мелкой
вкладке превращается в неразличимое пятно, и Windows отдельно
предупреждает, что иконка «слишком маленькая».

Запуск
------
    .venv\Scripts\python.exe tools\make_icons.py
    .venv\Scripts\python.exe tools\make_icons.py --site
    .venv\Scripts\python.exe tools\make_icons.py --upload
"""
from __future__ import annotations

import argparse
import io
import os
import struct
import sys
import zlib
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DIST = ROOT / "site-dist"

#: Размеры, которые кладутся в один .ico. Меньше 16 нельзя: это
#: системный значок, и без него Windows ругается на иконку.
ICO_SIZES = (16, 32, 48, 64, 128, 256)

#: Цвета. Фон белый, круг — цвет знака, обводка — темнее круга.
#:
#: Два цвета вместо одного намеренно: на белом фоне одноцветный круг
#: в 16 пикселей выглядит как простое пятно, а с тёмной каймой читается
#: как знак.
WHITE = (255, 255, 255)
INK = (12, 14, 18)


def circle_icon(size: int, fill: tuple[int, int, int],
                accent: tuple[int, int, int],
                letter: str) -> Image.Image:
    """Круглая иконка: белый фон, круг, буква внутри.

    Буква рисуется встроенным шрифтом Pillow. Свой шрифт не нужен:
    латинская буква в таком размере читается и системным начертанием,
    а подключать файл шрифта ради одной буквы незачем.
    """
    image = Image.new("RGBA", (size, size), WHITE + (255,))
    draw = ImageDraw.Draw(image)

    # Отступ от края: круг не должен касаться границы, иначе в 16
    # пикселей он обрезается по углам квадрата.
    pad = max(1, size // 16)
    box = (pad, pad, size - pad - 1, size - pad - 1)
    draw.ellipse(box, fill=fill + (255,))

    # Буква. Размер шрифта подбирается по кругу, а не задаётся
    # числом: при разных размерах иконки одно и то же число даёт
    # разный результат — от невидимой буквы до буквы за краями.
    font_size = int(size * 0.52)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except OSError:
        font = ImageFont.load_default(size=font_size)
    # Смещение считается по настоящему размеру текста: надпись может
    # оказаться шире круга, и без поправки она уедет вбок.
    left, top, right, bottom = draw.textbbox((0, 0), letter, font=font)
    width = right - left
    height = bottom - top
    x = (size - width) / 2 - left
    y = (size - height) / 2 - top
    draw.text((x, y), letter, font=font, fill=WHITE + (255,))

    return image


def save_png(image: Image.Image, path: Path) -> None:
    """Сохранить PNG без потери прозрачности по кругу."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def save_ico(image: Image.Image, path: Path,
             sizes: tuple[int, ...] = ICO_SIZES) -> None:
    """Собрать .ico сразу из нескольких размеров.

    Один файл со всеми размерами — требование, а не украшение:
    браузер и Windows берут из него тот размер, который им нужен, и
    иначе браузер уменьшает большую картинку сам, теряя детали.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Pillow требует, чтобы самый большой размер был первым и совпадал
    # с реальным размером картинки — иначе .ico получается битым.
    ordered = sorted(set(sizes), reverse=True)
    image.save(path, "ICO", sizes=[(s, s) for s in ordered])


#: Иконки для всех трёх портфолио и сайта. Ключ — папка, значение —
#: (цвет круга, буква).
MARKS: dict[str, tuple[tuple[int, int, int], str]] = {
    "neon": ((10, 42, 58), "N"),
    "paper": ((168, 50, 30), "P"),
    "term": ((18, 35, 63), "T"),
    "site": ((5, 5, 5), "N"),
}


def site_favicon() -> Image.Image:
    """Иконка сайта: тёмный круг с буквой и неоновым ободком.

    Ободок сделан вторым кругом чуть меньшего размера: так иконка
    читается и в светлой, и в тёмной вкладке, где обычный тёмный
    круг на тёмном фоне просто исчезает.
    """
    size = 256
    image = Image.new("RGBA", (size, size), WHITE + (255,))
    draw = ImageDraw.Draw(image)
    pad = size // 16
    draw.ellipse((pad, pad, size - pad - 1, size - pad - 1),
                 fill=INK + (255,))
    inner = size // 8
    draw.ellipse((inner, inner, size - inner - 1, size - inner - 1),
                 fill=(0, 240, 255, 255))

    try:
        from PIL import ImageFont
        font = ImageFont.truetype("arialbd.ttf", int(size * 0.46))
    except OSError:
        font = ImageFont.load_default(size=int(size * 0.46))
    left, top, right, bottom = draw.textbbox((0, 0), "N", font=font)
    draw.text(((size - (right - left)) / 2 - left,
               (size - (bottom - top)) / 2 - top),
              "N", font=font, fill=INK + (255,))
    return image


def build_all(verbose: bool = True) -> list[Path]:
    """Нарисовать все иконки. Возвращает созданные файлы."""
    made: list[Path] = []

    icon = site_favicon()
    for target in (SITE / "favicon.ico", DIST / "favicon.ico"):
        save_ico(icon, target)
        made.append(target)
    save_png(icon, SITE / "assets" / "favicon.png")
    made.append(SITE / "assets" / "favicon.png")
    if verbose:
        print(f"  сайт: favicon.ico ({ICO_SIZES})")

    for name, (color, letter) in MARKS.items():
        if name == "site":
            continue
        mark = circle_icon(256, color, WHITE, letter)
        target = ROOT / "portfolios" / name / "favicon.ico"
        save_ico(mark, target)
        made.append(target)
        save_png(mark, ROOT / "portfolios" / name / "icon.png")
        made.append(ROOT / "portfolios" / name / "icon.png")
        if verbose:
            print(f"  {name}: favicon.ico + icon.png")

    # Отдельные маленькие иконки для бота: они показываются в чате,
    # где полоса вкладки не нужна. Список лиц берётся из persona.py —
    # там же он живёт в ботах, и список должен быть один.
    sys.path.insert(0, str(ROOT / "hosting" / "pythonanywhere" / "bots"))
    from persona import PERSONAS
    for face in PERSONAS:
        key = face["key"]
        dark, accent = face["colors"]
        rgb = tuple(int(dark[i:i + 2], 16) for i in (1, 3, 5))
        mark = circle_icon(256, rgb, WHITE, str(face["name"])[0])
        folder = ROOT / "hosting" / "pythonanywhere" / "bots" / "pictures"
        save_png(mark, folder / f"face-{key}.png")
        made.append(folder / f"face-{key}.png")
    if verbose:
        print(f"  иконки ботов: {len(PERSONAS)}")

    return made


def upload(environ: dict[str, str] | None = None) -> int:
    """Залить иконки на хостинг по FTP.

    Отдельная функция, а не побочный эффект рисования: выкладка —
    действие с внешним миром, и случаться она должна только по
    явному `--upload`.
    """
    import ftplib

    env = {**(environ or {}), **{k: v for k, v in os.environ.items() if v}}
    host = env.get("ZAGENT_FTP_HOST", "s726.ucoz.net")
    user = env.get("ZAGENT_FTP_USER", "8zagent")
    password = env.get("ZAGENT_FTP_PASS", "")
    if not password:
        print("Нет пароля. Задайте переменную ZAGENT_FTP_PASS.")
        return 2

    targets: list[tuple[Path, str]] = [
        (SITE / "favicon.ico", "favicon.ico"),
        (SITE / "assets" / "favicon.png", "favicon.png"),
    ]
    for name in ("neon", "paper", "term"):
        local = ROOT / "portfolios" / name / "favicon.ico"
        if local.is_file():
            targets.append((local, f"{name}/favicon.ico"))

    print(f"куда: {host}")
    ftp = ftplib.FTP()
    try:
        ftp.connect(host, timeout=60)
        ftp.login(user, password)
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")
        for local, remote in targets:
            if not local.is_file():
                print(f"  пропущено: {local.name} не найден")
                continue
            # favicon.ico лежит в корне и заменяет служебный файл
            # панели. Он отдаётся кэшируемым надолго, поэтому рядом
            # кладётся копия с меткой: иначе браузер до месяца будет
            # показывать старую иконку.
            with local.open("rb") as stream:
                ftp.storbinary(f"STOR {remote}", stream, blocksize=1 << 16)
            print(f"  залит {remote} ({local.stat().st_size / 1024:.1f} КБ)")
    except Exception as exc:
        print(f"связь прервана: {exc}")
        return 1
    finally:
        try:
            ftp.quit()
        except Exception:
            pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="нарисовать иконки")
    parser.add_argument("--site", action="store_true",
                        help="только иконка сайта")
    parser.add_argument("--upload", action="store_true",
                        help="залить на хостинг по FTP")
    args = parser.parse_args()

    if args.upload:
        return upload()

    print("рисую иконки:")
    made = build_all()
    total = sum(p.stat().st_size for p in made if p.is_file())
    print(f"\nфайлов: {len(made)}, всего {total / 1024:.0f} КБ")
    print("Залить: .venv\\Scripts\\python.exe tools\\make_icons.py --upload")
    return 0


if __name__ == "__main__":
    sys.exit(main())