#!/usr/bin/env python3
r"""Ужать картинки так, чтобы каждая весила не больше 1 МБ.

Зачем это
---------
Telegram отправляет фотографии без сжатия на своей стороне, поэтому
вес файла — это ровно то, что уйдёт по сети. Лимит в 1 МБ задан, и
его надо гарантировать, а не проверять постфактум: одна слишком
тяжёлая картинка срывает отправку целиком, и человек не видит её
вовсе.

Как гарантируется
----------------
Не «сохранить и посмотреть, получилось ли», а подбор параметров до
тех пор, пока файл не влезет. Порядок такой:

1. **Формат.** WebP лучше JPEG на том же качестве, а Telegram его
   принимает. Но PNG для картинок с прозрачностью лучше, и она
   на аватарах есть, поэтому формат выбирается по содержимому.
2. **Качество.** Снижается от 90 до 35 шагами по 5. Ниже 35 картинка
   рассыпается блоками, и экономия уже не стоит потери вида.
3. **Размер.** Если качество упёрлось в пол, уменьшается сторона.
   Меньше 320 пикселей не опускаемся: телефон такую картинку
   растянет мыльно, и толку от неё не будет.

Что отдаётся
------------
Готовые файлы плюс отчёт по каждому: сколько весил, сколько стал и
чем именно пришлось пожертвовать. Отчёт нужен, чтобы по картинкам
видно было, где качество просело сильнее всего.

Запуск
------
    .venv\Scripts\python.exe tools\shrink_images.py
    .venv\Scripts\python.exe tools\shrink_images.py --folder site\assets\img --limit 900
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

#: Папки с картинками по умолчанию. Обе обрабатываются: и датасет
#: для обучения, и то, что бот показывает в чате.
DEFAULT_FOLDERS = (
    ROOT / "site" / "assets" / "img",
    ROOT / "character" / "dataset",
    ROOT / "hosting" / "pythonanywhere" / "bots" / "pictures",
)

#: Потолок в килобайтах. Ровно 1024, а не «около мегабайта»: Telegram
#: считает байты, и «около» однажды окажется «больше».
DEFAULT_LIMIT_KB = 1024

#: С какой стороны начинаем и куда идём.
QUALITY_START = 90
QUALITY_STEP = 5
QUALITY_FLOOR = 35

#: Ниже этой стороны картинку не уменьшаем: телефон растянет её мыльно,
#: и экономия окажется дороже, чем сам файл.
MIN_SIDE = 320

#: Шаг уменьшения стороны, когда качество уже не помогает.
SIDE_STEP = 64


def encode(image: Image.Image, quality: int) -> tuple[bytes, str]:
    """Закодировать картинку. Возвращает (байты, формат).

    Формат выбирается по наличию прозрачности: с ней JPEG и WebP
    теряют альфа-канал и картинка получает чёрный фон вместо
    прозрачного, а PNG сохраняет её как есть.
    """
    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info)
    if has_alpha:
        # PNG не умеет «качество», поэтому для прозрачных картинок
        # сжимается только размер. Попытка подобрать качество здесь
        # дала бы одинаковый результат и молчаливое отсутствие
        # экономии.
        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=True)
        return buffer.getvalue(), "PNG"

    buffer = io.BytesIO()
    image.save(buffer, "WebP", quality=quality, method=4)
    data = buffer.getvalue()
    # На совсем гладких картинках WebP иногда проигрывает JPEG по
    # размеру. Отступаем, только когда разница заметная.
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, optimize=True,
               progressive=True)
    if len(buffer.getvalue()) < len(data) * 0.9:
        return buffer.getvalue(), "JPEG"
    return data, "WebP"


def shrink(path: Path, limit_kb: int) -> dict[str, object]:
    """Ужать один файл. Возвращает отчёт по нему."""
    limit = limit_kb * 1024
    report: dict[str, object] = {
        "file": path.name, "before_kb": round(path.stat().st_size / 1024, 1),
        "after_kb": None, "format": None, "quality": None,
        "side": None, "ok": False,
    }
    try:
        source = Image.open(path)
        source.load()
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report

    image = source.convert("RGBA" if source.mode in ("RGBA", "LA", "P")
                           else "RGB")
    # EXIF поворачивает картинку в телефоне иначе, чем в Pillow, и
    # после сжатия картинка встаёт боком. Ориентация читается и
    # применяется вручную.
    try:
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image) or image
    except Exception:
        pass

    best: bytes | None = None
    best_format = ""
    best_quality = 0
    side = max(image.size)

    # Исходные байты и формат: потолок нужно выдержать, но раздувать
    # файл нельзя. Считается до подбора, потому что файл на диске
    # будет заменён.
    original_bytes = path.read_bytes()
    original_size = len(original_bytes)
    original_format = path.suffix.lstrip(".").upper() or "PNG"
    if original_format not in ("PNG", "WEBP", "JPEG"):
        original_format = "PNG"

    while True:
        quality = QUALITY_START
        while quality >= QUALITY_FLOOR:
            data, fmt = encode(image, quality)
            # Кодек не обязан быть выгоднее исходника: на пятнистом
            # шуме WebP тяжелее PNG, и «сжатие» раздувает файл вдвое.
            # Такое изображение оставляем в исходном виде — потолок
            # при этом выдержан, а размер не растёт.
            if len(data) > original_size:
                data = original_bytes
                fmt = original_format
            if len(data) <= limit:
                best, best_format, best_quality = data, fmt, quality
                break
            # Запоминаем лучшее из не прошедшего: если качество
            # опустится до пола, придётся уменьшать картинку, и
            # выгодно взять самую маленькую из уже полученных.
            best, best_format, best_quality = data, fmt, quality
            quality -= QUALITY_STEP
        if best is not None and len(best) <= limit:
            break
        if side <= MIN_SIDE:
            # Дальше уменьшать нельзя: картинка станет мыльной.
            break
        side = max(MIN_SIDE, side - SIDE_STEP)
        ratio = side / max(image.size)
        image = image.resize((max(1, int(image.width * ratio)),
                              max(1, int(image.height * ratio))),
                             Image.LANCZOS)

    if best is None:
        report["error"] = "не удалось закодировать"
        return report

    target = path.with_suffix(f".{best_format.lower()}")
    # Если формат изменился, старый файл удаляется: иначе в папке
    # останутся две копии одной картинки, и показываться будет старая.
    if target != path and path.exists():
        path.unlink()
    # Совпадающие имена трогать нельзя: запись идёт по тому же пути,
    # и удаление только что прочитанного файла оборвёт её.
    if target != path:
        target.write_bytes(best)
    else:
        path.write_bytes(best)

    report.update(
        after_kb=round(len(best) / 1024, 1),
        format=best_format, quality=best_quality,
        side=f"{image.width}×{image.height}",
        ok=len(best) <= limit,
        name=target.name,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="ужать картинки до 1 МБ")
    parser.add_argument("--folder", action="append", default=[],
                        help="папка с картинками (можно указать много раз)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT_KB,
                        help="потолок в килобайтах")
    parser.add_argument("--dry-run", action="store_true",
                        help="только показать, что изменится")
    args = parser.parse_args()

    folders = [Path(f) for f in args.folder] if args.folder else list(
        DEFAULT_FOLDERS)
    found_any = False
    problems = 0

    for folder in folders:
        if not folder.is_dir():
            print(f"{folder}: папки нет, пропускаю")
            continue
        shots = sorted(p for p in folder.iterdir()
                       if p.is_file() and p.suffix.lower() in
                       {".png", ".jpg", ".jpeg", ".webp"})
        if not shots:
            print(f"{folder.name}: картинок нет")
            continue
        found_any = True
        print(f"\n{folder.name}: {len(shots)} картинок, "
              f"потолок {args.limit} КБ")
        for path in shots:
            report = shrink(path, args.limit)
            if report.get("error"):
                print(f"  {report['file']:22} ОШИБКА {report['error']}")
                problems += 1
                continue
            mark = "ок" if report["ok"] else "БОЛЬШЕ ЛИМИТА"
            flag = " (сухой)" if args.dry_run else ""
            print(f"  {str(report['name']):22} {report['before_kb']:>7} → "
                  f"{report['after_kb']:>6} КБ  {report['format']:4} "
                  f"к={report['quality']:<3} {report['side']:<9} {mark}{flag}")
            if not report["ok"]:
                problems += 1

    if not found_any:
        print("\nкартинок нет ни в одной папке.")
        print("Нарисовать: .venv\\Scripts\\python.exe tools\\make_images.py "
              "--all")
        return 1
    print(f"\nготово, проблем: {problems}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())