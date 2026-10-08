r"""Дополнить карту проектов новыми папками: радио, веб, проекты.

Зачем
----
`ПРОЕКТЫ.md` писался до того, как появились `radio/`, `web/` и
самостоятельные `bots/`, `sites/`, `utils/`. Карта устарела и
описывала раскладку, которой больше нет.

Что дописывается
----------------
* раздел про отдельные проекты с инструкциями;
* раздел про радио — с готовой строкой для вставки на сайт;
* раздел про веб-часть — с объяснением, почему три папки стали
  одной.

Запуск:
    .venv\\Scripts\\python.exe tools\\update_projects_map.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "ПРОЕКТЫ.md"

PROJECTS_SECTION = """## Отдельные проекты

Каждый запускается сам и в репозиторий не идёт: в трёх из них лежат
ключи, а остальные — производные копии.

| Папка | Что это | Инструкция |
|---|---|---|
| `bots/` | три бота в Telegram, с ключами и токенами | `bots/ИНСТРУКЦИЯ.md` |
| `radio/` | радио: плеер, 37 станций, скрипт для сайтов | `radio/ЧТО-ЗДЕСЬ.md` |
| `sites/` | копия сайтов и портфолио | `sites/ЧТО-ЗДЕСЬ.md` |
| `utils/` | утилиты, каждая в своей папке | `utils/ЧТО-ЗДЕСЬ.md` |
| `web/` | плеер Flash | `web/ЧТО-ЗДЕСЬ.md` |

### Почему эти папки не в git

В `bots/` лежат токены трёх ботов и ключи моделей. Ключ в
репозитории достаточно одного неверного `git add .`, и отменить это
нельзя — история помнит всё. Настоящие файлы бота при этом в
репозитории есть: `hosting/pythonanywhere/bots/`.

## Радио

Радио размазано было по шести местам. Собрано в `radio/`.

Чтобы поставить радио на любой сайт, нужна одна строка:

```html
<iframe src="/radio-widget.html" width="320" height="420"
        style="border:0;border-radius:12px"></iframe>
```

Пока подключена одна страница — в `site/SVADBA`. Остальные 51 без
него; скрипт уже готов, подключение сводится к одной строке.

## Веб-часть

`web/` — плеер Flash на Ruffle и его состояние. Раньше это были три
папки: `web/`, `web-state/` и `web-static/`, и ни одна из них не
запускалась сама. Теперь это одна папка с понятными подпапками.
"""

OLD_SERVICE = "## Служебное"


def main() -> int:
    if not MAP.is_file():
        print("карта проектов не найдена", file=sys.stderr)
        return 1
    text = MAP.read_text(encoding="utf-8")

    if "## Отдельные проекты" not in text:
        text = text.replace(OLD_SERVICE, PROJECTS_SECTION + "\n\n"
                            + OLD_SERVICE, 1)
        MAP.write_text(text, encoding="utf-8")
        print(f"  карта дополнена, {len(text)} символов")
    else:
        print("  карта уже дополнена")

    # Проверка: все папки из карты существуют.
    print()
    print("=== папки из карты ===")
    for name in ("bots", "radio", "sites", "utils", "web", "hub",
                 "tools", "tests", "site", "portfolios", "hosting"):
        mark = "ок  " if (ROOT / name).is_dir() else "НЕТ "
        print(f"  {mark} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())