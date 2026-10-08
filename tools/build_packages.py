r"""Собрать готовые решения в zip-архивы для раздачи.

Зачем
-----
Каждая находка в проекте — это отдельный законченный инструмент: его
можно взять и сразу использовать. Такие вещи и раздаются: не «исходники
проекта», а пакет с одним инструментом, инструкцией и лицензией.

Что важно в сборке
------------------
* **Секреты не попадают в архив.** Перед упаковкой каждый файл
  проверяется: ключ, токен или пароль внутри означают, что пакет
  переписывается с красной строкой. Так однажды уедет ключ к модели,
  и его увидят все, кто скачает.
* **Ничего лишнего.** В архив идут только файлы пакета плюс
  `README.md` и `LICENSE`. Никаких `.venv`, кэшей и чужих правок.
* **Воспроизводимость.** Сборка идёт из одного места, состав пакета
  описан в коде: через полгода не придётся по архиву вспоминать, что
  туда клали.

Запуск:
    .venv\Scripts\python.exe tools\build_packages.py
    .venv\Scripts\python.exe tools\build_packages.py --out publish
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: Признаки секретов. Ловятся не слова, а значения: присваивание,
#: после которого идёт длинная строка без пробелов.
#:
#: В «хвосте» важно не ограничиваться буквами и цифрами. Настоящий ключ
#: выглядит так: `sk_live_rOWU5DOv_yy3inkj4TQ-JbaZAEaH2…` — там есть и
#: подчёркивание, и дефис. Шаблон `[A-Za-z0-9]{10,}` на таком ключе
#: обрывался после первых восьми символов и молчал, а ловить надо
#: именно его. Поэтому хвост — любой набор без пробелов: `\S`.
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"sk_live_\S{16,}", "ключ провайдера (sk_live)"),
    (r"sk-\S{20,}", "ключ провайдера (sk-)"),
    (r"gsk_\S{20,}", "ключ groq"),
    (r"nvapi-\S{16,}", "ключ nvidia"),
    (r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b", "токен телеграм-бота"),
    (r"['\"]?api_key['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}", "api_key в коде"),
    (r"(?i)authorization['\"]?\s*[:=]\s*['\"]\s*(?:token|bearer)\s+[A-Za-z0-9]{20,}",
     "заголовок Authorization с токеном"),
    (r"(?i)['\"]?(?:token|password|passwd)['\"]?\s*[:=]\s*['\"][^'\"\s]{12,}",
     "токен или пароль в значении"),
)

#: Описания пакетов. Ключ — имя архива, значение — что и откуда берётся.
PACKAGES: dict[str, dict[str, Any]] = {
    "zradio": {
        "title": "zradio — радиоклиент с окном и консолью",
        "summary": "Радио в консоли и в окне: 37 станций, пинг доступности, "
                   "воспроизведение через WMP ActiveX, переключение и "
                   "громкость. Окно прячется и возвращается командой.",
        "tags": "Python, Windows, радио, CLI, tkinter",
        "files": [
            "tools/zradio.py",
            "tools/zradio.cs",
            "tools/build_zradio.bat",
            "music/stations.json",
        ],
        "notes": [
            "Нужен Windows и WMP ActiveX (в современных сборках Windows "
            "он уже есть). Python — только стандартная библиотека.",
            "Запуск: python tools\\zradio.py, окно прячется кнопкой и "
            "возвращается командой show в консоли.",
        ],
    },
    "ada-telegram-bot": {
        "title": "Ада — телеграм-бот, отвечающий на имя и на каждое 10-е сообщение",
        "summary": "Бот-помощница для личных чатов и бесед: откликается на "
                   "«Ада» в любом написании, в беседе вмешивается в каждое "
                   "десятое сообщение, помнит ход разговора и отвечает через "
                   "модель. Работает на любом Python-хостинге.",
        "tags": "Python, Telegram, бот, ИИ, stdlib",
        "files": [
            "hosting/pythonanywhere/bots/ada_bot.py",
            "hosting/pythonanywhere/bots/config.example.json",
            "hosting/pythonanywhere/pa_api.py",
            "hosting/pythonanywhere/deploy.py",
            "hosting/pythonanywhere/make_bot_config.py",
            "hosting/pythonanywhere/tools/selfcheck.py",
            "hosting/pythonanywhere/tools/reach.py",
            "hosting/pythonanywhere/tools/poll_probe.py",
            "tests/test_ada_bot.py",
        ],
        "notes": [
            "Ничего доустанавливать не нужно — только стандартная "
            "библиотека Python 3.9+.",
            "Сначала создай бота у @BotFather и выключи приватность "
            "(/setprivacy → Disable), иначе в беседе он увидит только "
            "реплики с упоминанием.",
            "В комплекте замеры: reach.py покажет, какие адреса доступны с "
            "хостинга, poll_probe.py — какой длинный опрос проходит.",
        ],
    },
    "site-assistant-proxy": {
        "title": "Прокси помощника для сайта: ключи остаются на сервере",
        "summary": "Серверный ключ нельзя отдавать странице: его заберёт тот, "
                   "кто откроет инструменты разработчика. Прокси держит ключ "
                   "у себя, наружу отдаёт один маршрут с проверкой источника, "
                   "лимитом запросов и обрезкой истории.",
        "tags": "Python, безопасность, прокси, ИИ, API",
        "files": [
            "tools/bot_proxy.py",
            "tests/test_bot_proxy.py",
        ],
        "notes": [
            "Рассчитан на то, что агент (127.0.0.1) не выставлен наружу: "
            "наружу смотрит только прокси.",
            "Проверка источника — не защита от curl, поэтому лимит запросов "
            "обязателен: без него один человек выжигает квоту за ночь.",
        ],
    },
    "swf-generator": {
        "title": "Генератор .swf — настоящие флеш-файлы из кода",
        "summary": "Собирает корректные несжатые .swf прямо из Python: "
                   "заголовок, сцена, DefineShape, PlaceObject2, кадры. "
                   "Из них получаются анимации, которые играет Ruffle в "
                   "браузере. Ничего ставить не нужно.",
        "tags": "Python, SWF, Flash, Ruffle, бинарные форматы",
        "files": [
            "tools/make_demo_swf.py",
        ],
        "notes": [
            "Внутри разобраны все тонкости формата: выравнивание после "
            "RECT, порядок байт у 16-битных полей и 13-битные заголовки "
            "записей контура. Из-за этих мелочей файл либо работает, либо "
            "молча ломается.",
            "Запуск: python tools\\make_demo_swf.py",
        ],
    },
    "neural-archive-site": {
        "title": "Neural Archive — сайт-архив флеш-работ на Ruffle",
        "summary": "Готовый статический сайт: архив работ 1999–2010 с живым "
                   "воспроизведением через Ruffle, каталог с фильтрами, "
                   "загрузка .swf перетаскиванием. Всё локально — ни одного "
                   "внешнего адреса, работает без интернета.",
        "tags": "HTML, CSS, JavaScript, Ruffle, Flash, статический сайт",
        "files": [
            "site/index.html",
            "site/assets/style.css",
            "site/assets/chat.css",
            "site/assets/app.js",
            "site/assets/chat.js",
            "site/assets/catalog.json",
            # Живой конфиг с адресом туннеля в раздачу не идёт: он скоро
            # перестанет работать и рассказывает постороннему, где живёт
            # прокси. В пакете лежит пустой пример.
            "site/assets/config.example.json",
            "site/assets/fonts.css",
            "tools/build_site.py",
            "tools/serve_site.py",
            "tools/make_demo_swf.py",
        ],
        "notes": [
            "Ruffle (28 МБ) в пакет не входит: он и так лежит отдельно, "
            "положите папку ruffle рядом с index.html.",
            "Шрифты лежат в assets/fonts. Сборщик build_site.py "
            "выкладывает сайт плоско — под хостингы, где нельзя создавать "
            "папки по FTP.",
        ],
    },
    "radio-stations-list": {
        "title": "Список радиостанций — 37 работающих потоков",
        "summary": "Готовый список станций в JSON: имя, жанр, адрес потока, "
                   "плюс три личные станции. Годится как входные данные для "
                   "плеера, для пинга доступности и для каталога.",
        "tags": "JSON, радио, потоки, данные",
        "files": ["music/stations.json"],
        "notes": [
            "Проверен 7 октября 2026: адреса отвечают. Со временем часть "
            "потоков может устареть — это нормально для живого эфира.",
        ],
    },
}

LICENSE_TEXT = """MIT License

