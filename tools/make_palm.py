r"""Собрать витрину хиромантии из готовых макетов и положить её в сборку.

Зачем макет переносится, а не пишется с нуля
-------------------------------------------
Картинки лежат в `Downloads` под русскими именами с пробелами и двоеточиями
(`Линии руки_ карта возможностей.png`). По FTP такие имена ломаются, а в
URL выглядят нечитаемо, поэтому файлы переезжают в проект под короткими
ASCII-именами. Оригиналы остаются на месте.

Почему картинки ужимаются
-------------------------
Исходники весят по два мегабайта. Четыре таких на странице — восемь
мегабайт мобильного трафика, и на телефоне страница открывается секунд
десять, пока грузится четвёртая. Ширина 1400 пикселей и JPEG достаточно:
разница на экране телефона не видна, а трафик падает вчетверо.

Что на странице и почему именно это
----------------------------------
* `chart.jpg` — карта линий. Это содержательный блок: по нему видно,
  о чём вообще страница, а не «обо всём».
* `phone.jpg` — макет приложения. Показывает продукт: «та же карта, но
  в телефоне».
* `atrium.jpg` — вилла у моря. Атмосферный блок про обстановку, в
  котором проходит разбор.
* `athlete.jpg` — снимок с натурной съёмки. Ставится в подвал как
  иллюстрация съёмки «как это выглядит в жизни», а не как герой
  страницы.

Про текст
---------
Хиромантия не является наукой и ничего не предсказывает. Текст на
странице поэтому не обещает «ключ к судьбе», а говорит о разборе
рисунка ладони как о практике самоанализа. И отдельно стоит плашка
о том, что это демо-заготовка: мастера, отзывов и истории за ней нет,
всё придумано под вёрстку.

Запуск:
    .venv\Scripts\python.exe tools\make_palm.py
    .venv\Scripts\python.exe tools\make_palm.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = Path.home() / "Downloads"
SITE = ROOT / "site"
OUT = SITE / "palm"

#: Ширина, до которой ужимаем. На телефоне картинка и так показывается
#: в полосу, а на ноутбуке 1400 — это больше ширины контента.
MAX_WIDTH = 1400

#: исходник в Downloads -> имя в проекте. Короткое имя обязательно:
#: русские имена ломаются по FTP, а длинные — в адресе.
IMAGES = (
    ("Линии руки_ карта возможностей.png", "chart.jpg"),
    ("Премиальная хира́мантия_ карта возможностей.png", "phone.jpg"),
    ("Минималистичная вилла у моря.png", "atrium.jpg"),
    ("Мускулистый атлет с протеиновым шейком.png", "athlete.jpg"),
)

#: Что лежит в images/` и должно быть в сборке. Раньше сборщик копировал
#: только `png`, `mp4` и `ico`, и все эти файлы оставались бы в исходниках:
#: страница собиралась, а картинки на сервере не появлялись — 404, и
#: витрина выглядела целой.
PICTURE_EXTS = ("png", "jpg", "jpeg", "webp")

HTML = r"""<!DOCTYPE html>
<!-- Витрина хиромантии. Сгенерировано tools/make_palm.py.
     Правьте руками, если страница понадобится всерьёз. -->
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Линии руки — хиромантия как привычка смотреть на себя</title>
<meta name="description" content="Демо-заготовка витрины: разбор рисунка ладони, семь линий и приложение-карта. Мастера, отзывов и истории за страницей нет — вёрстка и содержание вымышлены.">
<link rel="icon" href="data:,">
<link rel="stylesheet" href="style.css">
</head>
<body>

<!-- Плашка. Страница описывает практику, которой нет за этим адресом:
     мастера, истории и отзывов не существует. Молчать об этом значило бы
     выдавать заготовку за действующую витрину. -->
<div class="notice" role="note">
  <strong>Это демо-заготовка.</strong> За страницей нет мастера, истории
  и отзывов — тексты написаны под вёрстку. Хиромантия не является наукой
  и ничего не предсказывает: разбор линий здесь подан как привычка
  смотреть на себя, а не как прогноз.
</div>

<header class="head">
  <p class="mark">ХИРОМАНТИЯ</p>
  <h1>Линии руки</h1>
  <p class="deck">
    Рисунок ладони — единственная часть тела, которая меняется вместе с
    привычками. Им пользуются, чтобы заметить перемену раньше, чем её
    назовут проблемой.
  </p>
  <nav class="nav">
    <a href="#lines">семь линий</a>
    <a href="#app">приложение</a>
    <a href="#about">о методе</a>
    <a href="#start">с чего начать</a>
  </nav>
</header>

