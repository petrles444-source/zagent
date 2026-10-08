r"""Собрать единый каталог всех сайтов: баннер, карточки, честные метки.

Зачем
----
Сайтов больше двадцати, и держать их список вручную бессмысленно:
одна забытая строка — и витрина врёт. Здесь список один, и из него
строятся и карточки, и проверка. Правка строки меняет и то и другое.

Что получается
--------------
* баннер на всю ширину — чем витрина открывается;
* группы: портфолио, реклама, лендинги, заглушки;
* отдельными карточками — главная и справочники;
* у каждой карточки превью, нарисованное кодом по её же палитре;
* честная метка состояния: живой, заготовка, демо.

Почему превью рисуются кодом, а не скриншотами
----------------------------------------------
Скриншот перестаёт соответствовать странице после первой же правки:
витрина продолжает показывать старое. Схема описывает форму страницы
и не устаревает. По той же причине в проекте запрещены подставные
картинки работ — рисунок должен соответствовать тому, что на странице.

Про шрифты
----------
Гарнитуры лежат рядом, в `assets/fonts/`, и подключаются локально.
Ссылка на Google Fonts запрещена: без сети витрина не должна
разваливаться.
"""

from __future__ import annotations

import html as html_mod
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = SITE / "catalog.html"

#: Единый список сайтов.
#:
#: Поля: папка, название, чем является, метка, тон, группа.
#: Тон задаёт фон превью: тёмные сайты выглядят тёмными, и витрина
#: перестаёт быть ровным рядом одинаковых прямоугольников.
SITES = (
    # портфолио
    ("aurum", "Aurum", "тёплое золото на светлом", "живой", "light", "Портфолио"),
    ("lumen", "Lumen", "холодное стекло", "живой", "light", "Портфолио"),
    ("onyx", "Onyx", "тёмный люкс", "живой", "dark", "Портфолио"),
    ("neon", "Neon", "тёмный кибер", "живой", "neon", "Портфолио"),
    ("paper", "Paper", "светлая печать", "живой", "light", "Портфолио"),
    ("term", "Term", "терминал", "живой", "dark", "Портфолио"),
    ("steel", "Steel", "белая сталь и стекло", "живой", "light", "Портфолио"),

    # реклама
    ("forno", "Forno", "пицца с доставкой", "демо", "fire", "Реклама"),
    ("dentalia", "Dentalia", "стоматология", "демо", "light", "Реклама"),
    ("vow", "Vow", "свадебный салон", "демо", "gold", "Реклама"),
    ("grind", "Grind", "тренировки", "демо", "dark", "Реклама"),
    ("strobe", "Strobe", "неоновая вечеринка", "демо", "neon", "Реклама"),

    # лендинги
    ("tovar", "NovaTech Store", "витрина готовых сайтов", "демо", "neon", "Лендинги"),
    ("barbie", "Pink Élite", "нейл-салон", "демо", "pink", "Лендинги"),
    ("tex", "NovaTech", "лендинг IT-компании", "демо", "dark", "Лендинги"),

    # заглушки
    ("prism", "Prism", "светлая сетка точек", "заготовка", "light", "Заглушки"),
    ("flux", "Flux", "сеть частиц на canvas", "заготовка", "dark", "Заглушки"),
    ("stone", "Stone", "фактура под лупой", "заготовка", "dark", "Заглушки"),
    ("nova", "Nova", "розовое зарево", "заготовка", "pink", "Заглушки"),
    ("fold", "Fold", "белое на белом", "заготовка", "light", "Заглушки"),
)

#: Порядок групп и пояснение к каждой.
GROUPS = (
    ("Портфолио", "архив флеш-работ, семь подач и справочники — всё на "
     "своих адресах"),
    ("Реклама", "пять витрин из сгенерированных макетов. Бизнеса за ними "
     "нет: телефон, цены и сроки выдуманы"),
    ("Лендинги", "готовые страницы-шаблоны: витрина сайтов, нейл-салон, "
     "IT-компания"),
    ("Заглушки", "нужны, чтобы витрину было на чём проверять: часть "
     "ссылок ведёт в пустоту специально"),
)

