r"""Сделать пять подач-з��глушек на абстрактных картинках.

Зачем
----
Заглушки нужны, чтобы проверить вёрстку витрины: двенадцать
карточек подряд на настоящих страницах не показывают, как ведёт себя
каталог, когда часть ссылок ведёт в пустоту или на страницу, которая
ещё не дописана.

Почему детализация 3 из 10
-------------------------
Заглушка не должна спорить с настоящими подачами за внимание.
На `steel` проработаны штриховка, стекло и типографика; здесь — только
картинка, заголовок и один абзац. Если заглушка выглядит законченной,
она не отличается от настоящей страницы, и проверить каталог нечем.

Почему картинки свои
--------------------
Картинки лежат в `Downloads/abstration` — это сток с разных сайтов,
и имена файлов — хеши, по которым источник не восстановить. Часть
папки отброшена осознанно: кадры с персонажами игр (Cyberpunk 2077,
Elsword) и работы с платного стока pngtree выкладывать нельзя, даже
в качестве заглушки. Взяты только абстрактные изображения без людей,
логотипов и узнаваемых персонажей.

Картинки уменьшаются до 1400 пикселей по ширине и пережимаются в
JPEG: исходники весят до 800 КБ, пять таких на странице — четыре
мегабайта мобильного трафика.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_placeholders.py
    .venv\\Scripts\\python.exe tools\\make_placeholders.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path.home() / "Downloads" / "abstration"
PORTFOLIOS = ROOT / "portfolios"

#: Что делает каждая заглушка. Разные палитры и разный характер:
#: пять одинаковых карточек подряд не проверяют каталог, а прячут
#: в нём ошибки — глаз скользит и ничего не замечает.
SPECS = (
    {
        "name": "prism",
        "title": "Призма",
        "tagline": "свет разбивается и собирается",
        "image": "pngtree-gray-white-round-dots-geometric-abstract-"
                 "background-image_754676.jpg",
        "text": "Светлая заглушка. Точки и круги на сером — "
                "проверка тонких линий и отступов.",
        "bg": "#F2F2F4", "fg": "#2A2A2E", "muted": "#8A8A93",
    },
    {
        "name": "flux",
        "title": "Поток",
        "tagline": "частицы, которые связаны",
        "image": "background-realistic-abstract-technology-particle_"
                 "23-2148431735.avif",
        "text": "Тёмная заглушка. Синяя сетка частиц — проверка "
                "контраста текста на тёмном фоне.",
        "bg": "#071A26", "fg": "#EAF6FF", "muted": "#6FA8C7",
    },
    {
        "name": "stone",
        "title": "Камень",
        "tagline": "текстура вместо рисунка",
        "image": "photo-stone-texture-pattern_58702-16052.avif",
        "text": "Фактурная заглушка. Проверка того, как фоновая "
                "картинка мешает читать текст.",
        "bg": "#3A3733", "fg": "#F2EFE9", "muted": "#A79E92",
    },
    {
        "name": "nova",
        "title": "Нова",
        "tagline": "розовое зарево на чёрном",
        "image": "synthwave-retro-background-with-neon-pink-sunset_"
                 "107791-26627.avif",
        "text": "Неоновая заглушка. Розовый на чёрном — проверка "
                "цветного акцента.",
        "bg": "#14060F", "fg": "#FFEAF6", "muted": "#D98BB4",
    },
    {
        "name": "fold",
        "title": "Складка",
        "tagline": "белое на белом, но читаемое",
        "image": "white-paper-fold-background-minimalist-elegant-"
                 "designs_851755-379466.avif",
        "text": "Самая светлая заглушка. Светлая картинка под "
                "светлым текстом — худший случай для читаемости.",
        "bg": "#F4F2EF", "fg": "#3B3835", "muted": "#9A938B",
    },
)

#: Ширина, до которой уменьшаем картинку. Меньше — не нужно: на
#: телефоне картинка всё равно показывается в полосу.
MAX_WIDTH = 1400

HTML = """<!DOCTYPE html>
<!-- Заглушка {name}: детализация 3 из 10 намеренно низкая.
     Сгенерировано tools/make_placeholders.py — правьте руками, если
     страница понадобится всерьёз. -->
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>zagent — {title}</title>
<meta name="description" content="Заглушка подачи портфолио {title}. {tagline}.">
<link rel="stylesheet" href="style.css">
</head>
<body>
<main class="wrap">
  <p class="tag">заглушка · детализация 3/10</p>
  <h1>{title}</h1>
  <p class="tagline">{tagline}</p>
  <img class="pic" src="pic.jpg" alt="Абстрактная заставка подачи {title}"
       width="{width}" height="{height}" decoding="async">
  <p class="body">{text}</p>
  <p class="back"><a href="/catalog.html">ко всем подачам</a></p>
