r"""Разобрать папку `character/`: что перенести, что убрать.

Зачем
-----
В корне проекта была папка `character`, сделанная вручную под телеграм-
ботов. В ней лежало:

* `ada/Ada.txt` — промпт Ады. Перенесён в `chars.py` целиком по
  смыслу: женский род, флирт, страх реальной встречи, противоречие
  «в коде жёсткая — в личном смущённая»;
* `anatoly/anatoly_character_prompt.txt` — промпт Анатолия с режимами
  `/ада`, `/лох`, `/про`, `/больше`. Перенесены в `chars.py` как
  переключатели `простыми словами`, `строгий`, `максимум`. Режим,
  названный в оригинале «Ада», переименован: так зовут бота, и
  команда `/ада` у Анатолия читалась как «переключись в Аду»;
* `anatoly/anatoly_bot.py` — отдельный консольный контроллер на
  библиотеке `openai` с ключом `OPENAI_API_KEY`. Он давно вытеснен
  `ada_bot.py`: там три бота, повторяющиеся обрывы, первичная логика
  и настройка характера. Своих уникальных идей в нём не осталось;
* `anatoly/README_ANATOLY.md` — инструкция по установке `openai` и
  ключу. Ключа такого больше нет, инструкция не работает;
* `ada/*.png` — три картинки по 2 МБ. Это не контент бота, а
  референсы палитры: кинематографичная палитра «красный против
  бирюзового», цветотип и портрет. Бот их не показывает, но из
  первой выведены цвета персоны;
* `dataset/` — пустая;
* `__pycache__` — кэш от запуска того самого контроллера.

Что делается
------------
1. Картинки и исходные промпты складываются в
   `hosting/pythonanywhere/bots/character/` — рядом с ботами, а не
   отдельно в корне. Промпты остаются читаемыми: они длинные и
   переписываются руками при настройке характера.
2. `__pycache__` и `dataset` не переносятся.
3. Старый контроллер не переносится.

Запуск:
    .venv\\Scripts\\python.exe tools\\tidy_character.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "character"
DEST = ROOT / "hosting" / "pythonanywhere" / "bots" / "character"

#: Что переносим. Список явный, потому что «перенести всё» значило бы
#: утащить и кэш, и пустую папку.
KEEP_FILES = {
    "ada": ("Ada.txt",),
    "anatoly": ("anatoly_character_prompt.txt",),
}

#: Куда класть картинки и зачем.
PICTURES_NOTE = (
    "Картинки из character/ada — это референсы палитры Ады, а не её "
    "аватар:\n\n"
    "  * «Кинематографичная палитра_ красный против бирюзового.png» — "
    "из неё взяты цвета персоны (#3a1030 тёмный и #ff7ab8 акцент);\n"
    "  * «Цветотип_ палитра красного и сине-зелёного.png» — та же "
    "палитра в другом изложении;\n"
    "  * «ChatGPT Image ...png» — портрет.\n\n"
    "Аватар бота рисуется кодом из цветов персоны (`avatar_png`), "
    "поэтому эти файлы на Telegram не отправляются. Они нужны, "
    "когда приходится подбирать цвета заново.\n"
)


def main() -> int:
    if not OLD.is_dir():
        print("папки character нет — переносить нечего")
        return 0

    DEST.mkdir(parents=True, exist_ok=True)

    moved = 0
    for sub, names in KEEP_FILES.items():
        target = DEST / sub
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = OLD / sub / name
            if not src.is_file():
                print(f"  нет файла {sub}/{name} — пропускаю")
                continue
            shutil.move(str(src), str(target / name))
            moved += 1
            print(f"  перенесено character/{sub}/{name}")

    # Картинки: в отдельную папку с пояснением, чтобы никто не принял
    # их за аватары и не отправил боту.
    pics_src = OLD / "ada"
    pics_dest = DEST / "pictures-референсы"
    wanted = [p for p in pics_src.glob("*.png")] if pics_src.is_dir() else []
    if wanted:
        pics_dest.mkdir(parents=True, exist_ok=True)
        for pic in wanted:
            shutil.move(str(pic), str(pics_dest / pic.name))
            moved += 1
            print(f"  перенесено character/ada/{pic.name}")
        (pics_dest / "ЗАЧЕМ-ЭТО.txt").write_text(PICTURES_NOTE,
                                                 encoding="utf-8")
        print("  перенесено character/pictures-референсы/ЗАЧЕМ-ЭТО.txt")

    print()
    print(f"перенесено файлов: {moved}")
    print(f"из: {OLD}")
    print(f"в:  {DEST}")
    print()
    print("ВНИМАНИЕ: старая папка character НЕ удалена. Удалить её можно")
    print("только после проверки, что в новой папке всё на месте:")
    print(f"  {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())