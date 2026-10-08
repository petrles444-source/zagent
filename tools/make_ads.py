r"""Собрать рекламные страницы из материалов в `site/demo`.

Зачем
----
В папке лежат двенадцать шаблонов и около пятидесяти сгенерированных
макетов. Из них собираются готовые страницы: берём тему и картинки,
делаем из них работающую витрину.

Почему не берём шаблоны как есть
---------------------------------
Десять из двенадцати шаблонов тянут Unsplash и Google Fonts. Правило
проекта запрещает внешние загрузки: без интернета страница не должна
разваливаться. Самодостаточны только два — `oboi_ru` и
`shredded_body_gym_site`, у которых картинки вшиты прямо в файл.

Почему картинки копируются, а не вшиваются
------------------------------------------
Макеты весят по два мегабайта, и три из них на странице весили бы
шесть. Копия рядом весит сотни килобайт после сжатия и грузится
лениво, по мере прокрутки.

Что обязательно на каждой странице
----------------------------------
Пометка о демо. В макетах стоят выдуманные телефоны вида
«+7 (800) 555-01-23», скидки и обещания доставки. Для заготовки это
нормально, для опубликованной страницы — выдумка, на которую
поведут. Страница без пометки врёт.

Отзывы и цифры достижений не выдумываются: их нет, и блок «чего
нет» честнее пустого отзыва от несуществующего клиента.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_ads.py
    .venv\\Scripts\\python.exe tools\\make_ads.py --dry-run
"""

from __future__ import annotations

import argparse
import html as html_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "site" / "demo"

#: Каждая страница: тема, картинки, палитра, текст.
#:
#: Имена файлов заданы точно: если картинка переименуется, страница
#: молча останется без снимка, и это будет выглядеть как «дизайн
#: сломался», а не как «файла нет».
PAGES = (
    {
        "dir": "forno",
        "title": "Пицца с доставкой",
        "brand": "PIZZA HOUSE",
        "lead": "Свежие ингредиенты, итальянские рецепты, доставка за 30 минут",
        "hero": "Пицца с доставкой_ вкусный герой сайта.png",
        "cards": (
            ("Маргарита", "от 690 ₽", "Вкусная пицца с доставкой.png"),
        ),
        "features": (
            ("Свежая выпечка", "Тесто поднимается сутки, не замораживается"),
            ("Своя печь", "Дровяная, а не газовая — вкус другой"),
            ("Доставка", "За 30–60 минут по городу"),
        ),
        "palette": {"bg": "#0d0906", "panel": "#1a1210", "line": "#3a2418",
                    "fg": "#fff6ee", "muted": "#b09a8a", "accent": "#e2571f"},
        "demo": "Пиццерии не существует. Телефон, цены и сроки доставки "
                "взяты из макета и выдуманы.",
    },
    {
        "dir": "dentalia",
        "title": "Стоматология",
        "brand": "БЕЛАЯ ЛИНИЯ",
        "lead": "Лечение без боли, врачи с опытом, понятные цены до приёма",
        "hero": "Современная стоматология_ команда и забота.png",
        "cards": (
            ("Детская", "от 1 200 ₽", "Детская стоматология_ здоровые улыбки.png"),
            ("Лечение", "от 2 400 ₽", "Стоматология по доступным ценам.png"),
        ),
        "features": (
            ("Диагностика", "Снимок и осмотр до начала лечения"),
            ("Без боли", "Анестезия перед каждой процедурой"),
            ("Цена до лечения", "Стоимость называют на консультации"),
        ),
        "palette": {"bg": "#f4f8f7", "panel": "#ffffff", "line": "#d8e5e2",
                    "fg": "#12211f", "muted": "#5c716e", "accent": "#12857a"},
        "demo": "Клиники не существует. Цены и услуги выдуманы. "
                "Медицинские услуги по стране не рекламируются без лицензии.",
    },
    {
        "dir": "vow",
        "title": "Свадебный салон",
        "brand": "БЕЛЫЙ САД",
        "lead": "Платья, которые ждали этого дня",
        "hero": "День свадьбы_ 22 октября 2026.png",
        "cards": (
            ("Коллекция 2026", "от 24 000 ₽", "Элегантный свадебный лендинг в тёмных тонах.png"),
        ),
        "features": (
            ("Примерка", "Полтора часа с бесплатным консультантом"),
            ("Подгонка", "По фигуре, срок — от двух недель"),
            ("Хранение", "Платье доживает до вашей даты"),
        ),
        "palette": {"bg": "#0b0a0c", "panel": "#16151a", "line": "#2e2b33",
                    "fg": "#f7f4f2", "muted": "#a49da8", "accent": "#c9a96a"},
        "demo": "Салона не существует. Цены, коллекции и условия выдуманы.",
    },
    {
        "dir": "grind",
        "title": "Тренировки",
        "brand": "СУХОЕ ТЕЛО",
        "lead": "Программа, а не набор случайных упражнений",
        "hero": "Твоё лучшее тело.png",
        "cards": (
            ("Программа", "от 3 900 ₽/мес", "Тренер и диетолог_ путь к результату.png"),
        ),
        "features": (
            ("План", "Тренировки и питание в одном расписании"),
            ("Тренер", "Сопровождение, а не разовые консультации"),
            ("Замеры", "Каждые четыре недели, цифры в таблице"),
        ),
        "palette": {"bg": "#0a0a0a", "panel": "#171717", "line": "#2e2e2e",
                    "fg": "#fafafa", "muted": "#9a9a9a", "accent": "#d6ff3f"},
        "demo": "Зал не существует. Отзывы, результаты клиентов и цифры "
                "достижений не выдуманы — их здесь нет намеренно.",
    },
    {
        "dir": "strobe",
        "title": "Неоновая вечеринка",
        "brand": "ALFA ROOM",
        "lead": "Суббота, неон, музыка до утра",
        "hero": "Неоновая вечеринка в красных тонах.png",
        "cards": (
            ("Вечер пятницы", "от 900 ₽", "Танец в алом свете клуба.png"),
        ),
        "features": (
            ("Сцена", "Свет и звук собственной сцены"),
            ("Бар", "Карта напитков без наценки"),
            ("Вход", "По билетам, лимит по вместимости"),
        ),
        "palette": {"bg": "#120205", "panel": "#210610", "line": "#4a0e1e",
                    "fg": "#ffeef4", "muted": "#c792a2", "accent": "#ff2d55"},
        "demo": "Клуба не существует. Даты, цены и состав вечеринки "
                "выдуманы.",
    },
)

