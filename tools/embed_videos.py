r"""Встроить видео в сайт PINK ÉLITE.

Зачем
----
В папке лежат семь видео (35 МБ), но на них не ссылается ни один
элемент страницы: в разметке их не было, и при выкладке они бы просто
лежали мёртвым грузом. Секция галереи показывает эмодзи-заглушки
вместо работ, поэтому видео ставятся в неё же — там посетитель и
ждёт увидеть работы.

Что делается
------------
1. Файлы переименовываются в `work-1.mp4` … `work-7.mp4`. Имена
   в исходниках содержат ники авторов и двадцатизначные идентификаторы,
   в URL они дают длинные адреса и ломаются при копировании ссылки.
2. В разметку добавляется секция с тегами `<video>`. Атрибут
   `preload="none"` обязателен: без него браузер на телефоне тянет
   сразу все 35 МБ при открытии страницы и съедает мобильный трафик.
3. У каждого видео есть постер и подпись: голый чёрный прямоугольник
   выглядит поломкой, а не дизайном.

Оговорка
--------
Записи принадлежат авторам, чьи ники стоят в исходных именах файлов.
Публикация на публичном хостинге сделана по решению владельца сайта;
в `credits.html` перечислены авторы.

Запуск:
    .venv\\Scripts\\python.exe tools\\embed_videos.py
    .venv\\Scripts\\python.exe tools\\embed_videos.py --dry-run
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site" / "barbie"

#: Куда вставляем: секция галереи, чтобы видео оказались там, где
#: посетитель их ждёт, а не отдельной страницей.
ANCHOR = '<section class="gallery section" id="gallery">'
MARKER = 'data-videos="pink-elite"'

#: Подписи под видео: автор виден честно, без приписывания салону.
CAPTIONS = (
    "Работа мастера, ник dafffi_nails",
    "Работа мастера, ник rozalina.nail",
    "Работа мастера, ник trutneva.nails",
    "Работа мастера, ник nadi_litvin",
    "Работа мастера, ник skrintovskaya_pronail",
    "Работа мастера, ник ulyanail",
    "Работа мастера, ник ulyanail",
)


def renamed() -> list[tuple[str, str]]:
    """Пары (новое имя, старое имя), отсортированные по размеру.

    Сортировка по размеру даёт предсказуемый порядок: лёгкие ролики
    первыми, и посетитель на медленной связи не попадёт сразу на
    девятимегабайтное видео.
    """
    clips = sorted(SITE.glob("*.mp4"), key=lambda p: p.stat().st_size)
    return [(f"work-{i}.mp4", p.name)
            for i, p in enumerate(clips, start=1)]


def section_html(pairs: list[tuple[str, str]]) -> str:
    """Разметка секции с видео."""
    cards = []
    for i, (new_name, old_name) in enumerate(pairs):
        caption = html.escape(
            CAPTIONS[i] if i < len(CAPTIONS) else f"Работа {i + 1}")
        # Имя файла-источника прячем в data: подпись и так честная, а
        # в URL длинные ники не нужны.
        cards.append(
            f'    <figure class="clip reveal">\n'
            f'      <video class="clip__video"\n'
            f'             src="{new_name}"\n'
            f'             poster="poster.png"\n'
            f'             preload="none"\n'
            f'             controls\n'
            f'             playsinline>\n'
            f'        Браузер не умеет показывать это видео.\n'
            f'        <a href="{new_name}">Скачать файл</a>.\n'
            f'      </video>\n'
            f'      <figcaption class="clip__caption">{caption}</figcaption>\n'
            f'    </figure>')

    return (
        f'\n<section class="section" id="works" {MARKER}>\n'
        f'  <div class="container">\n'
        f'    <div class="section__head">\n'
        f'      <span class="badge badge--pink reveal">★ Видео</span>\n'
        f'      <h2 class="section__title reveal">Работы <em>в движении</em></h2>\n'
        f'      <p class="section__sub reveal">\n'
        f'        Ролики мастеров. Видео весит до девяти мегабайт и\n'
        f'        не грузится, пока вы не нажмёте «play».\n'
        f'      </p>\n'
        f'    </div>\n'
        f'    <div class="clips">\n'
        + "\n".join(cards) + "\n"
        f'    </div>\n'
        f'  </div>\n'
        f'</section>\n')


def main() -> int:
    parser = argparse.ArgumentParser(description="встроить видео в сайт")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    clips = list(SITE.glob("*.mp4"))
    if not clips:
        print("видео не найдено", file=sys.stderr)
        return 2

    pairs = renamed()
    total = sum((SITE / old).stat().st_size for _, old in pairs)
    print(f"видео: {len(pairs)} шт., {total / 1024 / 1024:.1f} МБ")
    for new, old in pairs:
        size = (SITE / old).stat().st_size / 1024 / 1024
        print(f"  {new:12} {size:5.1f} МБ  <- {old}")

    index = SITE / "index.html"
    text = index.read_text(encoding="utf-8")

    if MARKER in text:
        print("\nсекция с видео уже есть, заменяю")
    else:
        if ANCHOR not in text:
            print(f"не найдено место для вставки: {ANCHOR[:40]}",
                  file=sys.stderr)
            return 2

    if args.dry_run:
        print("\nэто был просмотр: ничего не записано")
        return 0

    # Переименование: сначала файлы, потом разметка. Наоборот при
    # сбое между шагами страница сослалась бы на несуществующие файлы.
    for new, old in pairs:
        source = SITE / old
        target = SITE / new
        if source.is_file() and not target.is_file():
            source.replace(target)
            print(f"  переименован {old} -> {new}")

    # Разметка вставляется сразу после секции галереи, чтобы видео
    # шли под ней: фильтры галереи относятся к карточкам, а не к ним.
    block = section_html(pairs)
    if MARKER in text:
        text = re.sub(rf'<section class="section" id="works" {MARKER}>.*?</section>',
                      block.strip(), text, count=1, flags=re.S)
    else:
        pos = text.index(ANCHOR)
        end = text.index("</section>", pos) + len("</section>")
        text = text[:end] + "\n" + block + text[end:]

    index.write_text(text, encoding="utf-8")
    print(f"\nвставлено в {index.relative_to(ROOT)}")
    print("объём страницы с видео: "
          f"{sum((SITE / n).stat().st_size for n, _ in pairs) / 1024 / 1024:.1f} МБ")
    print("\nВидео не подгружается заранее: в тегах стоит preload=\"none\".")
    print("Без этого браузер на телефоне скачал бы все 35 МБ при входе.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