<main>

  <!-- Карта линий: главный содержательный блок. -->
  <section id="chart" class="chart">
    <img src="chart.jpg" width="1214" height="1295" decoding="async"
         alt="Карта линий ладони: семь линий с подписями и общим портретом">
    <div class="chart__text">
      <h2>Что вообще смотрят</h2>
      <p class="lead">
        Линий на ладони семь, и они не равнозначны: три разбирают
        постоянство характера, четыре — то, что меняется вместе с
        обстоятельствами.
      </p>
      <p>
        Постоянные — линия жизни, линия ума, линия сердца. Их сравнивают
        с тем, что человек уже знает о себе: если рисунок не сходится с
        самооценкой, значит смотреть надо не на линии, а на то, почему
        человек её врёт.
      </p>
      <p>
        Переменные — линия судьбы, линии Солнца, Меркурия и Интуиции.
        Они меняются с нагрузкой и возрастом, поэтому по ним не
        составляют прогноз, а отмечают направление: что менялось
        и куда шло.
      </p>
    </div>
  </section>

  <!-- Приложение. -->
  <section id="app" class="app-block">
    <div class="app-block__text">
      <h2>Карта в телефоне</h2>
      <p class="lead">
        Тот же разбор, но с фотографией ладони: линии подсвечиваются
        прямо на снимке, подписи меняются при прокрутке.
      </p>
      <ul class="list">
        <li>Съёмка ладони при ровном свете, без вспышки — иначе линии теряются в блике.</li>
        <li>Разметка ищет семь линий и подписывает каждую, а не «кажется, эта — жизнь».</li>
        <li>История разборов остаётся на устройстве и не уходит на сервер.</li>
      </ul>
      <p class="small">
        Макет приложения, а не рабочее приложение: разметки на фото нет,
        показан интерфейс.
      </p>
    </div>
    <img src="phone.jpg" width="1312" height="1199" decoding="async"
         alt="Макет приложения: экран смартфона с картой линий ладони и двумя карточками «Хиромантия — практика самопознания»">
  </section>

  <!-- Обстановка. -->
  <section id="about" class="wide">
    <img src="atrium.jpg" width="1536" height="1024" decoding="async"
         alt="Современный светлый интерьер с видом на море: разбор проходит в спокойной обстановке">
    <div class="wide__text">
      <h2>Где это делают</h2>
      <p class="lead">
        Не в кабинете с диваном и музыкой. Обычно за столом, в тишине,
        рядом с окном — чтобы разговор шёл о человеке, а не о декорациях.
      </p>
      <p>
        Формат — двадцать минут на человека. Больше не нужно: за
        получасовой встречей успевает сказать больше, чем разбор
        показывает, и он перестаёт быть разговором.
      </p>
    </div>
  </section>

  <!-- Направление работы: предметно, без обещаний. -->
  <section id="lines" class="lines">
    <h2>Семь линий</h2>
    <ol class="grid">
      <li><b>Линия жизни</b><span>здоровье и устойчивость привычек</span></li>
      <li><b>Линия ума</b><span>образ мышления и то, как он меняется с возрастом</span></li>
      <li><b>Линия сердца</b><span>то, что человек ставит выше отдыха</span></li>
      <li><b>Линия судьбы</b><span>направление перемен, а не список событий</span></li>
      <li><b>Линия Солнца</b><span>публичность и своё дело</span></li>
      <li><b>Линия Меркурия</b><span>речь, учёба, работа руками</span></li>
      <li><b>Линия интуиции</b><span>когда решение приходит раньше аргументов</span></li>
    </ol>
  </section>

  <!-- Первый шаг. -->
  <section id="start" class="start">
    <h2>С чего начать</h2>
    <div class="two">
      <p class="lead">
        С ладони, которой не видно. Вытяните левую руку ладонью вверх,
        держите её при дневном свете и смотрите на расстоянии вытянутой
        руки — линии должны читаться целиком, а не отрывочно.
      </p>
      <p>
        Не водите пальцем по сгибам и не ищите «свою» линию среди всех:
        сравнение не работает, потому что линия одна. Разговор начинается
        с того, что человек видит на своей ладони первым, и неважно,
        увидит он линию жизни или чёрту между пальцами.
      </p>
    </div>
  </section>

  <!-- Подвал. -->
  <section class="shot">
    <img src="athlete.jpg" width="1122" height="1402" loading="lazy" decoding="async"
         alt="Натурная съёмка: снимок рядом с домашним интерьером">
    <p class="shot__text">
      <b>Материал для съёмки.</b> Фото из натурных съёмок, взято для
      раздела о натурном разборе. Макеты сделаны из таких снимков: одна
      ладонь, ровный свет, без лишнего в кадре.
    </p>
  </section>