</main>
</body>
</html>
"""

CSS = """/* Заглушка {name}.
 *
 * Намеренно минимум: одна колонка, одна картинка, четыре правила.
 * Никакой сетки, стекла и анимаций — здесь проверяется каталог,
 * а не вёрстка. Настоящие подачи живут рядом и сделаны подробно.
 *
 * Палитра взята из картинки, а не выдумана: иначе заглушка спорила
 * бы с собственным снимком.
 */
:root {{
  --bg: {bg};
  --fg: {fg};
  --muted: {muted};
}}

* {{ box-sizing: border-box; }}

body {{
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial,
               sans-serif;
  font-size: 17px;
  line-height: 1.6;
}}

.wrap {{
  /* Колонка узкая: на заглушке важна читаемость, а не площадь. */
  max-width: 720px;
  margin: 0 auto;
  padding: 64px 24px;
}}

.tag {{
  margin: 0 0 12px;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}}

h1 {{
  margin: 0 0 6px;
  font-size: 44px;
  font-weight: 300;
  letter-spacing: -0.02em;
  line-height: 1.1;
}}

.tagline {{
  margin: 0 0 32px;
  font-size: 19px;
  color: var(--muted);
}}

.pic {{
  display: block;
  width: 100%;
  height: auto;
  border-radius: 10px;
  margin: 0 0 28px;
}}

.body {{
  margin: 0 0 32px;
  max-width: 56ch;
}}

.back {{
  margin: 0;
  padding-top: 20px;
  border-top: 1px solid currentColor;
  font-size: 15px;
}}

.back a {{
  color: inherit;
  opacity: 0.7;
  text-decoration: none;
  border-bottom: 1px solid currentColor;
}}

.back a:hover, .back a:focus-visible {{ opacity: 1; }}

:focus-visible {{ outline: 2px solid var(--muted); outline-offset: 3px; }}

@media (max-width: 560px) {{
  .wrap {{ padding: 36px 18px; }}
  h1 {{ font-size: 32px; }}
}}
"""


def prepare(spec: dict, dry: bool) -> bool:
    """Уменьшить картинку и положить рядом со страницей."""
    source = SRC / spec["image"]
    if not source.is_file():
        print(f"  нет картинки: {spec['image']}", file=sys.stderr)
        return False

    from PIL import Image

    try:
        image = Image.open(source)
        image.load()
    except Exception as exc:
        print(f"  не читается {spec['image']}: {exc}", file=sys.stderr)
        return False

    if image.width > MAX_WIDTH:
        ratio = MAX_WIDTH / image.width
        image = image.resize(
            (MAX_WIDTH, int(image.height * ratio)), Image.LANCZOS)

    folder = PORTFOLIOS / spec["name"]
    if not dry:
        folder.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(folder / "pic.jpg", "JPEG", quality=82,
                                 optimize=True, progressive=True)

    spec["width"] = image.width
    spec["height"] = image.height
    if not dry:
        size = (folder / "pic.jpg").stat().st_size / 1024
        print(f"    pic.jpg {image.width}x{image.height}, {size:.0f} КБ")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="сделать заглушки")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not SRC.is_dir():
        print(f"нет папки с картинками: {SRC}", file=sys.stderr)
        return 2

    made = 0
    for spec in SPECS:
        folder = PORTFOLIOS / spec["name"]
        print(f"{spec['name']} — {spec['title']}")
        if not prepare(spec, args.dry_run):
            return 2
        if not args.dry_run:
            (folder / "index.html").write_text(
                HTML.format(**spec), encoding="utf-8")
            (folder / "style.css").write_text(
                CSS.format(**spec), encoding="utf-8")
        made += 1

    print(f"\nзаглушек: {made}")
    if args.dry_run:
        print("это был просмотр: ничего не записано")
    else:
        total = sum(
            (PORTFOLIOS / s["name"] / "pic.jpg").stat().st_size
            for s in SPECS)
        print(f"картинок на диске: {total / 1024 / 1024:.2f} МБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
