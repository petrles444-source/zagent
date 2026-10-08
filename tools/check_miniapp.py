r"""Проверить мини-приложение: голоса, шаги и отсутствие внешних адресов.

Зачем
----
Приложение держит список голосов у себя, в `app.js`, а настоящие
описания лежат в `tools/bot_proxy.py`. Это два места, и они молчат
друг о друге: если в проксе добавить голос, приложение продолжит
показывать старый список, и человек выберет одного из трёх, хотя
доступных стало четыре. Никакой ошибки при этом не возникает —
приложение работает, просто предлагает не то.

Поэтому ключи сверяются, а не «считаются правильными на глаз».

Что ещё проверяется
------------------
* каждый голос из прокси описан в приложении и наоборот;
* у голоса есть имя, описание и цвет — иначе карточка выйдет пустой;
* в разметке и в скрипте нет внешних адресов: приложение обязано
  открываться без сети, а официальный SDK Telegram грузится снаружи;
* три шага действительно три, и у каждого есть панель;
* в `index.html` нет `<script src>` на файл, которого нет рядом.

Запуск:
    .venv\Scripts\python.exe tools\\check_miniapp.py
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "site" / "tma"

#: Шаги, которые обязаны быть в приложении. Порядок важен: он же
#: задан в разметке атрибутом `data-pane`.
EXPECTED_PANES = ("0", "1", "2", "3")


def load_proxy_voices() -> dict[str, str]:
    """Достать голоса из прокси, не поднимая его целиком."""
    spec = importlib.util.spec_from_file_location(
        "check_bot_proxy", ROOT / "tools" / "bot_proxy.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_bot_proxy"] = module
    spec.loader.exec_module(module)
    return dict(module.VOICES)


def load_app_voices(js: str) -> dict[str, dict[str, str]]:
    """Разобрать список VOICES из скрипта приложения.

    Разбираем регулярками, а не через JS: node в проекте нет, а список
    объявлен литералом. Проверяется ровно то, что нужно, — ключи и
    обязательные поля, — без попытки выполнить чужой код.
    """
    block = re.search(r"var VOICES\s*=\s*\[(.*?)\n\];", js, re.DOTALL)
    if not block:
        return {}

    voices: dict[str, dict[str, str]] = {}
    for chunk in re.findall(r"\{(.*?)\}", block.group(1), re.DOTALL):
        def field(name: str) -> str:
            m = re.search(rf"\b{name}\s*:\s*'([^']*)'", chunk)
            return m.group(1) if m else ""

        key = field("key")
        if key:
            voices[key] = {
                "name": field("name"),
                "what": field("what"),
                "about": field("about"),
                "mark": field("mark"),
                "color": field("color"),
            }
    return voices


def main() -> int:
    problems: list[str] = []

    for item in ("index.html", "app.js", "style.css"):
        if not (APP / item).is_file():
            print(f"нет файла: {item}")
            return 1

    html = (APP / "index.html").read_text(encoding="utf-8")
    js = (APP / "app.js").read_text(encoding="utf-8")

    # 1. Голоса совпадают в обе стороны.
    try:
        proxy_voices = load_proxy_voices()
    except Exception as exc:
        print(f"не читаются голоса из прокси: {exc}")
        return 1

    app_voices = load_app_voices(js)
    if not app_voices:
        problems.append("в app.js не разобран список VOICES — "
                        "формат изменился, проверку надо поправить")

    only_proxy = sorted(set(proxy_voices) - set(app_voices))
    only_app = sorted(set(app_voices) - set(proxy_voices))

    for key in only_proxy:
        problems.append(f"голос {key!r} есть в прокси, но его нет в "
                        f"приложении — человек не сможет его выбрать")
    for key in only_app:
        problems.append(f"голос {key!r} есть в приложении, но его нет "
                        f"в прокси — прокси подставит голос по умолчанию "
                        f"и ответит не тем")

    # 2. У каждого голоса заполнены карточка и цвет.
    for key, fields in sorted(app_voices.items()):
        for name in ("name", "what", "about", "mark", "color"):
            if not fields.get(name):
                problems.append(f"у голоса {key!r} пустое поле {name!r}")
        if fields.get("color") and not re.fullmatch(
                r"#[0-9a-fA-F]{6}", fields["color"]):
            problems.append(f"у голоса {key!r} цвет не в #rrggbb: "
                            f"{fields['color']!r}")

    # 3. Панели шагов.
    panes = re.findall(r'data-pane="(\d+)"', html)
    if tuple(panes) != EXPECTED_PANES:
        problems.append(f"панели шагов {panes} ожидались "
                        f"{list(EXPECTED_PANES)}")

    # 4. Внешних адресов быть не должно.
    for name, text in (("index.html", html), ("app.js", js)):
        found = re.findall(r'(?:src|href)="https?://[^"]+', text)
        for item in found:
            problems.append(f"{name}: внешняя загрузка {item}")
        # В тексте скрипта допустимо упоминать telegram.org в комментарии,
        # но не в загружаемом адресе — выше проверяется именно src/href.
    for name, text in (("index.html", html), ("app.js", js)):
        for url in re.findall(r"['\"](https?://[^'\"]+)['\"]", text):
            problems.append(f"{name}: внешний адрес в коде {url}")

    # 5. Все файлы, на которые ссылается разметка, есть рядом.
    for ref in re.findall(r'(?:src|href)="([A-Za-z0-9_./-]+)"', html):
        if ref.startswith("data:") or ref.startswith("/"):
            continue
        if not (APP / ref).is_file():
            problems.append(f"index.html ссылается на отсутствующий {ref}")

    # 6. Идентификаторы, которые скрипт ищет, есть в разметке.
    html_ids = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', html))
    used = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", js))
    for name in sorted(used - html_ids):
        problems.append(f"скрипт ищет #{name}, которого нет в разметке")

    print(f"голосов в прокси: {len(proxy_voices)}")
    print(f"голосов в приложении: {len(app_voices)}")
    print(f"панелей шагов: {len(panes)}")
    print()

    if problems:
        print(f"НАЙДЕНО ПРОБЛЕМ: {len(problems)}")
        for item in problems:
            print(f"  - {item}")
        return 1

    print("мини-приложение в порядке: голоса совпадают, внешних загрузок нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