Copyright (c) 2026 zagent

Настоящим предоставляется бесплатное разрешение любому лицу, получившему
копию настоящего программного обеспечения и сопутствующей документации
(«Программное обеспечение»), использовать Программное обеспечение без
ограничений, включая право использования, копирования, изменения,
слияния, публикации, распространения, сублицензирования и продажи копий
Программного обеспечения, при условии, что в вышеуказанном уведомлении
оно сохраняется.

ПРОГРАММНОЕ ОБЕСПЕЧЕНИЕ ПРЕДОСТАВЛЯЕТСЯ «КАК ЕСТЬ», БЕЗ КАКИХ-ЛИБО
ГАРАНТИЙ. АВТОР НЕ НЕСЁТ ОТВЕТСТВЕННОСТИ ПО ПРЕТЕНЗИЯМ, ВОЗНИКШИМ ИЗ
ИСПОЛЬЗОВАНИЯ ПРОГРАММНОГО ОБЕСПЕЧЕНИЯ ИЛИ ИНЫХ ДЕЙСТВИЙ С НИМ.
"""


def find_secrets(text: str, name: str) -> list[str]:
    """Найти в тексте секреты. Возвращает описания, что нашлось."""
    hits: list[str] = []
    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, text):
            hits.append(f"{name}: {label}")
    return hits


def readme_for(key: str, spec: dict[str, Any]) -> str:
    """Текст инструкции к пакету."""
    lines = [
        f"# {spec['title']}",
        "",
        spec["summary"],
        "",
        "## Что внутри",
        "",
    ]
    for item in spec["files"]:
        lines.append(f"- `{Path(item).name}`")
    lines += ["", "## Заметки", ""]
    for note in spec["notes"]:
        lines.append(f"- {note}")
    lines += [
        "",
        "## Требования",
        "",
        "- Python 3.9 или новее — и всё. Внешних пакетов нет.",
        "- Проверено 7 октября 2026.",
        "",
        "## Лицензия",
        "",
        "MIT (файл LICENSE). Код можно брать, менять и применять.",
        "Если он вам пригодился — упомяните источник, это единственная",
        "просьба.",
        "",
        f"Теги: {', '.join(spec['tags'])}",
        "",
    ]
    return "\n".join(lines)


def build_package(key: str, spec: dict[str, Any], out_dir: Path,
                  staging: Path) -> dict[str, Any]:
    """Собрать один архив. Возвращает отчёт для вывода."""
    work = staging / key
    work.mkdir(parents=True, exist_ok=True)

    problems: list[str] = []
    added: list[str] = []
    for relative in spec["files"]:
        source = ROOT / relative
        if not source.is_file():
            problems.append(f"нет файла {relative}")
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        hits = find_secrets(text, relative)
        if hits:
            problems.extend(hits)
            continue
        target = work / Path(relative).name
        shutil.copy2(source, target)
        added.append(target.name)

    if problems:
        shutil.rmtree(work, ignore_errors=True)
        return {"key": key, "ok": False, "problems": problems}

    (work / "README.md").write_text(readme_for(key, spec), encoding="utf-8")
    (work / "LICENSE").write_text(LICENSE_TEXT, encoding="utf-8")
    added += ["README.md", "LICENSE"]

    # Повторная проверка: инструкция пишется нами, но в неё могли
    # случайно попасть примеры с настоящими значениями.
    for item in sorted(work.iterdir()):
        hits = find_secrets(item.read_text(encoding="utf-8", errors="replace"),
                            item.name)
        if hits:
            problems.extend(hits)
    if problems:
        shutil.rmtree(work, ignore_errors=True)
        return {"key": key, "ok": False, "problems": problems}

    archive = out_dir / f"{key}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(work.iterdir()):
            zf.write(item, arcname=f"{key}/{item.name}")
    shutil.rmtree(work, ignore_errors=True)
    return {"key": key, "ok": True, "archive": archive,
            "files": added, "size": archive.stat().st_size,
            "title": spec["title"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="собрать пакеты для раздачи")
    parser.add_argument("--out", default="publish",
                        help="куда класть архивы (по умолчанию publish)")
    parser.add_argument("--only", help="собрать только этот пакет")
    args = parser.parse_args()

    out_dir = ROOT / args.out
    staging = ROOT / "tmp" / "packages"
    for path in (out_dir, staging):
        path.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    report: list[dict[str, Any]] = []
    for key, spec in PACKAGES.items():
        if args.only and key != args.only:
            continue
        report.append(build_package(key, spec, out_dir, staging))

    shutil.rmtree(staging, ignore_errors=True)
    index: list[dict[str, Any]] = []
    print(f"{'пакет':22} {'файлов':>7} {'размер':>10}  название")
    for item in report:
        if not item["ok"]:
            print(f"{item['key']:22} {'—':>7} {'НЕ СОБРАН':>10}")
            for problem in item["problems"]:
                print(f"    {problem}")
            continue
        print(f"{item['key']:22} {len(item['files']):>7} "
              f"{item['size'] / 1024:>8.0f} КБ  {item['title']}")
        index.append({"id": item["key"], "title": item["title"],
                      "summary": PACKAGES[item["key"]]["summary"],
                      "tags": PACKAGES[item["key"]]["tags"],
                      "file": item["archive"].name,
                      "kb": round(item["size"] / 1024, 1)})

    (out_dir / "catalog.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "LICENSE").write_text(LICENSE_TEXT, encoding="utf-8")

    failed = [item for item in report if not item["ok"]]
    print(f"\nготово: {len(index)} пакетов, каталог — {out_dir / 'catalog.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