</main>

<footer class="foot">
  <p>
    Демо-заготовка вёрстки: мастера, отзывов, цен и истории за страницей
    нет. Внешних загрузок ноль — шрифты системные, картинки свои.
  </p>
  <p class="foot__dim">
    Собрано tools/make_palm.py. Картинки ужаты до 1400 пикселей: исходники
    весили по два мегабайта, и четыре таких на странице съедали бы трафик.
  </p>
</footer>

</body>
</html>
"""

CSS = r"""/* Витрина хиромантии.
 *
 * Палитра — бумага и графит, без золота: набор из «золотых» карточек
 * про судьбу уже есть на соседних витринах, и эта отличается не цветом,
 * а типографикой — крупная антиква на бумаге и очень много воздуха.
 *
 * Шрифты системные намеренно. Своя гарнитура легла бы тяжелее, а
 * страница всё равно открывается без сети: правило проекта запрещает
 * внешние загрузки, и ломать его ради декора смысла нет.
 */

:root {
  --paper: #F4F0E8;
  --paper-2: #EAE4D8;
  --ink: #23201C;
  --ink-soft: #5E574C;
  --rule: #D6CEBE;
  --accent: #7A6A4F;
}

*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: Georgia, 'Times New Roman', 'Iowan Old Style', serif;
  font-size: 18px;
  line-height: 1.7;
  -webkit-text-size-adjust: 100%;
}

/* --- плашка --- */

.notice {
  padding: 14px 24px;
  background: #23201C;
  color: #EFE8DA;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 14px;
  line-height: 1.55;
}

.notice strong { color: #FFF; }

/* --- шапка --- */

.head {
  max-width: 1080px;
  margin: 0 auto;
  padding: clamp(44px, 8vw, 96px) 24px clamp(28px, 5vw, 56px);
}

.mark {
  margin: 0 0 18px;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 11px;
  letter-spacing: 0.34em;
  text-transform: uppercase;
  color: var(--ink-soft);
}

h1 {
  margin: 0 0 18px;
  font-size: clamp(38px, 7vw, 78px);
  font-weight: 400;
  letter-spacing: -0.02em;
  line-height: 1.02;
}

.deck {
  margin: 0 0 28px;
  max-width: 54ch;
  font-size: clamp(18px, 2vw, 22px);
  color: var(--ink-soft);
}

.nav {
  display: flex;
  flex-wrap: wrap;
  gap: 22px;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 14px;
}

.nav a {
  color: var(--ink-soft);
  text-decoration: none;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 2px;
}

.nav a:hover, .nav a:focus-visible { color: var(--ink); border-color: var(--accent); }

/* --- общие секции --- */

main > section {
  max-width: 1080px;
  margin: 0 auto;
  padding: clamp(38px, 6vw, 72px) 24px;
  border-top: 1px solid var(--rule);
}

h2 {
  margin: 0 0 22px;
  font-size: clamp(26px, 3.4vw, 40px);
  font-weight: 400;
  letter-spacing: -0.015em;
  line-height: 1.15;
}

.lead {
  font-size: clamp(19px, 2.1vw, 23px);
  line-height: 1.55;
}

p { margin: 0 0 18px; max-width: 62ch; }

.small {
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 14px;
  color: var(--ink-soft);
}

/* --- карта --- */

.chart {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 6fr);
  gap: clamp(24px, 4vw, 56px);
  align-items: start;
}

.chart img, .app-block img, .wide img, .shot img {
  display: block;
  width: 100%;
  height: auto;
  border: 1px solid var(--rule);
  background: var(--paper-2);
}

/* --- приложение --- */

.app-block {
  display: grid;
  grid-template-columns: minmax(0, 6fr) minmax(0, 5fr);
  gap: clamp(24px, 4vw, 56px);
  align-items: center;
}

.list {
  margin: 0 0 20px;
  padding: 0;
  list-style: none;
  font-size: 17px;
}

.list li {
  position: relative;
  padding-left: 26px;
  margin-bottom: 12px;
}

.list li::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 0.72em;
  width: 9px;
  height: 1px;
  background: var(--accent);
}

/* --- широкий блок --- */

.wide {
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  gap: clamp(24px, 4vw, 56px);
  align-items: center;
}

/* --- семь линий --- */

.grid {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 1px;
  background: var(--rule);
  border: 1px solid var(--rule);
}

.grid li {
  counter-increment: line;
  background: var(--paper);
  padding: 22px 20px;
}

.grid { counter-reset: line; }

.grid li b {
  display: block;
  margin-bottom: 6px;
  font-weight: 400;
  font-size: 20px;
}