#: Ширина, до которой ужимаем макет. Он сделан под широкий экран, а
#: в столбце на телефоне ему самое место.
MAX_WIDTH = 1600

#: Качество JPEG. Макеты — фотографии с плавными переходами, и на
#: низком качестве по краям появляются кольца, заметные глазом.
QUALITY = 80


def prepare_image(name: str, target: Path, dry: bool) -> bool:
    """Скопировать макет рядом со страницей, ужав по ширине."""
    source = DEMO / name
    if not source.is_file():
        print(f"    НЕТ КАРТИНКИ: {name}", file=sys.stderr)
        return False

    from PIL import Image

    image = Image.open(source)
    image.load()
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    if image.width > MAX_WIDTH:
        ratio = MAX_WIDTH / image.width
        image = image.resize((MAX_WIDTH, int(image.height * ratio)),
                             Image.LANCZOS)

    if not dry:
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "JPEG", quality=QUALITY, optimize=True,
                   progressive=True)
    return True


def esc(text: str) -> str:
    return html_mod.escape(str(text))


def page_html(spec: dict) -> str:
    """Собрать страницу. Разметка строится здесь, не копируется."""
    c = spec["palette"]
    esc_title = esc(spec["title"])
    esc_brand = esc(spec["brand"])
    esc_lead = esc(spec["lead"])
    esc_demo = esc(spec["demo"])

    cards = "\n".join(
        f"""      <article class="card">
        <img class="card__pic" src="{esc(src)}" alt="" loading="lazy"
             decoding="async">
        <h3>{esc(name)}</h3>
        <p class="card__price">{esc(price)}</p>
      </article>"""
        for name, price, src in spec["cards"])

    features = "\n".join(
        f"""      <li>
        <h3>{esc(name)}</h3>
        <p>{esc(text)}</p>
      </li>"""
        for name, text in spec["features"])

    return f"""<!DOCTYPE html>
<!-- Рекламная страница-заготовка: {esc_title}.
     Сгенерировано tools/make_ads.py из материалов в site/demo.
     Бизнеса за ней нет — поэтому пометка о демо обязательна и стоит
     первым экраном, а не в подвале. -->
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc_title} — демо-заготовка</title>
<meta name="description" content="{esc_lead}. Демонстрационная страница: бизнеса не существует, цены и контакты выдуманы.">
<link rel="icon" href="data:,">
<link rel="stylesheet" href="style.css">
</head>
<body>

<!-- Плашка о демо. В макете стоит телефон «+7 (800) 555-01-23» и
     обещание доставки за 30 минут: для опубликованной страницы это
     выдумка, на которую поведут. Поэтому плашка первым экраном. -->
<div class="demo" role="note">
  <strong>Демо-заготовка.</strong> {esc_demo} Вёрстка и оформление —
  рабочие, наполнение — пример.
</div>

<header class="head">
  <a class="brand" href="#">{esc_brand}</a>
  <a class="to-catalog" href="/catalog.html">ко всем страницам</a>
</header>

<section class="hero">
  <img class="hero__pic" src="{esc(spec["hero"])}" alt="" width="{MAX_WIDTH}"
       height="{MAX_WIDTH // 2}" decoding="async">
  <div class="hero__body">
    <h1>{esc_title}</h1>
    <p class="lead">{esc_lead}</p>
    <a class="cta" href="#cards">смотреть</a>
  </div>
</section>

<section id="cards" class="block">
  <h2>Предложение</h2>
  <div class="grid">
{cards}
  </div>
</section>

<section class="block">
  <h2>Почему к нам</h2>
  <ul class="features">
{features}
  </ul>
</section>

<footer class="foot">
  <p class="foot__demo">{esc_demo}</p>
  <p class="foot__note">
    Страница собрана из макета в <code>site/demo</code>. Внешних
    загрузок нет: шрифты системные, картинки лежат рядом.
  </p>
</footer>

</body>
</html>
"""