#: Карточки вне сетки.
SINGLES = (
    ("index.html", "Главная", "архив флеш-работ с живым воспроизведением",
     "живой"),
    ("guide/neural.html", "Справочники", "четыре гайда: нейронные сети, "
     "pandas, OpenCV, VK API", "живой"),
)

#: Тона превью: два цвета, из которых рисуется плашка.
TONES = {
    "light": ("#F2F3F5", "#23282C"),
    "dark":  ("#14161A", "#E6E8EC"),
    "neon":  ("#170A24", "#F0D8FF"),
    "fire":  ("#1E0C06", "#FFD9C0"),
    "gold":  ("#12100C", "#F2E4C4"),
    "pink":  ("#2A0A1C", "#FFD8EC"),
}

#: Число плиток в плашке. У всех страниц одинаковое, иначе ряд
#: перестаёт быть рядом, а становится лестницей.
TILES = 4


def esc(text: str) -> str:
    return html_mod.escape(str(text))


def preview(tone: str, seed: int) -> str:
    """Плашка-превью. Рисуется полосами, а не картинкой.

    Полоски повторяются по диагонали и с разной толщиной — это
    намёк на сетку страницы. Настоящий скриншот устареет после
    первой правки и начнёт показывать то, чего на странице уже нет.
    """
    bg, fg = TONES[tone]
    bars = []
    for i in range(TILES):
        width = 34 + ((seed + i * 17) % 46)
        bars.append(
            f'<span style="width:{width}%;background:{fg};'
            f'opacity:{0.9 - i * 0.18:.2f}"></span>')
    return (f'<div class="prev prev--{tone}" style="background:{bg}" '
            f'aria-hidden="true">{"".join(bars)}</div>')


def cards_for(group: str) -> str:
    out = []
    for index, (folder, name, note, state, tone, g) in enumerate(SITES):
        if g != group:
            continue
        out.append(
            f'        <a class="card" href="/{folder}/">\n'
            f'{preview(tone, index)}\n'
            f'          <div class="card__body">\n'
            f'            <h3>{esc(name)}</h3>\n'
            f'            <p class="card__note">{esc(note)}</p>\n'
            f'            <p class="card__row"><span class="tag tag--{esc(state)}">'
            f'{esc(state)}</span><code>/{esc(folder)}/</code></p>\n'
            f'          </div>\n'
            f'        </a>')
    return "\n".join(out)


