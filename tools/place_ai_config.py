r"""Положить настройки виджета агента рядом с каждой страницей.

Зачем
----
Виджет на всех страницах один, а адрес прокси у них общий. Но файл
`ai.json` должен лежать рядом с каждой страницей: страницы лежат в
разных папках, а внешних адресов на хостинге быть не может — значит
и настройки приходится дублировать.

Почему адрес пустой по умолчанию
--------------------------------
Виджет с пустым адресом не показывает кнопку вовсе. Это честнее формы,
которая отправляет вопрос в никуда: посетитель видит, что помощника
сейчас нет, а не получает «ошибка сети» через двадцать секунд ожидания.

Запуск:
    .venv\Scripts\python.exe tools\place_ai_config.py
    .venv\Scripts\python.exe tools\place_ai_config.py --endpoint https://.../chat
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Куда кладём. Главная и каталог собираются в site-dist, подачи
#: выкладываются своими папками.
#:
#: Подпапки страниц тоже нужны: виджет ищет настройки рядом с собой,
#: и без своей копии он просто молча не появляется. Раньше список знал
#: только про корень и подачи портфолио, из-за чего папки с гайдами и
#: лендингом остались без настроек — страница выглядела целой, а
#: кнопка не показывалась.
TARGETS: tuple[Path, ...] = (
    ROOT / "site-dist",
    ROOT / "site-dist" / "guide",
    ROOT / "site-dist" / "tex",
    ROOT / "site" / "guide",
    ROOT / "site" / "tex",
    ROOT / "site" / "barbie",
    ROOT / "site" / "tovar",
    ROOT / "site-dist" / "barbie",
    ROOT / "site-dist" / "tovar",
    # Пять рекламных витрин. Виджет на них подключается сборщиком
    # (он кладёт `ai.js` и `ai.css` в каждую папку из KEEP_FOLDERS),
    # а настроек рядом не было: файл ищется виджетом по своему адресу,
    # не нашёлся — и кнопка не показывалась. Страница при этом
    # выглядела целой, то есть поломка была невидимая.
    ROOT / "site" / "forno",
    ROOT / "site" / "dentalia",
    ROOT / "site" / "vow",
    ROOT / "site" / "grind",
    ROOT / "site" / "strobe",
    ROOT / "site-dist" / "forno",
    ROOT / "site-dist" / "dentalia",
    ROOT / "site-dist" / "vow",
    ROOT / "site-dist" / "grind",
    ROOT / "site-dist" / "strobe",
    # Витрина хиромантии. Виджет на неё кладёт сборщик, а настроек
    # рядом не было — как и с пятью рекламными: файл ищется виджетом
    # по своему адресу, не нашёлся, кнопка не показалась, страница
    # выглядела целой.
    ROOT / "site" / "palm",
    ROOT / "site-dist" / "palm",
    # --- папки макетов из demo (вставляется register_folders.py) ---
    ROOT / "site" / "aetheris",
    ROOT / "site" / "auraspin",
    ROOT / "site" / "academy",
    ROOT / "site" / "palmistry",
    ROOT / "site" / "palmchart",
    ROOT / "site" / "shaurma",
    ROOT / "site" / "apex",
    ROOT / "site" / "zov",
    ROOT / "site" / "taiga",
    ROOT / "site" / "auratravel",
    ROOT / "site" / "cakes",
    ROOT / "site" / "realtravel",
    ROOT / "site" / "pizzafire",
    ROOT / "site" / "foodie",
    ROOT / "site" / "guardbase",
    ROOT / "site" / "modern",
    ROOT / "site" / "iskra",
    ROOT / "site" / "horology",
    ROOT / "site" / "lumiere3d",
    ROOT / "site" / "lumiere",
    ROOT / "site" / "nariaidy",
    ROOT / "site" / "naturespace",
    ROOT / "site" / "novastore",
    ROOT / "site" / "oboi",
    ROOT / "site" / "soramoku",
# --- конец папок макетов ---
    ROOT / "portfolios" / "aurum",
    ROOT / "portfolios" / "lumen",
    ROOT / "portfolios" / "onyx",
    ROOT / "portfolios" / "neon",
    ROOT / "portfolios" / "paper",
    ROOT / "portfolios" / "term",
    ROOT / "portfolios" / "steel",
)

#: Исходник, из которого берутся подписи по умолчанию. Виджет всё равно
#: переопределяет имя и роль из meta-тега страницы, но поле greeting
#: читается только здесь, поэтому текст должен быть в файле.
SOURCE = ROOT / "site" / "assets" / "ai.json"


def build(endpoint: str) -> dict[str, object]:
    """Собрать содержимое ai.json."""
    try:
        base = json.loads(SOURCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        base = {}
    base["endpoint"] = endpoint
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description="настройки виджета агента")
    parser.add_argument("--endpoint", default="",
                        help="адрес прокси с /chat; пусто — виджет прячется")
    args = parser.parse_args()

    endpoint = args.endpoint.strip()
    if endpoint and not endpoint.endswith("/chat"):
        print("похоже, это не адрес маршрута: он должен кончаться на /chat",
              file=sys.stderr)

    payload = build(endpoint)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    written = 0
    for folder in TARGETS:
        if not folder.is_dir():
            print(f"нет папки {folder.relative_to(ROOT)} — пропускаю")
            continue
        (folder / "ai.json").write_text(text, encoding="utf-8")
        written += 1
        print(f"записан {folder.relative_to(ROOT) / 'ai.json'}")

    print(f"\nфайлов: {written}")
    if not endpoint:
        print("адрес пустой: кнопка помощника на страницах не показывается.")
        print("Появится, как только будет указан адрес прокси:")
        print("  .venv\\Scripts\\python.exe tools\\place_ai_config.py "
              "--endpoint https://.../chat")
    return 0


if __name__ == "__main__":
    sys.exit(main())