def page_css(spec: dict) -> str:
    c = spec["palette"]
    return f"""/* Рекламная страница «{spec["title"]}».
 *
 * Палитра взята из макета-героя, а не выдумана: акцент {c["accent"]}
 * снят с вывески и кнопки на картинке. Иначе оформление спорило бы
 * с собственным снимком, и это видно глазом.
 *
 * Шрифты системные — правило проекта запрещает внешние загрузки,
 * и страница обязана открываться без интернета.
 */
:root {{
  --bg:     {c["bg"]};
  --panel:  {c["panel"]};
  --line:   {c["line"]};
  --fg:     {c["fg"]};
  --muted:  {c["muted"]};
  --accent: {c["accent"]};
}}

*, *::before, *::after {{ box-sizing: border-box; }}

body {{
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial,
               sans-serif;
  font-size: 17px;
  line-height: 1.6;
  -webkit-text-size-adjust: 100%;
}}

/* --- плашка о демо --- */

.demo {{
  padding: 13px 24px;
  background: rgba(255, 193, 7, 0.14);
  border-bottom: 1px solid rgba(255, 193, 7, 0.45);
  color: #ffd97a;
  font-size: 14px;
}}

.demo strong {{ color: #fff0c4; font-weight: 600; }}

/* --- шапка --- */

.head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 24px;
  border-bottom: 1px solid var(--line);
}}

.brand {{
  font-weight: 800;
  font-size: 19px;
  letter-spacing: 0.02em;
  color: var(--fg);
  text-decoration: none;
}}

.to-catalog {{
  color: var(--muted);
  font-size: 14px;
  text-decoration: none;
  border-bottom: 1px solid var(--line);
}}

.to-catalog:hover {{ color: var(--fg); border-bottom-color: var(--fg); }}

/* --- герой --- */

.hero {{ position: relative; overflow: hidden; }}

/* Снимок затемняется не градиентом «на глаз», а равномерно: под ним
   нет текста, и смысл в том, чтобы кадр не спорил с шапкой. */
.hero__pic {{
  display: block;
  width: 100%;
  height: auto;
  opacity: 0.85;
}}

.hero__body {{
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  gap: 16px;
  padding: 5vw;
  /* Затемнение слева: текст стоит только в этой части кадра, а
     справа остаётся еда или интерьер нетронутым. */
  background: linear-gradient(100deg,
              rgba(0, 0, 0, 0.78) 0%,
              rgba(0, 0, 0, 0.45) 45%,
              rgba(0, 0, 0, 0.05) 75%);
}}

.hero h1 {{
  margin: 0;
  font-size: clamp(30px, 5vw, 58px);
  line-height: 1.05;
  font-weight: 800;
  letter-spacing: -0.02em;
  /* Тень под заголовком обязательна: он лежит поверх фотографии,
     и без неё белый текст пропадает на светлом участке. */
  text-shadow: 0 2px 18px rgba(0, 0, 0, 0.6);
}}

.lead {{
  margin: 0;
  max-width: 34ch;
  font-size: clamp(15px, 1.4vw, 19px);
  color: var(--fg);
  opacity: 0.9;
  text-shadow: 0 1px 10px rgba(0, 0, 0, 0.6);
}}

.cta {{
  display: inline-block;
  padding: 13px 28px;
  background: var(--accent);
  color: #101010;
  font-weight: 700;
  text-decoration: none;
  border-radius: 10px;
  /* Светлая кнопка на снимке без тени выглядит вклеенной. */
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
}}

.cta:hover {{ filter: brightness(1.07); }}

/* На телефоне текст поверх снимка нечитаем в любом случае, поэтому
   он переезжает под картинку, а не мельчает. */
@media (max-width: 720px) {{
  .hero__body {{
    position: static;
    padding: 26px 20px 30px;
    background: none;
    text-shadow: none;
  }}
  .hero h1 {{ color: var(--fg); }}
  .lead {{ color: var(--muted); opacity: 1; }}
}}

/* --- блоки --- */

.block {{ padding: 64px 24px; max-width: 1180px; margin: 0 auto; }}

.block h2 {{
  margin: 0 0 28px;
  font-size: 30px;
  font-weight: 700;
  letter-spacing: -0.01em;
}}

.grid {{
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}}

@media (max-width: 720px) {{
  .grid {{ grid-template-columns: 1fr; }}
  .block {{ padding: 44px 20px; }}
}}

.card {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
}}

.card__pic {{
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}}

.card h3 {{ margin: 16px 18px 4px; font-size: 18px; font-weight: 600; }}

.card__price {{
  margin: 0 18px 18px;
  font-size: 15px;
  color: var(--accent);
  font-weight: 600;
}}

/* --- преимущества --- */

.features {{
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}}

@media (max-width: 720px) {{
  .features {{ grid-template-columns: 1fr; }}
}}

.features li {{
  padding: 22px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  border-top: 3px solid var(--accent);
}}

.features h3 {{ margin: 0 0 8px; font-size: 17px; font-weight: 600; }}

.features p {{ margin: 0; font-size: 15px; color: var(--muted); }}

/* --- подвал --- */

.foot {{
  padding: 40px 24px 56px;
  max-width: 1180px;
  margin: 0 auto;
  border-top: 1px solid var(--line);
}}

.foot__demo {{ margin: 0 0 12px; font-size: 15px; color: var(--fg); }}

.foot__note {{ margin: 0; font-size: 13.5px; color: var(--muted); }}

.foot code {{
  font-family: ui-monospace, Consolas, monospace;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 1px 5px;
}}

:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 3px; }}

@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="собрать рекламные страницы")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DEMO.is_dir():
        print(f"нет папки {DEMO}", file=sys.stderr)
        return 2

    made = 0
    for spec in PAGES:
        folder = ROOT / "site" / spec["dir"]
        print(f"{spec['dir']} — {spec['title']}")

        images = [spec["hero"]] + [src for _, _, src in spec["cards"]]

        # Карточка не должна повторять герой. Раньше четыре страницы
        # ссылались на один и тот же макет дважды, и в блоке
        # «Предложение» картинка героя повторялась: страница
        # выглядела сломанной без единой ошибки в консоли.
        if len(images) != len(set(images)):
            print("    ВНИМАНИЕ: картинка повторяется, "
                  "карточка покажет героя снова", file=sys.stderr)

        # Имена на диске — короткие и латинские. Исходные макеты
        # называются по-русски и с пробелами («День свадьбы_ 22 октября
        # 2026.png»); такие имена ломаются по FTP и требуют
        # процент-кодирования в каждом URL. Поэтому на страницу
        # кладётся `hero.jpg`, `card-1.jpg`, `card-2.jpg`, а
        # исходник остаётся в `site/demo` нетронутым.
        renamed = {}
        for index, name in enumerate(images):
            renamed[name] = "hero.jpg" if index == 0 else f"card-{index}.jpg"

        ok = True
        for name in images:
            target = folder / renamed[name]
            if not prepare_image(name, target, args.dry_run):
                ok = False
                break
        if not ok:
            return 2

        # Разметка подставляет переименованные файлы.
        spec = dict(spec)
        spec["hero"] = renamed[spec["hero"]]
        spec["cards"] = tuple((n, p, renamed[s]) for n, p, s in spec["cards"])

        if not args.dry_run:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "index.html").write_text(page_html(spec),
                                               encoding="utf-8")
            (folder / "style.css").write_text(page_css(spec),
                                              encoding="utf-8")
            size = sum(p.stat().st_size for p in folder.glob("*"))
            print(f"    собрано: {size / 1024:.0f} КБ")
        made += 1

    print(f"\nстраниц: {made}")
    if args.dry_run:
        print("это был просмотр: ничего не записано")
    return 0


if __name__ == "__main__":
    sys.exit(main())
