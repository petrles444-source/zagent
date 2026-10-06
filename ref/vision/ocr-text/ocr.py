#!/usr/bin/env python
"""Извлечение текста из картинки и оценка точности через CER.

Запуск:
    python ocr.py photo.png                 → текст в stdout
    python ocr.py photo.png --gt right.txt  → текст + оценка точности

Зависимости (поставь только нужное):
    pip install pillow pytesseract
Плюс сам движок Tesseract — https://github.com/tesseract-ocr/tesseract
Windows: choco install tesseract
Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-rus

Без Tesseract скрипт не упадёт — он объяснит, что делать, и вернёт код 2.
Это сознательно: «молча ничего не нашёл» хуже, чем «движок не установлен».
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

#: Пороги по типу изображения. Для кода требуется почти точность, для
#: рукописного текста норма — 20 процентов ошибок.
CER_LIMITS = {
    "code": 0.02,
    "table": 0.05,
    "dialog": 0.08,
    "photo": 0.15,
    "handwriting": 0.20,
}


def normalize(text: str) -> str:
    """Привести к сравнимому виду.

    Пробелы и переносы — шум: у Tesseract они отличаются от наших, и без
    нормализации оценка врёт на проценты. Регистр и ё оставляем: это часть
    содержания, а не оформления.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def cer(truth: str, prediction: str) -> float:
    """Доля несовпавших символов, 0..1.

    Считается по методу Левенштейна. Значение 0 — совпало всё, 1 — не совпало
    ничего.
    """
    a, b = normalize(truth), normalize(prediction)
    if not a:
        return 0.0 if not b else 1.0
    previous = list(range(len(b) + 1))
    for i, ch_a in enumerate(a, start=1):
        current = [i]
        for j, ch_b in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,            # удаление
                current[j - 1] + 1,        # вставка
                previous[j - 1] + (ch_a != ch_b),   # замена
            ))
        previous = current
    return previous[-1] / len(a)


def wer(truth: str, prediction: str) -> float:
    """То же самое, но по словам. Часто говорит о качестве больше, чем CER."""
    a = normalize(truth).split()
    b = normalize(prediction).split()
    if not a:
        return 0.0 if not b else 1.0
    previous = list(range(len(b) + 1))
    for i, word_a in enumerate(a, start=1):
        current = [i]
        for j, word_b in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (word_a != word_b),
            ))
        previous = current
    return previous[-1] / len(a)