def page() -> str:
    groups = []
    for title, note in GROUPS:
        groups.append(
            f'    <section class="group">\n'
            f'      <div class="group__head">\n'
            f'        <h2>{esc(title)}</h2>\n'
            f'        <p>{esc(note)}</p>\n'
            f'      </div>\n'
            f'      <div class="grid">\n'
            f'{cards_for(title)}\n'
            f'      </div>\n'
            f'    </section>')

    singles = "\n".join(
        f'      <a class="card card--wide" href="/{esc(href)}">\n'
        f'{preview("light", i)}\n'
        f'        <div class="card__body">\n'
        f'          <h3>{esc(name)}</h3>\n'
        f'          <p class="card__note">{esc(note)}</p>\n'
        f'          <p class="card__row"><span class="tag tag--{esc(state)}">'
        f'{esc(state)}</span><code>/{esc(href)}</code></p>\n'
        f'        </div>\n'
        f'      </a>'
        for i, (href, name, note, state) in enumerate(SINGLES))

    total = len(SITES) + len(SINGLES)
    return f"""<!DOCTYPE html>
<!-- Витрина всех сайтов. Сгенерировано tools/make_catalog_site.py.
     Список сайтов один, и из него строятся и карточки, и проверка:
     иначе забытая строка делает витрину врущей. -->
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Каталог сайтов — {total} страниц</title>
<meta name="description" content="Витрина проекта: {len(SITES)} сайтов и справочников, собранных в одном проекте. Каждая карточка ведёт на работающий адрес.">
<link rel="icon" href="data:,">
<link rel="stylesheet" href="assets/fonts/fonts.css">
<link rel="stylesheet" href="catalog.css">
</head>
<body>

<!-- Плашка. Витрина описывает страницы-заготовки и демо-витрины, и
     молчать об этом было бы враньём: посетитель принял бы половину
     ссылок за готовые сайты. -->
<div class="notice" role="note">
  <strong>Часть страниц — заготовки.</strong> Портфолио, справочники и
  главная работают. Рекламные витрины, лендинги и заглушки — демо:
  за ними не стоит бизнеса, а телефоны, цены и отзывы выдуманы.
  Метка под каждой карточкой говорит, что перед вами.
</div>

<header class="head">
  <div>
    <p class="mono">zagent</p>
    <h1>Каталог сайтов</h1>
  </div>
  <p class="count">{total}<span>страниц</span></p>
</header>

<main>
{chr(10).join(groups)}

  <section class="group">
    <div class="group__head">
      <h2>Отдельно</h2>
      <p>страницы, которые не вписываются в группы выше</p>
    </div>
    <div class="grid grid--wide">
{singles}
    </div>
  </section>
</main>

<footer class="foot">
  <p>
    Страница собрана вручную, без сборщика: список сайтов один, и
    карточки строятся из него. Внешних загрузок нет — шрифты лежат
    рядом, в <code>assets/fonts/</code>.
  </p>
  <p class="foot__dim">
    Превью нарисованы кодом, а не скриншотами: снимок устаревает
    после первой правки и начинает показывать то, чего на странице
    уже нет.
  </p>
</footer>

</body>
</html>
"""