.grid li b::before {
  counter-increment: line;
  content: counter(line, decimal-leading-zero) " · ";
  color: var(--accent);
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 13px;
}

.grid li span {
  display: block;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 14px;
  color: var(--ink-soft);
}

/* --- две колонки --- */

.two { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(20px, 3vw, 44px); }

/* --- съёмка --- */

.shot {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 8fr);
  gap: clamp(24px, 4vw, 56px);
  align-items: center;
}

.shot__text {
  margin: 0;
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 15px;
  color: var(--ink-soft);
}

.shot__text b { color: var(--ink); }

/* --- подвал --- */

.foot {
  max-width: 1080px;
  margin: 0 auto;
  padding: 30px 24px 70px;
  border-top: 1px solid var(--rule);
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif;
  font-size: 14px;
  color: var(--ink-soft);
}

.foot p { margin: 0 0 8px; max-width: 74ch; }
.foot__dim { opacity: 0.8; }

:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

@media (max-width: 820px) {
  .chart, .app-block, .wide, .shot, .two { grid-template-columns: 1fr; }
  /* Текст перед картинкой на телефоне: картинка занимает полосу
     и отодвигает текст за экран. */
  .chart img, .app-block img, .wide img, .shot img { order: -1; }
  .shot img { max-width: 320px; }
}

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
"""


def prepare_images(dry: bool) -> int:
    """Скопировать и ужать картинки. Возвращает число проблем."""
    missing = 0
    OUT.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image
    except ImportError:
        print("нужен Pillow для ужатия картинок", file=sys.stderr)
        return 1

    for source_name, target_name in IMAGES:
        source = DOWNLOADS / source_name
        if not source.is_file():
            print(f"  НЕТ ФАЙЛА: {source_name}", file=sys.stderr)
            missing += 1
            continue

        try:
            with Image.open(source) as raw:
                raw.load()
                image = raw.convert("RGB")
        except Exception as exc:
            print(f"  не читается {source_name}: {exc}", file=sys.stderr)
            missing += 1
            continue

        if image.width > MAX_WIDTH:
            ratio = MAX_WIDTH / image.width
            image = image.resize(
                (MAX_WIDTH, int(image.height * ratio)), Image.LANCZOS)

        target = OUT / target_name
        if not dry:
            image.save(target, "JPEG", quality=82, optimize=True,
                       progressive=True)
            src_kb = source.stat().st_size / 1024
            dst_kb = target.stat().st_size / 1024
            print(f"  {target_name:<14} {image.width}x{image.height}  "
                  f"{src_kb:.0f} -> {dst_kb:.0f} КБ "
                  f"({src_kb / max(1.0, dst_kb):.1f}× меньше)")
        else:
            print(f"  {target_name:<14} {image.width}x{image.height} "
                  f"(просмотр, не записано)")

    return missing


def write_page(dry: bool) -> None:
    if dry:
        print("разметка и стиль: просмотр, не записано")
        return
    (OUT / "index.html").write_text(HTML, encoding="utf-8")
    (OUT / "style.css").write_text(CSS, encoding="utf-8")
    print(f"  index.html  {(OUT / 'index.html').stat().st_size / 1024:.0f} КБ")
    print(f"  style.css   {(OUT / 'style.css').stat().st_size / 1024:.0f} КБ")


def main() -> int:
    parser = argparse.ArgumentParser(description="собрать витрину хиромантии")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DOWNLOADS.is_dir():
        print(f"нет папки {DOWNLOADS}", file=sys.stderr)
        return 2

    print(f"исходники: {DOWNLOADS}")
    missing = prepare_images(args.dry_run)
    write_page(args.dry_run)

    if missing:
        print(f"\nНЕ НАЙДЕНО ФАЙЛОВ: {missing}. Загляните в Downloads и "
              f"поправьте IMAGES.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\nэто был просмотр: ничего не записано")
        return 0

    # Страница обязана ссылаться только на то, что рядом лежит.
    # Проверка дешёвая, а ошибка here стоит 404 на живом сайте.
    body = (OUT / "index.html").read_text(encoding="utf-8")
    import re
    refs = re.findall(r'(?:src|href)="([A-Za-z0-9_./-]+\.(?:jpg|png|css|js|webp))"',
                      body)
    absent = [r for r in refs if not (OUT / r).is_file()]
    if absent:
        print(f"\nстраница ссылается на то, чего нет: {', '.join(absent)}",
              file=sys.stderr)
        return 1
    print(f"\nссылок на свои файлы: {len(refs)}, все на месте")

    total = sum(p.stat().st_size for p in OUT.iterdir() if p.is_file())
    print(f"папка целиком: {total / 1024:.0f} КБ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