def preprocess(image_path: Path):
    """Подготовка картинки. Работает без Pillow — тогда возвращаем ``None``."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None, "нет Pillow: pip install pillow"
    try:
        from PIL import ImageFilter
    except ImportError:
        ImageFilter = None  # type: ignore[assignment]

    try:
        image = Image.open(image_path)
    except FileNotFoundError:
        return None, f"файла нет: {image_path}"
    except Exception as exc:  # noqa: BLE001
        return None, f"не открывается как изображение: {exc}"

    # 1. Оттенки серого: цвет не помогает OCR, а мешает.
    image = image.convert("L")
    # 2. Выравнивание фона: у скриншотов фон серый, и порог не срабатывает.
    image = ImageOps.autocontrast(image, cutoff=1)
    # 3. Увеличение: Tesseract ожидает примерно 300 dpi, у скриншотов меньше.
    #    Ниже 1400 px по ширине распознавание заметно падает.
    if image.width < 1400:
        factor = max(1.0, 1400 / image.width)
        image = image.resize(
            (int(image.width * factor), int(image.height * factor)),
            Image.LANCZOS,
        )
    # 4. Лёгкое размытие убирает шум от сжатия, но не ломает буквы.
    if ImageFilter is not None:
        image = image.filter(ImageFilter.SMOOTH)
    return image, None


def orientation(image_path: Path) -> str:
    """``portrait`` (вертикально), ``landscape`` или ``square``.

    Tesseract заметно хуже читает перевёрнутый текст, а у фото телефонов
    ориентация часто не та, что кажется. Этот код ничего не исправляет — он
    говорит вызывающему, что картинку надо повернуть.
    """
    try:
        from PIL import Image
    except ImportError:
        return "unknown"
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001
        return "unknown"
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def extract(image_path: Path, languages: str = "rus+eng") -> tuple[str | None, str | None]:
    """Текст с картинки либо (None, причина)."""
    prepared, problem = preprocess(image_path)
    if prepared is None:
        return None, problem

    try:
        import pytesseract
    except ImportError:
        return None, "нет pytesseract: pip install pytesseract"

    # 5. psm 6 — «блок текста без разметки». Для скриншотов и кода он
    #    заметно точнее автоматического подбора. Для разбросанного текста
    #    (интерфейс, выпадающий список) нужен psm 11.
    config = "--psm 6"
    try:
        text = pytesseract.image_to_string(prepared, lang=languages, config=config)
    except Exception as exc:  # noqa: BLE001
        return None, (
            f"Tesseract не отвечает: {exc}\n"
            "Проверьте, что он установлен и доступен в PATH. "
            "Windows: choco install tesseract"
        )
    return text, None


def make_samples(out_dir: Path) -> int:
    """Сгенерировать эталонные картинки без внешних источников.

    Нужен `pillow`. Эталон рисуется сам, поэтому оценка не зависит от того,
    что лежит в сети.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Нужен Pillow: pip install pillow", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Текст на белом — самый простой случай.
    image = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(image).text((40, 80), "Привет, мир! 12345", fill="black")
    image.save(out_dir / "01_text.png")
    (out_dir / "01_text.gt.txt").write_text("Привет, мир! 12345", encoding="utf-8")

    # 2. Таблица: колонки, из-за которых порядок строк путается.
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 30), "name    qty    price", fill="black")
    draw.text((40, 90), "apple   10     250", fill="black")
    draw.text((40, 150), "banana  20     300", fill="black")
    draw.text((40, 210), "cherry  30     450", fill="black")
    image.save(out_dir / "02_table.png")
    (out_dir / "02_table.gt.txt").write_text(
        "name qty price\napple 10 250\nbanana 20 300\ncherry 30 450",
        encoding="utf-8",
    )

    # 3. Мелкий шрифт: проверка предобработки.
    image = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(image).text((40, 70), "маленький шрифт 8px", fill="black")
    image.save(out_dir / "03_small.png")
    (out_dir / "03_small.gt.txt").write_text("маленький шрифт 8px", encoding="utf-8")

    print(f"Готово 3 образца → {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Извлечение текста из картинки и оценка точности."
    )
    parser.add_argument("image", nargs="?", help="путь к картинке")
    parser.add_argument("--gt", help="эталонный текст для оценки")
    parser.add_argument("--lang", default="rus+eng", help="языки, например rus+eng")
    parser.add_argument("--kind", default="dialog", choices=sorted(CER_LIMITS),
                        help="тип картинки: влияет на допустимую ошибку")
    parser.add_argument("--make-samples", action="store_true",
                        help="создать эталонные образцы и выйти")
    parser.add_argument("--out", help="папка для --make-samples")
    args = parser.parse_args(argv)

    if args.make_samples:
        return make_samples(Path(args.out or "samples"))

    if not args.image:
        parser.print_help()
        return 2

    image_path = Path(args.image)
    text, problem = extract(image_path, args.lang)
    if text is None:
        print(f"Ошибка: {problem}", file=sys.stderr)
        return 2

    # Если эталон не дан, извлечённый текст всё равно полезно показать, но
    # точность посчитать не по чему — об этом честно сказано в выводе.
    print(text.strip())
    print(f"\n--- символов: {len(normalize(text))}")

    if not args.gt:
        return 0

    truth = Path(args.gt).read_text(encoding="utf-8", errors="replace")
    error = cer(truth, text)
    words = wer(truth, text)
    limit = CER_LIMITS[args.kind]

    print(f"--- CER: {error:.1%} (порог для «{args.kind}»: {limit:.0%})")
    print(f"--- WER: {words:.1%}")

    if error <= limit:
        print("Итог: в пределах нормы")
        return 0
    print("Итог: точность ниже нормы")
    print("Что обычно помогает: увеличить картинку, убрать шум, "
          "проверить `--psm` (6 — блок, 4 — колонка, 11 — разбросанный текст)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())