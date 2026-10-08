#!/usr/bin/env python3
r"""Собрать датасет для обучения LoRA на персонажа.

Зачем это нужно
---------------
LoRA учится на картинках и на подписях к ним. Без подписей модель
запоминает только «как выглядит» и не понимает, что меняется: любой
запрос даст одно и то же лицо в одной и той же позе. Поэтому для
каждой картинки рядом лежит `.txt` с тем же именем — это то, что
тренажёр читает как описание.

Что делает скрипт
-----------------
1. Кладёт подписи к уже нарисованным картинкам, переименовывая файлы
   в `0001.png` / `0001.txt` — такой порядок тренажёр разбирает
   однозначно.
2. Проверяет, что каждой картинке есть подпись, а каждой подписи —
   картинка. Ошибка в этом с�� стороны не ловится: тренажёр молча
   пропустит файл и обучится на меньшем числе примеров, чем
   ожидалось.

Про активационный тег
---------------------
В начале каждой подписи стоит одно слово-триггер, например `ohwx`.
Оно не перемешивается с остальными тегами и говорит модели: «вот
это слово — вот этот персонаж». Без него результат получится
размытым, и понять почему, можно будет только переобучив.

Нужен ли этот скрипт, если есть Colab
--------------------------------------
Нет. Скрипт собирает датасет на этой машине, из картинок, нарисованных
моделью `make_images.py`. Colab используется уже собранный архив:
подписи и картинки кладутся в `MyDrive/Loras/<имя>/dataset`, и в
ноутбуке остаётся только указать папку.

Запуск
------
    .venv\Scripts\python.exe tools\make_lora_dataset.py --check
    .venv\Scripts\python.exe tools\make_lora_dataset.py --tag ohwx
    .venv\Scripts\python.exe tools\make_lora_dataset.py --zip
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Куда кладутся картинки персонажа и подписи к ним.
CHAR_DIR = ROOT / "character" / "dataset"

#: Слово-триггер. Оно попадает в начало каждой подписи и не
#: перемешивается с остальными тегами при подготовке к обучению.
DEFAULT_TAG = "ohwx"

#: Сколько примеров нужно для узнаваемого лица. Меньше десяти —
#: модель выучивает одежду и фон, а не человека; больше сорока на
#: бесплатном тарифе Colab обучение не помещается по времени.
MIN_IMAGES = 10
IDEAL_IMAGES = 20

#: Подписи к каждому ракурсу. Ключ — часть имени файла, значение —
#: описание того, что на картинке.
#:
#: Порядок описаний важен: сначала неизменная внешность, потом
#: переменная часть. Тренажёр запоминает различия между подписями, и
# если постоянное описание прыгает по местам, лицо «размывается».
CAPTIONS: dict[str, str] = {
    "portrait": "close-up portrait, looking at camera, calm neutral "
                "expression, studio lighting, soft gray background, "
                "sharp focus on eyes, detailed facial features",
    "neon": "medium shot, dark neon-lit cyberpunk alley at night, "
            "confident stance, slight smirk, futuristic glowing jacket, "
            "pink and cyan rim lighting, moody atmosphere",
    "fantasy": "full body shot, elegant flowing white silk dress, "
               "barefoot in a magical bioluminescent forest, soft morning "
               "light through glowing leaves, ethereal",
    "cafe": "over-the-shoulder shot, sitting at a table in a cozy vintage "
            "cafe, laughing, holding a cup of coffee, warm golden hour "
            "light, candid lifestyle photography",
    "action": "extreme low angle shot, running through a rainy city "
              "street, fierce determined expression, wet dark trench coat, "
              "splashing puddles, dramatic cinematic rain lighting",
    "space": "medium shot, futuristic white spacesuit, helmet held under "
             "arm, inside a spaceship cockpit, looking out the window at a "
             "distant galaxy, cool blue ambient lighting",
    "cliff": "profile shot, sitting on the edge of a rocky cliff over the "
             "ocean, melancholic expression, wind blowing hair, oversized "
             "knitted sweater, dramatic sunset lighting",
    "ball": "medium shot, dancing with a man in a black tuxedo in a "
            "luxurious ballroom, joyful expression, sparkling red evening "
            "gown, warm chandelier lighting, high society event",
    "fashion": "extreme macro close-up on face, high fashion editorial "
               "photography, fierce expression, avant-garde reflective "
               "sunglasses, harsh studio flash lighting, sharp shadows",
    "snow": "full body action shot, snowboarding down a steep snowy "
            "mountain slope, excited wide smile, bright modern winter "
            "sports gear, crisp winter sunlight, snow particles in air",
}

#: Неизменная часть описания: то, что делает все картинки одним и тем
#: же человеком. Копируется в каждую подпись дословно.
ANCHOR = ("25-year-old woman, shoulder-length wavy ash-blonde hair, "
          "striking bright piercing blue eyes, pale skin, "
          "small beauty mark under her left eye, "
          "black leather choker with a silver crescent moon pendant")

#: Подпись целиком: тег, затем неизменная внешность, затем ракурс.
#:
#: Порядок именно такой — тег первым (он не перемешивается), потом
#: постоянная часть (она должна стоять рядом, чтобы тренажёр видел
#: одинаковую структуру), потом переменная.
def caption_for(kind: str, tag: str) -> str:
    """Подпись для одного ракурса."""
    detail = CAPTIONS.get(kind, kind.replace("_", " "))
    return f"{tag}, {ANCHOR}, {detail}"


def find_images(folder: Path) -> list[Path]:
    """Картинки, пригодные для обучения.

    Отсутствующая папка даёт пустой список, а не исключение: проверка
    готовности должна уметь запускаться до того, как папка создана, и
    говорить, что делать, а не падать с `FileNotFoundError`.
    """
    if not folder.is_dir():
        return []
    wanted = {".png", ".jpg", ".jpeg", ".webp"}
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in wanted)


def kind_of(path: Path) -> str:
    """Ракурс из имени файла.

    Имя разбирается по известным словам, а не по номеру: после
    перемешивания файлов номера меняются, а слова остаются.

    Про цифры в имени
    -----------------
    Раньше незнакомое имя приводилось к буквам регуляркой `[^a-z]+`,
    и цифры в ней выбрасывались. Имя `0001.png` давало пустую строку,
    а `char_0003.png` — `char`, то есть тоже не то. Ни то, ни другое
    не ключ в CAPTIONS, поэтому описание ракурса подставлялось
    пустым.

    Это стоило дороже, чем выглядело. `build()` читает ракурс из имени
    и сам же переименовывает файлы в `0001.png`, `0002.png` — то есть
    на втором запуске он читает имена, которые создал на первом.
    Описание ракурса оттуда уже не извлекалось, и подпись писалась
    заново уже без него: оставалась внешность и пропадало то, чем
    картинки отличаются друг от друга. Датасет собирался, проверка
    проходила, тренажёр брал файлы — а модель выучивала одно лицо в
    одной позе. Причина выглядела как «неплохое качество».

    Теперь цифры сохраняются, а имя без известного слова возвращается
    как есть: лучше `0001`, чем пустая строка, по которой искать нечего.
    """
    name = path.stem.lower()
    for kind in CAPTIONS:
        if kind in name:
            return kind
    # Меняем только разделители. Пробелы и подчёркивания в имени
    # файла не встречаются, но на всякий случай приводим их к одному
    # виду, чтобы ключ можно было искать в CAPTIONS.
    cleaned = re.sub(r"[\s\-]+", "_", name).strip("_")
    return cleaned or name


def build(args: argparse.Namespace) -> int:
    """Переименовать и подписать."""
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"нет папки {folder}")
        return 2

    images = find_images(folder)
    if not images:
        print(f"в папке {folder} нет картинок. Сначала нарисуйте их: "
              "tools/make_images.py --set character")
        return 2

    print(f"картинок: {len(images)}")
    if len(images) < MIN_IMAGES:
        print(f"\nмало для узнаваемого лица: нужно от {MIN_IMAGES}, "
              f"лучше {IDEAL_IMAGES}.")
        print("Лицо выучится по одежде и фону, а не по человеку.")

    written = 0
    kept = 0
    for number, image in enumerate(images, 1):
        kind = kind_of(image)
        # Единое имя для пары картинка+подпись: тренажёр сопоставляет
        # их по имени файла, и разные имена означают потерянную связь.
        base = f"{number:04d}"
        target = folder / f"{base}.png"
        caption_path = folder / f"{base}.txt"

        # Подпись, написанную ранее, не переписываем заново.
        #
        # Зачем. На втором запуске файлы уже называются `0001.png`, и
        # ракурс из имени уже не выводится — в имени нет слова,
        # остались цифры. Переписать подпись в этом случае нельзя:
        # на её месте окажется либо пустота, либо сам номер файла, и
        # описание ракурса пропадёт навсегда, потому что исходное имя
        # с ракурсом уже переименовано. Старая подпись — единственная
        # копия описания, и она верная.
        #
        # Дословная проверка вместо «файл есть»: подпись, созданная
        # пустой, должна быть дописана, а не оставлена как есть.
        if caption_path.is_file() and caption_path.read_text(
                encoding="utf-8").strip():
            if kind in CAPTIONS or not getattr(args, "force", False):
                kept += 1
                if image != target:
                    image.replace(target)
                continue

        if image != target:
            image.replace(target)
        caption_path.write_text(
            caption_for(kind, args.tag) + "\n", encoding="utf-8")
        written += 1

    if kept:
        print(f"подписей сохранено без изменений: {kept}")
    print(f"подписей записано: {written}")
    print(f"тег: {args.tag}")
    if args.zip:
        archive = make_zip(folder, args.zip)
        print(f"архив: {archive} "
              f"({archive.stat().st_size / 1024 / 1024:.1f} МБ)")
    return 0


def check(folder: Path) -> int:
    """Проверить готовность датасета."""
    images = find_images(folder)
    if not images:
        print(f"нет картинок в {folder}")
        print("Папки может не быть — создайте её и нарисуйте персонажа:\n"
              "  .venv\\Scripts\\python.exe tools\\make_images.py "
              "--set character")
        return 1

    lonely_images: list[str] = []
    lonely_caps: list[str] = []
    for image in images:
        if not image.with_suffix(".txt").is_file():
            lonely_images.append(image.name)

    stems = {p.stem for p in images}
    for text in sorted(folder.glob("*.txt")):
        if text.stem not in stems:
            lonely_caps.append(text.name)

    print(f"картинок: {len(images)}")
    print(f"подписей: {len(list(folder.glob('*.txt')))}")
    print(f"без подписи: {len(lonely_images)}")
    print(f"подписей без картинки: {len(lonely_caps)}")
    if lonely_images:
        print("  " + ", ".join(lonely_images[:8]))
    if lonely_caps:
        print("  " + ", ".join(lonely_caps[:8]))
    if lonely_images or lonely_caps:
        print("\nТренажёр такие файлы пропустит молча. Дозаполнить: "
              "tools/make_lora_dataset.py --tag ohwx")
        return 1

    sample = sorted(folder.glob("*.txt"))[0]
    print(f"\nпример подписи ({sample.name}):\n  {sample.read_text(encoding='utf-8').strip()}")
    if len(images) < MIN_IMAGES:
        print(f"\nОсторожно: {len(images)} из {MIN_IMAGES}. Лицо может "
              "не узнаваться.")
    return 0


def make_zip(folder: Path, name: str) -> Path:
    """Архив для загрузки в Colab.

    Отдельный архив нужен, потому что в Drive загружать сотни мелких
    файлов медленно: один zip копируется за секунды, а файлы по
    одному — за минуты.

    В архив кладутся только пары «картинка + подпись с тем же именем»
    ---------------------------------------------------------
    Раньше в архив попадал любой файл с расширением `.txt`. Заметка
    рядом с датасетом — обычное дело (`notes.txt`, `readme.txt`), и она
    уезжала в Colab вместе с данными. Тренажёр сверяет подпись с
    картинкой по имени: лишнего `notes.txt` он не найдёт и не
    откажется, а просто примёт его за описание картинки, которой нет.

    Проверка на самом деле о таком файле сообщает, но в архив он всё
    равно попадал: `check()` и `make_zip()` смотрели на папку
    по-разному. Отсюда расхождение — «проверка чистая, а в архиве
    мусор».

    Поэтому имена берутся у картинок, и `.txt` добавляется только
    если картинка с таким именем действительно есть.
    """
    target = folder.parent / f"{name}.zip"

    images = find_images(folder)
    # Имена картинок без расширения: по ним ищем подпись.
    stems = {p.stem for p in images}

    written = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for item in images:
            bundle.write(item, arcname=f"dataset/{item.name}")
            written += 1
            caption = item.with_suffix(".txt")
            if caption.is_file():
                bundle.write(caption, arcname=f"dataset/{caption.name}")
                written += 1

    # Считаем и показываем, что осталось за бортом: молча выкинутый
    # файл выглядит как «сборщик сломался», а не как «лишнее убрано».
    skipped = sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() == ".txt" and p.stem not in stems)
    if skipped:
        print(f"в архив не взято (нет картинки с таким именем): "
              f"{', '.join(skipped)}")

    print(f"в архиве файлов: {written}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(
        description="собрать датасет для LoRA")
    parser.add_argument("--folder", default=str(CHAR_DIR),
                        help="папка с картинками")
    parser.add_argument("--tag", default=DEFAULT_TAG,
                        help="активационный тег в начале подписей")
    parser.add_argument("--check", action="store_true",
                        help="только проверить готовность")
    parser.add_argument("--zip", nargs="?", const="lora-dataset",
                        help="упаковать датасет для Colab")
    parser.add_argument("--force", action="store_true",
                        help="переписать подписи даже там, где они уже есть")
    args = parser.parse_args()

    folder = Path(args.folder)
    if args.check:
        return check(folder)
    return build(args)


if __name__ == "__main__":
    sys.exit(main())