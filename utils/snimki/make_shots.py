r"""Снять превью каждой страницы сайта настоящим браузером.

Зачем снимки, а не нарисованные плашки
-------------------------------------
Раньше в каталоге превью рисовались кодом — полоски по диагонали. Так
дёшево и не устаревает, но каталог обещает «пять разных сайтов», а сам
показывает пять одинаковых прямоугольников. Проверить по такому
превью, что страницы действительно разные, нельзя.

Снимок показывает настоящий первый экран. Плата за это известная и
осознанная: снимок перестаёт соответствовать странице после правки.
Поэтому он снимается скриптом, а не вручную, и версия снимка хранится
рядом — по ней видно, какой снимок какого адреса и когда он снят.

Как снимается
-------------
Chrome в режиме headless, фиксированное окно. Размер окна зафиксирован
намеренно: при разном размере превью разного размера, и ряд в каталоге
перестаёт быть рядом.

Полная страница не снимается — только первый экран. В каталоге нужен
именно он: человек выбирает по первому взгляду, а не по всей длине.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_shots.py
    .venv\\Scripts\\python.exe tools\\make_shots.py --only palm
    .venv\\Scripts\\python.exe tools\\make_shots.py --only /tma/
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "site" / "assets" / "shots"
META = SHOTS / "shots.json"

BASE = "https://zagent.do.am"

#: Страницы без снимка.
#:
#: `catalog.html` снять нельзя осмысленно: это сам каталог, и снимок
#: каталога внутри каталога — таврография. Остальным снимок нужен.
NO_SHOT = {"/catalog.html"}

#: Что снимаем. Порядок задаёт порядок карточек в каталоге.
PAGES: tuple[tuple[str, str], ...] = (
    ("/", "Главная"),
    ("/tex/", "NovaTech"),
    ("/barbie/", "Pink Élite"),
    ("/tovar/", "NovaTech Store"),
    ("/forno/", "Forno"),
    ("/dentalia/", "Dentalia"),
    ("/vow/", "Vow"),
    ("/grind/", "Grind"),
    ("/strobe/", "Strobe"),
    ("/palm/", "Линии руки"),
    ("/tma/", "Помощник"),
    # --- макеты из demo ---
    ("/aetheris/", "Aetheris"), ("/auraspin/", "Aura Spin"),
    ("/academy/", "Авторская академия"), ("/palmistry/", "Хиромантия"),
    ("/palmchart/", "Карта линий"), ("/shaurma/", "Шаурма"),
    ("/apex/", "APEX"), ("/zov/", "ЗОВ"), ("/taiga/", "TAIGA"),
    ("/auratravel/", "Aura Travel"), ("/cakes/", "Торты"),
    ("/realtravel/", "Real Travel"), ("/pizzafire/", "Pizza Fire"),
    ("/foodie/", "Foodie"), ("/guardbase/", "Guardbase"),
    ("/modern/", "Современный сайт"), ("/iskra/", "Iskra"),
    ("/horology/", "Kinetic Horology"), ("/lumiere3d/", "Lumière 3D"),
    ("/lumiere/", "Lumière"), ("/nariaidy/", "Nariaidy"),
    ("/naturespace/", "Nature Space"), ("/novastore/", "NovaTech Store"),
    ("/oboi/", "ОБОИ.RU"), ("/soramoku/", "Sora & Moku"),
)

#: Окно. Ширина под телефон и ноутбук сразу: 1280 — это то, что видит
#: посетитель на ноутбуке, и превью в каталоге выглядит как страница,
#: а не как её мобильная версия.
WIDTH = 1280
HEIGHT = 800

#: Виртуальное время: сколько миллисекунд ждать анимации, шрифтов и
#: картинок до снимка. Восемь секунд хватает страницам с локальными
#: картинками; меньше — снимок делается на середине отрисовки.
BUDGET_MS = 9000


def find_chrome() -> Path | None:
    """Найти Chrome: без него снимок нечем снять."""
    candidates = [
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for item in candidates:
        if item.is_file():
            return item
    found = shutil.which("chrome") or shutil.which("chromium")
    return Path(found) if found else None


def shoot(chrome: Path, url: str, out_png: Path) -> tuple[bool, str]:
    """Снять один адрес. Возвращает (получилось, причина неудачи)."""
    with tempfile.TemporaryDirectory() as profile:
        try:
            result = subprocess.run(
                [
                    str(chrome),
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--no-sandbox",
                    f"--user-data-dir={profile}",
                    f"--window-size={WIDTH},{HEIGHT}",
                    f"--virtual-time-budget={BUDGET_MS}",
                    f"--screenshot={out_png}",
                    url,
                ],
                capture_output=True, text=True, timeout=420)
        except subprocess.TimeoutExpired:
            return False, "браузер не ответил за 180 с"
        except Exception as exc:  # pragma: no cover - ветка окружения
            return False, f"{type(exc).__name__}: {exc}"

    if not out_png.is_file():
        tail = (result.stderr or "").strip().splitlines()
        return False, tail[-1][:90] if tail else "файл не создан"

    size = out_png.stat().st_size
    if size < 4000:
        return False, f"снимок подозрительно мал: {size} Б"

    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="снять превью страниц")
    parser.add_argument("--only", metavar="ПУТЬ", help="одна страница")
    parser.add_argument("--list", action="store_true", help="только список")
    args = parser.parse_args()

    chrome = find_chrome()
    if not chrome:
        print("Chrome не найден: снимать нечем", file=sys.stderr)
        return 2

    pages = [p for p in PAGES if p[0] not in NO_SHOT]
    if args.only:
        pages = [p for p in pages if p[0] == args.only]
        if not pages:
            print(f"страница {args.only} не в списке")
            return 1

    if args.list:
        for path, name in pages:
            print(f"  {path:<12} {name}")
        return 0

    print(f"Chrome: {chrome}")
    print(f"окно: {WIDTH}x{HEIGHT}, ожидание: {BUDGET_MS} мс")
    print()

    SHOTS.mkdir(parents=True, exist_ok=True)
    index = json.loads(META.read_text(encoding="utf-8")) if META.is_file() else {}

    good = 0
    bad = 0
    for path, name in pages:
        slug = path.strip("/").replace("/", "_") or "main"
        png = SHOTS / f"{slug}.png"
        jpg = SHOTS / f"{slug}.jpg"

        url = BASE + path
        print(f"{path:<12} {name}")
        ok, why = shoot(chrome, url, png)
        if not ok:
            print(f"   не снято: {why}")
            bad += 1
            png.unlink(missing_ok=True)
            continue

        # Снимок ужимается: PNG страницы весит сотни килобайт, а в
        # каталоге их двадцать плюс, и на мобильном трафике это полмегабайта
        # на один ряд карточек.
        try:
            from PIL import Image
            with Image.open(png) as raw:
                raw.load()
                raw.convert("RGB").save(jpg, "JPEG", quality=72,
                                        optimize=True, progressive=True)
                width, height = raw.size
        except Exception as exc:
            print(f"   не ужать: {exc}")
            jpg = png
            width = height = 0

        png_kb = png.stat().st_size / 1024
        jpg_kb = jpg.stat().st_size / 1024 if jpg.is_file() else 0
        png.unlink(missing_ok=True)

        index[path] = {"name": name, "file": jpg.name, "w": width,
                       "h": height, "kb": round(jpg_kb)}
        print(f"   {jpg.name}  {width}x{height}  "
              f"{png_kb:.0f} -> {jpg_kb:.0f} КБ")
        good += 1

    META.write_text(json.dumps(index, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    print()
    print(f"снято: {good}   не вышло: {bad}   всего превью: {len(index)}")
    total = sum(v["kb"] for v in index.values())
    print(f"вес всех превью: {total / 1024:.1f} МБ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
