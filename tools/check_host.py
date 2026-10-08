r"""Проверить все страницы проекта на хостинге и отдать ссылки.

Зачем
----
Витрина обещает 52 страницы, а живут они по-разному: часть лежит в
корне сайта, часть — в папках, портфолио выкладывает отдельный
загрузчик. Проверять их вручную по одной — двадцать минут, и
пропустится ровно одна.

Проверка идёт по-настоящему: страница считается живой, если отдаёт
200 и в теле есть признак страницы, а не заглушки хостинга. У uCoz
заглушка отдаёт 200 с текстом «default welcome page», и по одному
коду такая страница прошла бы незамеченной.

Что проверяется по каждому адресу
---------------------------------
* код ответа;
* длина тела — слишком короткая страница это подозрительно;
* заглушка хостинга;
* для страниц с картинками — что файлы рядом тоже отдаются.

Запуск:
    .venv\\Scripts\\python.exe tools\\check_host.py
    .venv\\Scripts\\python.exe tools\\check_host.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS_JSON = ROOT / "site" / "assets" / "shots" / "shots.json"

BASE = "https://zagent.do.am"

#: Признаки заглушки хостинга. Проверяются в теле ответа.
PLACEHOLDERS = (
    "default welcome page",
    "pythonanywhere hosted web application",
    "Page not found",
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

#: Минимальная длина настоящей страницы. Короткая — это заглушка или
#: пустая папка, а не страница.
MIN_BYTES = 300


def load_catalog() -> list[str]:
    """Адреса из готового каталога: один источник, а не список руками."""
    catalog = ROOT / "site" / "catalog.html"
    if not catalog.is_file():
        return []
    import re
    body = catalog.read_text(encoding="utf-8")
    hrefs = re.findall(r'<a class="card[^>]*href="(/[^"]*)"', body)
    out: list[str] = []
    for item in hrefs:
        path = item.rstrip("/")
        if path and path not in out:
            out.append(path)
    return out


def check(path: str) -> dict:
    url = BASE + path if path.startswith("/") else BASE + "/" + path
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            raw = answer.read()
            status = answer.status
    except urllib.error.HTTPError as exc:
        return {"path": path, "status": exc.code, "bytes": 0,
                "note": "отказ сервера"}
    except Exception as exc:
        return {"path": path, "status": 0, "bytes": 0,
                "note": f"{type(exc).__name__}"}

    text = raw.decode("utf-8", "replace")
    note = ""
    if any(marker in text for marker in PLACEHOLDERS):
        note = "ЗАГЛУШКА ХОСТИНГА"
    elif len(raw) < MIN_BYTES:
        note = f"слишком короткая ({len(raw)} Б)"

    return {"path": path, "status": status, "bytes": len(raw), "note": note}


def main() -> int:
    parser = argparse.ArgumentParser(description="проверка страниц")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = load_catalog()
    if not paths:
        print("каталог не собран — запустите tools/make_catalog.py")
        return 1

    results = [check(p) for p in paths]

    # Превью каталога: снимки лежат на сервере, значит и они должны
    # открываться. Битое превью выглядит как пустая рамка в витрине.
    shots = []
    if SHOTS_JSON.is_file():
        try:
            index = json.loads(SHOTS_JSON.read_text(encoding="utf-8"))
        except ValueError:
            index = {}
        # Путь без `assets/`: сборщик сплющивает `assets/` в корень, и
        # правило REWRITES переписывает ссылки в каталоге на `shots/`.
        # Проверка шла по `assets/shots/` и честно рапортовала 404 на
        # файлах, которые лежат рядом с корнем — то есть ругалась не
        # на сайт, а сама на себя.
        shots = [f"/shots/{v['file']}" for v in index.values()
                 if v.get("file")]
    shots_result = [check(p) for p in shots]

    ok = [r for r in results if r["status"] == 200 and not r["note"]]
    bad = [r for r in results if r not in ok]
    shots_bad = [r for r in shots_result if r["status"] != 200 or r["note"]]

    if args.json:
        print(json.dumps({"pages": results, "shots": shots_result},
                         ensure_ascii=False, indent=1))
        return 0

    total_kb = sum(r["bytes"] for r in results) / 1024
    print(f"страниц проверено: {len(results)}")
    print(f"живых: {len(ok)}   с проблемами: {len(bad)}")
    print(f"объём: {total_kb / 1024:.1f} МБ")
    print(f"превью проверено: {len(shots_result)}   битых: {len(shots_bad)}")
    print()

    if bad:
        print("С ПРОБЛЕМАМИ:")
        for r in bad:
            print(f"  {r['status'] or '---'}  {r['path']}  {r['note']}")
        print()
    if shots_bad:
        print("БИТЫЕ ПРЕВЬЮ:")
        for r in shots_bad:
            print(f"  {r['status']}  {r['path']}")

    print("=" * 66)
    print("ССЫЛКИ")
    print("=" * 66)
    for r in results:
        mark = " " if r in ok else "!"
        print(f"{mark} {BASE}{r['path']:<24} {r['status']}  "
              f"{r['bytes'] / 1024:>7.0f} КБ  {r['note']}")

    return 1 if (bad or shots_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
