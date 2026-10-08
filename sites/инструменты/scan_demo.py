r"""Разобрать папку site/demo: что можно выкладывать, а что нельзя.

Зачем
----
В папке тридцать страниц и картинки, собранные откуда попало: с
генераторов макетов, из загрузок, из папки с фотографиями. Среди них
есть то, что проект запрещает к публикации — персонажи чужих игр,
фрагменты тела, платный сток, снимки реальных людей.

Выкладывать пачкой нельзя, пока не разобрано, что в паке. Разбор
идёт в два слоя:

1. Технический слой: внешние загрузки, размер, дубликаты. Страница,
   которая тянет Unsplash, нарушает правило проекта — без сети она
   разваливается, а собранный сайт обязан её переживать.
2. Содержательный слой: поимённый список запрещённого. Он не
   выводится по совпадению слов в тексте, а перечислен явно, потому
   что ошибочное срабатывание здесь обходится дороже пропуска.

Что страница считается годной к выкладке
----------------------------------------
* Нет ни одного внешнего адреса загрузки.
* Внешние ссылки в тексте допустимы: их не нужно, чтобы страница
  открылась.
* Разметка и стили внутри одной папки, а не раскиданы по `demo/`
  общим файлом: иначе пятнадцать страниц будут драться за один
  `style.css`.

Запуск:
    .venv\\Scripts\\python.exe tools\\scan_demo.py
    .venv\\Scripts\\python.exe tools\\scan_demo.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "site" / "demo"

#: Внешняя загрузка: src/href на http(s).
#: Ровно то, что ломает страницу без сети.
EXTERNAL_LOAD = re.compile(
    r'(?:src|<link[^>]*href|<script[^>]*src)\s*=\s*["\']https?://[^"\']+',
    re.IGNORECASE)

#: Отдельный счётчик: внешний адрес в обычной гиперссылке — не загрузка.
PLAIN_LINK = re.compile(r'<a[^>]*href=["\']https?://', re.IGNORECASE)

#: Запрещённое содержание. Совпадение по имени файла.
#:
#: Список явный, а не проверка «есть ли эти слова в тексте»: в тексте
#: макета слова встречаются и в безобидном контексте, а ложное
#: срабатывание здесь стоит дороже, чем пропуск мимо проверки.
FORBIDDEN = (
    # Персонажи чужих игр. Их нельзя выдавать за свою работу, даже
    # как абстрактную иллюстрацию: это узнаваемая чужая собственность.
    ("gta", "персонаж GTA"),
    ("gtav", "персонаж GTA"),
    ("elsword", "персонаж Elsword"),
    ("cyberpunk", "персонаж Cyberpunk 2077"),
    ("genshin", "персонаж Genshin"),
    ("honkai", "персонаж Honkai"),

    # Фрагменты тела и обнажённые кадры: запрещено проектом.
    ("shredded_body", "фрагменты тела"),
    ("nudes", "обнажённые кадры"),
    ("nudify", "изображение обнажённого тела по фото"),
    ("ass", "фрагменты тела"),
    ("feet", "кадры ступней"),
    ("bdsm", "запрещённое содержание"),

    # Платный сток и чужие фотографии людей.
    ("pngtree", "платный сток pngtree"),
    ("_y.jpg", "фотографии реальных людей (подборка vk)"),
    ("_w.jpg", "фотографии реальных людей (подборка vk)"),
    ("getty", "сток getty"),
    ("shutterstock", "сток shutterstock"),
    ("unsplash", "сток unsplash"),
    ("freepik", "сток freepik"),
)

#: Что считать дубликатом по содержимому, а не по имени.
def digest(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def verdict(name: str) -> tuple[str, str]:
    """Вернуть (решение, причина) по имени файла."""
    low = name.lower()
    for needle, reason in FORBIDDEN:
        if needle in low:
            return "нельзя", reason
    return "можно", ""


def main() -> int:
    parser = argparse.ArgumentParser(description="разбор папки demo")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not DEMO.is_dir():
        print(f"нет папки {DEMO}")
        return 1

    pages: list[dict] = []
    images: list[dict] = []
    by_hash: dict[str, str] = {}
    duplicates: list[str] = []

    for item in sorted(DEMO.iterdir()):
        if not item.is_file():
            continue

        decision, reason = verdict(item.name)
        h = digest(item.read_bytes())
        if h in by_hash:
            duplicates.append(f"{item.name} = копия {by_hash[h]}")
        else:
            by_hash[h] = item.name

        if item.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            images.append({"name": item.name, "kb": item.stat().st_size // 1024,
                           "verdict": decision, "reason": reason})
            continue
        if item.suffix.lower() not in (".html", ".htm"):
            continue

        text = item.read_text(encoding="utf-8", errors="replace")
        ext = EXTERNAL_LOAD.findall(text)
        plain = PLAIN_LINK.findall(text)
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()

        blocks: list[str] = []
        if ext:
            blocks.append(f"{len(ext)} внешних загрузок")
        if decision == "нельзя":
            blocks.append(reason)

        pages.append({
            "name": item.name,
            "kb": item.stat().st_size // 1024,
            "title": title[:70],
            "external": len(ext),
            "links": len(plain),
            "verdict": "нельзя" if (ext or decision == "нельзя") else "можно",
            "reason": "; ".join(blocks),
        })

    ok = [p for p in pages if p["verdict"] == "можно"]
    no = [p for p in pages if p["verdict"] != "можно"]

    if args.json:
        print(json.dumps({"pages": pages, "images": images,
                          "duplicates": duplicates},
                         ensure_ascii=False, indent=1))
        return 0

    print(f"страниц: {len(pages)}   картинок и файлов: {len(images)}")
    print(f"можно выкладывать: {len(ok)}   нельзя: {len(no)}")
    print()

    print("--- МОЖНО ---")
    for p in sorted(ok, key=lambda x: x["name"]):
        print(f"  {p['kb']:>5} КБ  внешних: {p['external']:>2}  {p['name']}")
        if p["title"]:
            print(f"           {p['title']}")

    print()
    print("--- НЕЛЬЗЯ ---")
    for p in sorted(no, key=lambda x: x["name"]):
        print(f"  {p['name']}")
        print(f"      {p['reason']}")

    banned_img = [i for i in images if i["verdict"] == "нельзя"]
    if banned_img:
        print()
        print(f"--- картинок под запретом: {len(banned_img)} ---")
        for i in banned_img[:12]:
            print(f"  {i['name']}  — {i['reason']}")

    if duplicates:
        print()
        print("--- точные копии (в выкладку одна копия) ---")
        for d in duplicates[:12]:
            print(f"  {d}")

    total_good = sum(p["kb"] for p in ok)
    print()
    print(f"к выкладке: {len(ok)} страниц, {total_good / 1024:.1f} МБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