CSS = """/* Витрина сайтов.
 *
 * Шрифты локальные: `assets/fonts/fonts.css` рядом. Ссылка на Google
 * Fonts запрещена правилом проекта — без сети витрина не должна
 * разваливаться.
 *
 * Тон превью задаётся в разметке из списка сайтов: тёмные страницы
 * выглядят тёмными. Иначе ряд из одинаковых светлых прямоугольников
 * перестаёт различать страницы между собой.
 */

:root {
  --bg: #0B0D10;
  --panel: #14171C;
  --line: #232830;
  --fg: #EDEEF2;
  --muted: #8B929C;
  --accent: #6FA8FF;
}

@media (prefers-color-scheme: light) {
  :root {
    --bg: #F6F7F9;
    --panel: #FFFFFF;
    --line: #E2E5EA;
    --fg: #1A1D22;
    --muted: #6B7280;
    --accent: #2C6BD1;
  }
}

*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  /* Inter из assets/fonts, с системным запасным: без сети шрифт не
     подгрузится, и страница останется читаемой. */
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, Arial,
               sans-serif;
  font-size: 16px;
  line-height: 1.6;
  -webkit-text-size-adjust: 100%;
}

/* --- плашка --- */

.notice {
  padding: 13px 24px;
  background: rgba(255, 193, 7, 0.12);
  border-bottom: 1px solid rgba(255, 193, 7, 0.4);
  color: #FFD97A;
  font-size: 14px;
}

.notice strong { color: #FFF0C4; font-weight: 600; }

/* --- шапка --- */

.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  max-width: 1240px;
  margin: 0 auto;
  padding: 52px 24px 34px;
  border-bottom: 1px solid var(--line);
}

.mono {
  margin: 0 0 6px;
  font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace;
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--muted);
}

h1 {
  margin: 0;
  font-size: clamp(30px, 4.6vw, 50px);
  font-weight: 800;
  letter-spacing: -0.025em;
  line-height: 1.05;
}

.count {
  margin: 0;
  font-size: 46px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1;
  color: var(--accent);
}

.count span {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  font-weight: 400;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}

/* --- группы --- */

main { max-width: 1240px; margin: 0 auto; padding: 0 24px 8px; }

.group { padding: 46px 0; border-bottom: 1px solid var(--line); }
.group:last-of-type { border-bottom: 0; }

.group__head { margin-bottom: 24px; }

.group__head h2 {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.015em;
}

.group__head p {
  margin: 0;
  max-width: 62ch;
  font-size: 14.5px;
  color: var(--muted);
}

/* --- сетка --- */

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(268px, 1fr));
  gap: 16px;
}

.grid--wide { grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }

/* --- карточка --- */

.card {
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  color: inherit;
  text-decoration: none;
  transition: transform 0.18s ease, border-color 0.18s ease;
}

.card:hover {
  transform: translateY(-3px);
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line));
}

/* --- превью --- */

.prev {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 14px 16px;
  aspect-ratio: 16 / 9;
  border-bottom: 1px solid var(--line);
}

.prev span { display: block; height: 7px; border-radius: 2px; }

/* --- тело карточки --- */

.card__body { padding: 14px 16px 16px; display: flex; flex-direction: column; flex: 1; }

.card__body h3 { margin: 0 0 4px; font-size: 17px; font-weight: 600; }

.card__note {
  margin: 0 0 14px;
  font-size: 14px;
  color: var(--muted);
  /* Описание не должно отжимать мета-строку вниз: у карточек
     разной длины подпись прыгала бы по высоте. */
  flex: 1;
}

.card__row {
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.card__row code {
  font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace;
  font-size: 12px;
  color: var(--muted);
}

.tag {
  font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace;
  font-size: 10.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid;
}

/* Метка состояния — единственное место с цветом в тёмной теме:
   она отвечает на вопрос «работает ли это», и ответ должен
   читаться сразу. */
.tag--живой { color: #4ADE80; border-color: #4ADE80; background: rgba(74, 222, 128, 0.12); }
.tag--демо { color: #FBBF24; border-color: #FBBF24; background: rgba(251, 191, 36, 0.12); }
.tag--заготовка { color: #94A3B8; border-color: #94A3B8; background: rgba(148, 163, 184, 0.12); }

@media (prefers-color-scheme: light) {
  .tag--живой { color: #15803D; border-color: #15803D; background: rgba(21, 128, 61, 0.10); }
  .tag--демо { color: #A16207; border-color: #A16207; background: rgba(161, 98, 7, 0.10); }
  .tag--заготовка { color: #64748B; border-color: #64748B; background: rgba(100, 116, 139, 0.10); }
}

/* --- подвал --- */

.foot {
  max-width: 1240px;
  margin: 0 auto;
  padding: 30px 24px 60px;
  border-top: 1px solid var(--line);
  font-size: 14px;
  color: var(--muted);
}

.foot p { margin: 0 0 10px; max-width: 72ch; }

.foot__dim { font-size: 13px; opacity: 0.85; }

.foot code {
  font-family: 'JetBrains Mono', ui-monospace, Consolas, monospace;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 1px 5px;
}

:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
"""


def main() -> int:
    missing = [folder for folder, *_ in SITES if not (SITE / folder).is_dir()]
    if missing:
        print("нет папок: " + ", ".join(missing), file=sys.stderr)
        return 1

    used = {g[0] for g in GROUPS}
    if used != {s[5] for s in SITES}:
        print("группы в GROUPS не совпадают с группами в SITES", file=sys.stderr)
        return 1

    OUT.write_text(page(), encoding="utf-8")
    (SITE / "catalog.css").write_text(CSS, encoding="utf-8")

    size = OUT.stat().st_size / 1024
    print(f"записан {OUT.relative_to(ROOT)}  ({size:.0f} КБ)")
    print(f"записан {(SITE / 'catalog.css').relative_to(ROOT)}  "
          f"({(SITE / 'catalog.css').stat().st_size / 1024:.0f} КБ)")
    print(f"карточек: {len(SITES)} в группах + {len(SINGLES)} отдельно = "
          f"{len(SITES) + len(SINGLES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
