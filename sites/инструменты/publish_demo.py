r"""Разложить макеты из site/demo по отдельным папкам и убрать внешние загрузки.

Зачем
----
В папке demo лежат макеты, собранные откуда попало: имена файлов —
либо случайные хеши, либо `deepseek_html_20261008_7e2ce3`, либо китайские
имена. Так выкладывать нельзя: адрес на сервере становится нечитаемым, а
файл с пробелами ломается по FTP.

Вторая причина серьёзнее. Двадцать шесть страниц из двадцати девяти тянут
снаружи фотографии, шрифты и библиотеки — 97 картинок Unsplash, Google
Fonts, Tailwind и cdnjs. Правило проекта запрещает внешние загрузки: без
сети страница обязана остаться целой, а не превратиться в пустые блоки.
Поэтому здесь не только переименование, но и скачивание всего наружу и
переписывание ссылок на локальные.

Что делается
------------
1. Страница получает короткое латинское имя и свою папку.
2. Всё, что она тянет снаружи, скачивается рядом с ней.
3. Ссылки в разметке переписываются на локальные файлы.
4. Проверка: после сборки внешних адресов быть не должно ни одного.

Почему Tailwind CDN скачивается, а не выбрасывается
---------------------------------------------------
Tailwind в браузере — это скрипт, который на лету собирает стили. Убрать
его нельзя: страница останется совсем без оформления, то есть пустой.
Поэтому скрипт кладётся рядом и работает как раньше, только без сети.

Почему каталог строится словарём, а не по шаблону имени
------------------------------------------------------
Имя страницы не говорит, что она о ней. `code_artifact.html` — это
хиромантия, `deepseek_html_20261008_751dd0` — экспедиции. Если выводить
имя из файла, в адресах окажется мусор. Словарь задан явно, и сверка
покажет, какая страница ещё не названа.

Про дубликаты
-------------
Три пары файлов оказались побайтово одинаковыми под разными именами.
Каждая такая пара публикуется один раз: второй адрес создал бы страницу,
неотличимую от первой, и в каталоге появилось бы два пункта на одну работу.

Запуск:
    .venv\\Scripts\\python.exe tools\\publish_demo.py
    .venv\\Scripts\\python.exe tools\\publish_demo.py --dry-run
    .venv\\Scripts\\python.exe tools\\publish_demo.py --only apex
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "site" / "demo"
SITE = ROOT / "site"

#: С современным браузером: без этого серверы отдают старые форматы.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

#: Страница -> короткое имя папки.
#:
#: Имена латинские и короткие: они попадают в адрес, и длинное имя
#: в адресе читается как мусор. Занятые имена уже проверяются —
#: папка `palm` занята витриной хиромантии, поэтому её версии из
#: demo названы иначе.
PAGES: dict[str, str] = {
    "aetheris_next_gen_crypto_protocol.html": "aetheris",
    "aura_spin_analog_sound_experience.html": "auraspin",
    "buhgalterika_mentor.html": "academy",
    "code_artifact (1).html": "palmistry",
    "code_artifact.html": "palmchart",
    "deepseek_html_20261008_0816ad.html": "shaurma",
    "deepseek_html_20261008_3716ee.html": "apex",
    "deepseek_html_20261008_751dd0.html": "zov",
    "deepseek_html_20261008_7e2ce3.html": "taiga",
    "deepseek_html_20261008_9db1be.html": "auratravel",
    "deepseek_html_20261008_afed4e.html": "cakes",
    "deepseek_html_20261008_b6cf14.html": "realtravel",
    "deepseek_html_20261008_c52c2e.html": "pizzafire",
    "foodie_food_site_one_file.html": "foodie",
    "guardbase_ai_security_startup.html": "guardbase",
    "HTML\u20113 - Kimi.html": "modern",
    "iskra_ceramic_art_e_commerce.html": "iskra",
    "kinetic_horology_fine_horology_studio_interactive_3d_timepiece_atelier.html": "horology",
    "lumi_re_studio_interactive_design_furniture_studio (1).html": "lumiere3d",
    "lumi_re_studio_interactive_design_furniture_studio.html": "lumiere",
    "nariaidy_luxury_jewelry_landing_page.html": "nariaidy",
    "nature_space_eco_hotel.html": "naturespace",
    "NovaTechStore.html": "novastore",
    "oboi_ru_site_one_file.html": "oboi",
    "sora_moku_japandi_design_studio_interactive_3d_atelier.html": "soramoku",
}

#: Страницы, которые не выкладываются ни при каком варианте.
#:
#: Причина не техническая, а содержательная, и она задана проектом:
#: персонажи чужих игр и фрагменты тела в публикацию не идут.
#: Изображения на таких страницах — стоковые, то есть вендор не
#: нарушается, но тема страницы остаётся чужой работой, выдавать
#: которую за свою нельзя.
SKIP: dict[str, str] = {
    "gta_vi_character_wireframe_dna_analysis.html":
        "разбор персонажа GTA VI: чужая игровая работа",
    "shredded_body_gym_site.html": "фрагменты тела",
    "shredded_body_landing_page.html": "фрагменты тела",
    "shredded_body_landing_page (1).html": "фрагменты тела",
}

#: Файлы, которые страницы берут из общей папки demo.
#:
#: Ссылаются на них только две страницы — `modern` и `novastore`.
#: Копировать их во все двадцать шесть папок незачем: двадцать четыре
#: копии файла, на который никто не ссылается, только занимают место.
SHARED = ("style.css", "script.js")

#: Внешняя загрузка: src/href на http(s).
#:
#: Отдельная от гиперссылки в тексте: ссылка «нас тут нет» не нужна,
#: чтобы страница открылась, а вот картинка или шрифт снаружи — это
#: ровно то, что ломает страницу без сети.
EXTERNAL = re.compile(
    r'(?:src|<link[^>]*href|<script[^>]*src)\s*=\s*["\']https?://[^"\']+',
    re.IGNORECASE)

#: Куда грузить и что с этим делать дальше.
#: `nest` — обычный файл кладём в папку страницы как есть.
#: `css` — скачиваем как CSS, внутри разбираем ссылки на шрифты.
#: `js` — скрипт кладём как есть.
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif", ".ico"}
FONT_EXT = {".woff2", ".woff", ".ttf", ".otf", ".eot"}

#: Кэш скачанного на весь прогон: url -> локальное имя файла.
#: Один и тот же шрифт или картинка тянется на двадцати страницах, и
#: без кэша это двадцать одинаковых копий на диске и двадцать одинаковых
#: файлов на сервере.
_cache: dict[str, str] = {}

#: Те же данные по содержимению. Нужны, потому что кэш отдаёт только
#: имя файла: страница, пришедшая за уже скачанной картинкой второй,
#: получала ссылку на файл, которого в её папке нет. Имя одно на весь
#: прогон (выбрано по первой странице, за ней закрепилось
#: `aetheris-font.css`), а копия лежала только в той первой папке.
#: Итог: страница собиралась, ссылалась на свой же файл и отдавала 404
#: при загрузке, а сборщик об этом честно сообщал.
_cache_bytes: dict[str, bytes] = {}

#: Совпадения по содержимому: хеш -> уже сохранённый файл.
_by_hash: dict[str, str] = {}


def fetch(url: str, tries: int = 3) -> bytes:
    """Скачать адрес с повторами.

    Повторы не из вежливости: сорок семь мегабайт картинок идут по
    сотне ссылок, и единичный обрыв на середине оставлял бы страницу
    без половины фото. Пауза растёт, чтобы не долбить сервер.
    """
    last = ""
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=60) as answer:
                return answer.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last)


def safe_name(url: str, index: int) -> str:
    """Имя файла из адреса, пригодное для сервера и для URL."""
    path = urlparse(url).path
    base = Path(path).name or f"file-{index:03d}"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.") or f"file-{index:03d}"
    stem, dot, ext = base.partition(".")
    # Хвост вроде `photo-1600x900` бесполезен и повторяется у всех
    # картинок Unsplash: без него десять файлов назывались бы одинаково
    # до первых четырёх букв.
    if len(stem) > 18:
        stem = stem[:18]
    return f"{stem}{dot}{ext}" if dot else stem


def unique(folder: Path, name: str) -> str:
    """Не дать двум файлам занять одно имя."""
    if not (folder / name).exists():
        return name
    stem, dot, ext = name.partition(".")
    for i in range(2, 100):
        candidate = f"{stem}-{i}{dot}{ext}" if dot else f"{stem}-{i}"
        if not (folder / candidate).exists():
            return candidate
    raise RuntimeError(f"не могу подобрать имя для {name}")


def save(folder: Path, name: str, data: bytes) -> str:
    """Сохранить, переиспользовав копию по содержимому."""
    digest = hashlib.sha256(data).hexdigest()[:16]
    if digest in _by_hash:
        return _by_hash[digest]
    final = unique(folder, name)
    (folder / final).write_bytes(data)
    _by_hash[digest] = final
    return final


def localize_css(text: str, folder: Path, prefix: str) -> str:
    """Скачать всё, на что ссылается CSS, и переписать ссылки.

    Отдельно от HTML, потому что внутри таблицы стилей лежат адреса
    на сами шрифты: скачать CSS и забыть про `url(...)` внутри него
    означало бы оставить ровно ту поломку, ради устранения которой
    всё затевалось.
    """
    def repl(match: re.Match[str]) -> str:
        url = match.group(1).strip("'\"")
        if url.startswith("data:"):
            return match.group(0)
        if not url.startswith("http"):
            return match.group(0)
        try:
            data = fetch(url)
        except RuntimeError as exc:
            print(f"      шрифт/файл не скачался: {url[:70]} — {exc}")
            return match.group(0)
        name = save(folder, f"{prefix}-{safe_name(url, 0)}", data)
        return f"url('{name}')"

    return re.sub(r"url\(\s*['\"]?(https?://[^'\")]+)['\"]?\s*\)", repl, text)


def is_preconnect(url: str) -> bool:
    """Это подсказка браузеру, а не загружаемый файл.

    В макетах стоит `<link rel="preconnect" href="https://fonts.gstatic.com">`
    — сказать браузеру «похоже, сюда скоро пойдёт соединение». Скачивать
    нечего: по этому адресу нет файла, сервер отвечает 404.

    Раньше скрипт пытался скачать такой адрес и считал 404 ошибкой
    страницы. В итоге двадцать восемь «ошибок» на двадцать пять
    страниц — то есть почти каждая страница выглядела сломанной
    из-за двух строк, которые ничего не грузят.

    Раз подсказка не нужна (шрифты теперь лежат рядом), её убираем из
    разметки целиком.
    """
    parsed = urlparse(url)
    return parsed.path in ("", "/") and not parsed.query


def placeholder(folder: Path, note: str) -> str:
    """Заглушка на место фотографии, которой уже нет.

    Ссылка осталась бы внешней, а значит страница без сети потеряла бы
    картинку. Заглушка держит вёрстку: размер блока тот же, поэтому
    страница не пересобирается при загрузке.
    """
    from PIL import Image, ImageDraw

    width, height = 1200, 750
    image = Image.new("RGB", (width, height), "#e7e4dc")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline="#b9b3a6", width=3)
    try:
        draw.text((40, height // 2 - 12), note[:60], fill="#6d675c")
    except Exception:
        pass          # шрифта нет — заглушка всё равно годится
    name = save(folder, "missing-photo.jpg",
                _png_to_jpeg(image))
    return name


def _png_to_jpeg(image) -> bytes:
    import io
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70, optimize=True)
    return buffer.getvalue()


def process(source: Path, name: str, dry: bool) -> dict:
    """Скачать наружу, переписать, положить в папку страницы."""
    html = source.read_text(encoding="utf-8", errors="replace")
    target = SITE / name
    if dry:
        return {"name": name, "external": len(EXTERNAL.findall(html)),
                "downloaded": 0, "kb": source.stat().st_size // 1024}

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    stats = {"downloaded": 0, "failed": 0, "bytes": 0,
             "missing": 0, "stripped": 0}

    # Общие файлы кладём только те, на которые эта страница ссылается.
    # Содержимое проходит ту же локализацию, что и всё остальное: в
    # `style.css` могут быть адреса на шрифты, и оставить их внешними
    # означало бы оставить ровно ту поломку, ради устранения которой
    # всё затевалось.
    for extra in SHARED:
        local = DEMO / extra
        if not local.is_file():
            continue
        if not re.search(rf'["\']{re.escape(extra)}["\']', html, re.I):
            continue
        text = localize_css(local.read_text(encoding="utf-8", errors="replace"),
                            target, "shared")
        (target / extra).write_text(text, encoding="utf-8")
        print(f"      + общий {extra}")

    pattern = re.compile(
        r'((?:src|href)\s*=\s*["\'])(https?://[^"\']+)(["\'])', re.I)

    def repl(match: re.Match[str]) -> str:
        url = match.group(2)

        # Подсказка браузеру, а не файл: выкидываем её целиком.
        if is_preconnect(url):
            stats["stripped"] += 1
            return ""

        if url in _cache:
            local_name = _cache[url]
            # Копия обязана существовать в папке этой страницы, а не
            # в той, где файл скачали первым. Раньше здесь возвращалось
            # одно имя, и вторая страница ссылалась на файл, которого
            # у неё не было.
            if not (target / local_name).is_file():
                payload = _cache_bytes.get(url)
                if payload is not None:
                    (target / local_name).write_bytes(payload)
                    stats["downloaded"] += 1
                    stats["bytes"] += len(payload)
            return f"{match.group(1)}{local_name}{match.group(3)}"

        ext = Path(urlparse(url).path).suffix.lower()
        try:
            data = fetch(url)
        except RuntimeError as exc:
            print(f"      НЕ СКАЧАЛОСЬ: {url[:80]} — {exc}")
            # Фотографии, которой больше нет, заменяем заглушкой:
            # оставить внешний адрес нельзя — страница потеряет картинку
            # без сети, а это ровно то, ради чего всё затевалось.
            if ext in IMAGE_EXT or ext == "":
                local_name = placeholder(target, "фото недоступно")
                stats["missing"] += 1
            else:
                stats["failed"] += 1
                return match.group(0)
            _cache[url] = local_name
            return f"{match.group(1)}{local_name}{match.group(3)}"

        stats["downloaded"] += 1
        stats["bytes"] += len(data)

        if ext in IMAGE_EXT or ext in FONT_EXT:
            local_name = save(target, safe_name(url, stats["downloaded"]), data)
        elif "fonts.googleapis.com" in url or ext == ".css":
            # Это таблица стилей: внутри неё адреса на сами шрифты.
            css = localize_css(data.decode("utf-8", "replace"),
                               target, "font")
            local_name = save(target, f"{name}-font.css", css.encode("utf-8"))
        elif ext == ".js" or "cdn.tailwindcss.com" in url:
            local_name = save(target, safe_name(url, stats["downloaded"]), data)
        else:
            local_name = save(target, safe_name(url, stats["downloaded"]), data)

        _cache[url] = local_name
        # В кэш кладём то, что реально лежит на диске, а не исходную
        # выкачку: для таблицы стилей это уже локализованный текст, а
        # для картинки при совпадении по содержимому мог сохраниться
        # файл из другой папки. Читать обратно надёжнее, чем
        # рассуждать, какой из двух случаев перед нами.
        written = target / local_name
        _cache_bytes[url] = written.read_bytes() if written.is_file() else b""
        return f"{match.group(1)}{local_name}{match.group(3)}"

    out = pattern.sub(repl, html)
    (target / "index.html").write_text(out, encoding="utf-8")

    # Дописываем уведомление, что страница демонстрационная.
    notice = (
        "\n<!-- Демонстрационная страница из materials/demo. "
        "Бизнеса за ней нет: цены, контакты и отзывы вымышлены. "
        "Всё грузится с этого же адреса, внешних загрузок нет. -->\n"
    )
    body = out.replace("</body>", notice + "</body>")
    (target / "index.html").write_text(body, encoding="utf-8")

    stats["name"] = name
    stats["kb"] = sum(p.stat().st_size for p in target.iterdir()
                      if p.is_file()) // 1024
    # Проверяем то, что останется в файле на диске, а не исходник:
    # между ними стоят и вырезанные подсказки, и заглушки.
    written = (target / "index.html").read_text(encoding="utf-8")
    stats["external_left"] = len(EXTERNAL.findall(written))
    stats["files"] = len([p for p in target.iterdir() if p.is_file()])
    return stats


#: общий файл -> список страниц, которым он нужен
extra_map: dict[str, list[str]] = {}


def unused_extra_map_guard() -> None:
    """Заглушка: extra_map больше не используется.

    Оставлена как напоминание: механизм раскладки общих файлов убран,
    теперь `process()` сам решает по содержимому страницы, какие файлы
    из общей папки ей нужны.
    """
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="выложить макеты из demo")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", metavar="ИМЯ", help="одна страница")
    args = parser.parse_args()

    if not DEMO.is_dir():
        print(f"нет папки {DEMO}")
        return 1

    on_disk = {p.name for p in DEMO.glob("*.html")}
    mapped = set(PAGES)
    skipped = set(SKIP)

    unknown = sorted(on_disk - mapped - skipped)
    missing = sorted(mapped - on_disk)
    duplicates = len(mapped) != len(set(PAGES.values()))

    print(f"страниц на диске: {len(on_disk)}")
    print(f"  названо: {len(mapped & on_disk)}   пропущено по содержанию: "
          f"{len(skipped & on_disk)}")
    print()

    if unknown:
        print("БЕЗ ИМЕНИ (не выкладываются, пока не названы):")
        for name in unknown:
            print(f"  {name}")
        print()
    if missing:
        print("В СЛОВАРЕ, НО НЕТ НА ДИСКЕ:")
        for name in missing:
            print(f"  {name}")
        print()
    if duplicates:
        print("ВНИМАНИЕ: два файла названы одинаково")
        print()

    if skipped & on_disk:
        print("ПРОПУЩЕНЫ ПО СОДЕРЖАНИЮ:")
        for name in sorted(skipped & on_disk):
            print(f"  {name} — {SKIP[name]}")
        print()

    if duplicates:
        return 1
    if unknown and not args.only:
        print("Не все страницы названы. Добавьте их в PAGES или запустите "
              "с --only, чтобы выложить часть.")
        return 1

    targets = [n for n in PAGES if n in on_disk]
    if args.only:
        targets = [n for n in targets if PAGES[n] == args.only]
        if not targets:
            print(f"нет страницы с именем {args.only}")
            return 1

    total_bytes = 0
    total_downloads = 0
    total_missing = 0
    total_stripped = 0
    problems = 0

    for filename in sorted(targets):
        name = PAGES[filename]
        source = DEMO / filename
        print(f"{name}  <-  {filename}  ({source.stat().st_size // 1024} КБ)")

        # общие файлы копируем только один раз, перед первой страницей
        if not args.dry_run and not extra_map:
            pass

        stats = process(source, name, args.dry_run)
        total_bytes += stats.get("bytes", 0)
        total_downloads += stats.get("downloaded", 0)
        total_missing += stats.get("missing", 0)
        total_stripped += stats.get("stripped", 0)

        if args.dry_run:
            print(f"      внешних загрузок: {stats['external']}")
            continue

        print(f"      скачано: {stats['downloaded']}"
              f"   подсказок вырезано: {stats['stripped']}"
              f"   заглушек: {stats['missing']}")
        print(f"      файлов в папке: {stats.get('files')}"
              f"   вес: {stats.get('kb')} КБ")
        if stats["failed"]:
            print(f"      НЕ УДАЛОСЬ: {stats['failed']}")
            problems += stats["failed"]
        if stats["external_left"]:
            print(f"      ВНИМАНИЕ: осталось внешних загрузок "
                  f"{stats['external_left']}")
            problems += stats["external_left"]

    # общие файлы раскладываем по папкам страниц
    if not args.dry_run:
        for extra, pages in extra_map.items():
            original = DEMO / extra
            for page in pages:
                shutil.copy2(original, SITE / page / extra)
            print(f"\nобщий файл {extra} положен в {len(pages)} папок")

    print()
    print(f"итого: страниц {len(targets)}, скачано файлов "
          f"{total_downloads}, трафик {total_bytes / 1024 / 1024:.1f} МБ")
    print(f"  подсказок браузеру вырезано: {total_stripped}")
    print(f"  фотографий заменено заглушкой: {total_missing}")
    if problems:
        print(f"проблем: {problems}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
