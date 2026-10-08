r"""Скачать свободные картинки с Wikimedia Commons для витрины.

Зачем
----
Витрине портфолио нужны иллюстрации, а в проекте лежат только фотографии
людей. Берём их у Wikimedia Commons: лицензии там — public domain либо
CC, условия соблюдаются указанием автора, и у каждого файла есть точная
страница описания.

Почему через API, а не прямой адрес
-----------------------------------
`upload.wikimedia.org` отдаёт 400 на любую ширину, которой нет в
белом списке сервера, а хост для миниатюр у них — `thumb.wikimedia.org`.
Чтобы не гадать с размерами, спрашиваем у API готовый `thumburl` и берём
именно его: так запрос всегда корректен, а файл уже нужного размера.

Что сохраняется
---------------
Рядом с картинкой кладётся `credits.json` — по каждому снимку автор,
лицензия и страница описания. Это не украшение: без указания авторства
лицензия CC не соблюдена, а ссылка на источник нужна для проверки.

Запуск:
    .venv\Scripts\python.exe tools\fetch_stock.py --out tmp\stock --count 12
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

API = "https://commons.wikimedia.org/w/api.php"

#: Категории, из которых берём. Все они — свободные лицензии, и в них
#: нет фотографий людей: портреты в витрине проекта не выкладываются.
#: Список задан файлами, а не случайными запросами, поэтому результат
#: повторяем: те же категории дают те же снимки.
CATEGORIES = (
    "Category:Modern architecture",
    "Category:Glass architecture",
    "Category:Skyscrapers",
    "Category:Staircases",
    "Category:Light and shadow",
)

#: Ключевые слова, по которым отбираем файлы внутри категории.
KEYWORDS = (
    "glass", "steel", "facade", "staircase", "light", "interior",
    "stair", "skyscraper", "concrete", "atrium",
)

#: Сколько снимков на каждую категорию. Меньше неинтересно, больше —
#: страница перестаёт читаться.
PER_CATEGORY = 3

#: Ширина, которую сервер отдаёт без вопросов: любая из белого списка.
THUMB_WIDTH = 320


def get_json(params: dict[str, str]) -> dict:
    """Запрос к API Commons. Возвращает разобранный ответ."""
    query = urllib.parse.urlencode({**params, "format": "json"})
    request = urllib.request.Request(
        API + "?" + query,
        headers={"User-Agent": "zagent-portfolio/1.0 (учебный проект)"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def list_files(category: str, limit: int) -> list[str]:
    """Названия файлов в категории, отобранные по ключевым словам."""
    data = get_json({
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "file",
        "cmlimit": "120",
    })
    members = (data.get("query") or {}).get("categorymembers") or []
    picked = [m["title"] for m in members
              if any(word in m["title"].lower() for word in KEYWORDS)]
    if not picked:
        picked = [m["title"] for m in members]
    return picked[:limit]


def file_info(title: str) -> dict | None:
    """Автор, лицензия и готовая ссылка на миниатюру."""
    data = get_json({
        "action": "query",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": str(THUMB_WIDTH),
    })
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [None])[0]
        if info:
            return info
    return None


def plain(value: str) -> str:
    """Убрать html-разметку из строки лицензии и снять лишние пробелы."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value or "")).strip()


def download(url: str, target: Path) -> bool:
    """Скачать файл. False — если сервер оборвал или отказал."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "zagent-portfolio/1.0 (учебный проект)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"   не скачалось: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False
    if len(data) < 4096:
        # Меньше — почти наверняка страница ошибки, а не картинка.
        print(f"   слишком мало данных ({len(data)} байт)", file=sys.stderr)
        return False
    target.write_bytes(data)
    return True


def collect(out: Path, count: int) -> list[dict]:
    """Собрать набор картинок. Возвращает список записей для credits.json."""
    out.mkdir(parents=True, exist_ok=True)
    credits: list[dict] = []
    per = max(1, count // len(CATEGORIES))

    for category in CATEGORIES:
        print(f"категория: {category}")
        try:
            titles = list_files(category, per)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            print(f"   список не получен: {exc}", file=sys.stderr)
            continue
        for title in titles:
            try:
                info = file_info(title)
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                print(f"   сведения не получены: {exc}", file=sys.stderr)
                continue
            if not info:
                continue
            thumb = info.get("thumburl")
            if not thumb:
                continue
            meta = info.get("extmetadata") or {}

            slug = re.sub(r"[^a-zA-Z0-9]+", "-",
                          title.replace("File:", ""))[:60].strip("-").lower()
            ext = ".png" if thumb.lower().endswith(".png") else ".jpg"
            target = out / f"{slug}{ext}"
            print(f"   {slug}")
            if not download(thumb, target):
                continue
            credits.append({
                "file": target.name,
                "title": title.replace("File:", ""),
                "author": plain((meta.get("Artist") or {}).get("value", "")),
                "license": plain((meta.get("LicenseShortName") or {}).get("value", "")),
                "source": info.get("descriptionurl", ""),
            })
            time.sleep(0.4)  # вежливо к API

    (out / "credits.json").write_text(
        json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nскачано {len(credits)} шт., список авторов: {out / 'credits.json'}")
    return credits


def main() -> int:
    parser = argparse.ArgumentParser(description="картинки с Wikimedia Commons")
    parser.add_argument("--out", default="tmp/stock", help="куда складывать")
    parser.add_argument("--count", type=int, default=12, help="сколько всего")
    args = parser.parse_args()

    out = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    credits = collect(out, args.count)
    if not credits:
        print("ничего не скачалось", file=sys.stderr)
        return 1
    for item in credits:
        size = (out / item["file"]).stat().st_size
        print(f"  {item['file']:52} {size / 1024:6.0f} КБ  {item['license']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())