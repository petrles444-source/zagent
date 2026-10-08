r"""Собрать портал в плоский вид и залить на хостинг.

Зачем плоский
-------------
FTP этого хостинга не умеет создавать папки и не пускает исполняемые
страницы: `STOR portal/x` отвечает «доступ запрещён», а `.php` — «553
Prohibited file extension». Значит, всё ложится в один корень.

Поэтому исходники живут как удобно (`site/assets`, `site/ruffle`,
`site/swf`), а на сервер уходит `site-dist` — один каталог, где:

* пути в разметке и в CSS переписаны в корень;
* `publicPath` движка сброшен, иначе он ищет ядро в папке `ruffle/`;
* имена файлов не меняются: Ruffle грузит `core.ruffle.<хэш>.js`
  относительно каталога скрипта, и переименование его сломает.

Запуск:
    .venv\Scripts\python.exe tools\build_site.py
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site"
DIST = ROOT / "site-dist"

#: Двоичные файлы, которые копируются как есть, потому что ссылаются на
#: них страницы. Шрифты и ядро движка попадают в корень перебором папок,
#: а эти лежат в корне исходников и потерялись бы при смене сбора.
#: Двоичные файлы, которые копируются как есть, потому что ссылаются на
#: них страницы. Шрифты и ядро движка попадают в корень перебором папок,
#: а эти лежат в корне исходников и потерялись бы при смене сбора.
#:
#: Виджет агента лежит в assets/, но подключается с корневых страниц
#: относительным путём, поэтому в сборке он тоже должен оказаться в корне.
EXTRA_BINARIES = ("favicon.ico",)

#: Папки, которые сохраняются в сборке как есть. Всё остальное из
#: `assets/` сплющивается в корень: замены путей в REWRITES рассчитаны
#: на плоскую сборку, и без этого страницы не найдут своих файлов.
#:
#: Пять рекламных витрин добавлены сюда вручную. Пока их не было в
#: списке, они молча выпадали из сборки: сборщик рапортовал об успехе,
#: папок в `site-dist/` не появлялось, и на сервере их не было — хотя
#: витрина обещала эти адреса. Молчание тут опаснее ошибки: ошибку
#: видно по красному выводу, а отсутствие папки — нигде.
KEEP_FOLDERS = ("guide", "tex", "barbie", "tovar",
                "forno", "dentalia", "vow", "grind", "strobe", "tma",
                "palm",
                # --- папки макетов из demo (вставляется register_folders.py) ---
                "aetheris", "auraspin", "academy", "palmistry", "palmchart",
                "shaurma", "apex", "zov", "taiga", "auratravel", "cakes",
                "realtravel", "pizzafire", "foodie", "guardbase", "modern",
                "iskra", "horology", "lumiere3d", "lumiere", "nariaidy",
                "naturespace", "novastore", "oboi", "soramoku"
# --- конец папок макетов ---
                )

#: Папки макетов из demo: содержимое копируется целиком, потому что
#: имена файлов задаёт генератор загрузки, а не человек. Список
#: вырезан по имени первой папки — иначе пришлось бы дублировать
#: двадцать пять строк во второй раз.
DEMO_FOLDERS = KEEP_FOLDERS[KEEP_FOLDERS.index("aetheris"):]

#: Папки, которых в сборке нет намеренно: их выкладывает отдельный
#: загрузчик портфолио (tools/upload_portfolios.py), потому что у них
#: свои папки на сервере. Проверка каталога не должна считать их
#: пропавшими — иначе сборка сайта блокируется из-за страниц, которые
## и не обязана собирать.
EXTERNAL_FOLDERS = ("aurum", "lumen", "neon", "onyx", "paper", "term",
                    "steel", "prism", "flux", "stone", "nova", "fold")

#: Замены путей в текстовых файлах. Порядок важен: сначала длинные
#: (каталог с именем файла), затем голые имена каталогов.
REWRITES: tuple[tuple[str, str], ...] = (
    ("assets/fonts.css", "fonts.css"),
    ("assets/style.css", "style.css"),
    ("assets/app.js", "app.js"),
    ("assets/catalog.json", "catalog.json"),
    ("assets/catalog.css", "catalog.css"),
    ("assets/chat.css", "chat.css"),
    ("assets/chat.js", "chat.js"),
    ("assets/config.json", "config.json"),
    ("assets/slider.js", "slider.js"),
    ("assets/favicon.png", "favicon.png"),
    ("assets/img/", "img/"),
    # Превью каталога. Без этого правила снимки искались бы по пути
    # `assets/shots/…`, которого в плоской сборке не существует: папка
    # `assets/` в сборке разбирается на отдельные файлы в корне.
    ("assets/shots/", "shots/"),
    ("ruffle/ruffle.js", "ruffle.js"),
    ("fonts/", ""),
    ("swf/", ""),
)

#: `publicPath` указывает движку, где искать ядро и .wasm. В плоской
#: сборке ядро лежит рядом со скриптом, поэтому путь должен быть пустым.
PUBLIC_PATH_OLD = "publicPath: 'ruffle/'"
PUBLIC_PATH_NEW = "publicPath: ''"


def rewrite(text: str) -> str:
    """Переписать пути к файлам сборки на корневые."""
    for old, new in REWRITES:
        text = text.replace(old, new)
    text = text.replace(PUBLIC_PATH_OLD, PUBLIC_PATH_NEW)
    # В CSS и JSON пути заключены в кавычки: после удаления префикса
    # остаётся 'fonts.css' — это верно. А вот `url('fonts/x.woff2')`
    # должен стать `url('x.woff2')`, что REWRITES уже сделал.
    return text


def stamp_assets() -> None:
    """Дописать к ссылкам на скрипты и стили метку содержимого.

    Хостинг кэширует статику надолго, и после правки страница продолжает
    работать на старой версии файла: это выглядит как «ничего не
    изменилось», хотя поменялось всё. Метка `?v=…` считается от
    содержимого самих файлов, поэтому меняется ровно тогда, когда
    меняется файл, и вручную её поддерживать не нужно.
    """
    digest = hashlib.sha256()
    for item in sorted(DIST.iterdir()):
        if item.suffix in (".css", ".js") and item.is_file():
            digest.update(item.name.encode("utf-8"))
            digest.update(item.read_bytes())
    mark = digest.hexdigest()[:10]

    index = DIST / "index.html"
    text = index.read_text(encoding="utf-8")
    # Метку ставим только на локальные файлы: внешних адресов быть не
    # должно (см. проверку выше).
    text = re.sub(r'(<(?:script|link)[^>]*?\b(?:src|href)=")([A-Za-z0-9_.-]+\.(?:js|css))(")',
                  lambda m: f"{m.group(1)}{m.group(2)}?v={mark}{m.group(3)}",
                  text)
    # Ссылка «обновить страницу» в подвале: у документа кэш в 20 дней,
    # а адрес с меткой — другой, поэтому вернувшийся посетитель сам
    # выбирает свежую копию одной ссылкой.
    text = re.sub(r'<a class="foot-ver" id="footVer" href="#" rel="nofollow">[^<]*</a>',
                  f'<a class="foot-ver" id="footVer" href="index.html?v={mark}" '
                  f'rel="nofollow">сборка {mark} · обновить</a>',
                  text)
    index.write_text(text, encoding="utf-8")

    # Метка ставится на ВСЕ страницы, а не только на главную.
    # Страницы в подпапках ссылаются на свои css и js без метки, и
    # браузер месяцами держал их в кэше: правка в `store.css`
    # доходила до сервера и лежала там новая, а у посетителя и в моём
    # браузере продолжала применяться старая. Выглядело как «styles не
    # применились», хотя файл на сервере был правильный.
    for page in sorted(DIST.rglob("*.html")):
        if page.name == "index.html" and page.parent == DIST:
            continue                      # главная уже обработана выше
        source = page.read_text(encoding="utf-8")
        stamped = re.sub(
            r'(<(?:script|link)[^>]*?\b(?:src|href)=")([A-Za-z0-9_.-]+\.(?:js|css))(")',
            lambda m: f"{m.group(1)}{m.group(2)}?v={mark}{m.group(3)}",
            source)
        if stamped != source:
            page.write_text(stamped, encoding="utf-8")

    print(f"метка версии: v={mark}")


def main() -> int:
    if DIST.exists():
        # На Windows папку может держать антивирус или уже открытый
        # проводник — `rmtree` тогда падает с «Access is denied».
        # Сборка не должна из-за этого вставать: удаляем что можем и
        # досоздаём каталог, а лишние файлы попадут в проверку путей.
        shutil.rmtree(DIST, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)

    count = 0
    size = 0

    # 1. Текстовые файлы — с переписанными пути.
    #
    #    Куда класть результат, решается по имени:
    #      * `assets/…` — сплющивается в корень, как и раньше: страницы
    #        ссылаются на `style.css`, а не на `assets/style.css`, и
    #        замены путей в REWRITES рассчитаны именно на плоскую сборку;
    #      * `guide/…`, `tex/…` — сохраняют подпапку. Раньше здесь стояло
    #        `DIST / Path(name).name`, и `tex/index.html` тихо лёг бы в
    #        корень и перезаписал бы главную страницу: сборщик отчитался
    #        бы об успехе, а на сайте открылся бы лендинг вместо архива.
    for name in ("index.html", "catalog.html",
                 "guide/vk-api.html", "guide/pandas.html",
                 "guide/opencv.html", "guide/neural.html",
                 "tex/index.html", "tex/css.css",
                 "tex/javascript.js", "tex/demo.css",
                 "barbie/index.html", "barbie/css.css",
                 "barbie/js.js", "barbie/demo.css", "barbie/clips.css",
                 "tovar/index.html", "tovar/style.css",
                 "tovar/store.css", "tovar/demo.css", "tovar/script.js",
                 # Пять рекламных витрин. Файлы перечислены поимённо, а
                 # не папкой: список текстовых файлов общий для всех
                 # подпапок, и перебор по папке зацепил бы заодно то,
                 # что класть не нужно.
                 "forno/index.html", "forno/style.css",
                 "dentalia/index.html", "dentalia/style.css",
                 "vow/index.html", "vow/style.css",
                 "grind/index.html", "grind/style.css",
                 "strobe/index.html", "strobe/style.css",
                 # Мини-приложение для Telegram.
                 "tma/index.html", "tma/style.css", "tma/app.js",
                 # Витрина хиромантии из готовых макетов.
                 "palm/index.html", "palm/style.css",
                 # --- папки макетов из demo (вставляется register_folders.py) ---
                 "aetheris/index.html", "auraspin/index.html",
                 "academy/index.html", "palmistry/index.html",
                 "palmchart/index.html", "shaurma/index.html",
                 "apex/index.html", "zov/index.html", "taiga/index.html",
                 "auratravel/index.html", "cakes/index.html",
                 "realtravel/index.html", "pizzafire/index.html",
                 "foodie/index.html", "guardbase/index.html",
                 "modern/index.html", "modern/style.css",
                 "modern/script.js", "iskra/index.html",
                 "horology/index.html", "lumiere3d/index.html",
                 "lumiere/index.html", "nariaidy/index.html",
                 "naturespace/index.html", "novastore/index.html",
                 "novastore/style.css", "novastore/script.js",
                 "oboi/index.html", "soramoku/index.html",
                 # --- конец папок макетов ---
                 "assets/style.css",
                 "assets/app.js", "assets/fonts.css", "assets/catalog.json",
                 "assets/catalog.css", "assets/chat.css", "assets/chat.js",
                 "assets/config.json", "assets/slider.js"):
        source = SRC / name
        relative = Path(name)
        target = DIST / (relative if relative.parts[0] in KEEP_FOLDERS
                         else Path(relative.name))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewrite(source.read_text(encoding="utf-8")),
                          encoding="utf-8")
        count += 1
        size += target.stat().st_size

    # 2. Двоичные файлы копируются как есть: имена важны для движка.
    #    Исключение — файлы без расширения (лицензии Ruffle): хостинг
    #    отвечает на них «553 Prohibited file name», поэтому дописываем
    #    `.txt`. Сами лицензии у Ruffle обязательны, выбрасывать их нельзя.
    for source_dir, dest in ((SRC / "ruffle", DIST),
                          (SRC / "swf", DIST),
                          (SRC / "assets" / "fonts", DIST)):
        for item in source_dir.glob("*"):
            if not item.is_file():
                continue
            # Папка `fonts/` копируется в корень целиком, и её
            # `fonts.css` там оказывался вторым файлом с тем же именем,
            # что уже положен из `assets/fonts.css`. Копирование шло
            # позже и молча затирало обработанный сборщиком файл
            # своим, с путями `fonts/…`, которые в плоской сборке
            # неверны.
            #
            # На видно это только на ошибке сборки, и выглядит она
            # неправдоподобно: страницы подключают `fonts.css`, шрифты
            # лежат рядом, а сборщик ругается на `fonts/inter-…`.
            # Поэтому `fonts.css` из папки наружу не выпускаем, а его
            # наличие — предупреждение, а не молчание: правило
            # @font-face должно жить в `assets/fonts.css`.
            if item.name == "fonts.css" and source_dir == SRC / "assets" / "fonts":
                print(f"ВНИМАНИЕ — {source_dir.relative_to(ROOT) / item.name} "
                      f"не копируется: правило @font-face должно быть "
                      f"в site/assets/fonts.css, иначе оно затрёт "
                      f"собранную версию. Файл со шрифтами лишний.")
                continue
            name = item.name if "." in item.name else item.name + ".txt"
            target = dest / name
            shutil.copy2(item, target)
            count += 1
            size += target.stat().st_size

    # 2a. Картинки в корне: иконка страницы и favicon.png. Подпапка img/
    #    на сервере создаётся загрузчиком папок, содержимое копируется
    #    сюда же, чтобы не держать две копии в корне.
    for name in EXTRA_BINARIES:
        source = SRC / name
        if not source.is_file():
            print(f"НЕТ ФАЙЛА {source}", file=sys.stderr)
            return 1
        shutil.copy2(source, DIST / name)
        count += 1
        size += (DIST / name).stat().st_size

    shutil.copy2(SRC / "assets" / "favicon.png", DIST / "favicon.png")
    count += 1
    size += (DIST / "favicon.png").stat().st_size

    # 2b. Виджет агента. Настройки кладёт tools/place_ai_config.py уже
    #     сюда, в корень сборки; из assets берём только два файла кода.
    #
    #     Копия нужна в каждой подпапке со страницей: виджет ищет
    #     настройки рядом с собой, и без своей копии в `tex/` он
    #     отдавал бы 404 на оба файла — страница при этом выглядела бы
    #     целой, а кнопка просто не появлялась бы.
    for name in ("ai.js", "ai.css"):
        shutil.copy2(SRC / "assets" / name, DIST / name)
        count += 1
        size += (DIST / name).stat().st_size
        for folder in KEEP_FOLDERS:
            # Мини-приложение — не страница сайта, а окно в Telegram.
            # Виджет чата там не нужен и вреден: он ищет `ai.json`
            # рядом с собой, не находит его и прячет кнопку, а сам
            # тянет двенадцать килобайт в папку, которая и так
            # работает сама. Свой интерфейс у приложения свой.
            if folder == "tma":
                continue
            target_folder = DIST / folder
            if not target_folder.is_dir():
                continue
            shutil.copy2(SRC / "assets" / name, target_folder / name)
            count += 1
            size += (target_folder / name).stat().st_size
            # Настройки: из исходников папки, если их туда положил
            # tools/place_ai_config.py, иначе из корня сборки.
            for source_json in (SRC / folder / "ai.json",
                                DIST / "ai.json"):
                if source_json.is_file():
                    shutil.copy2(source_json, target_folder / "ai.json")
                    count += 1
                    size += (target_folder / "ai.json").stat().st_size
                    break
    # Подпапки assets, которые копируются в корень под своим именем.
    #
    # `fonts/` в этом списке нет намеренно: её файлы разбираются
    # отдельно, с переписыванием путей внутри таблиц стилей.
    #
    # `shots/` добавлен после того, как каталог начал показывать
    # настоящие снимки первых экранов. Папки не было в списке, и
    # все тридцать четыре превью отдавали 404: каталог ссылался на
    # `assets/shots/…`, а в сборке её не существовало. По коду это
    # выглядело как «битые картинки», и на глаз в витрине — как пустые
    # рамки.
    for assets_sub in ("img", "shots"):
        source_dir = SRC / "assets" / assets_sub
        if not source_dir.is_dir():
            continue
        (DIST / assets_sub).mkdir(exist_ok=True)
        for item in source_dir.glob("*"):
            if not item.is_file():
                continue
            shutil.copy2(item, DIST / assets_sub / item.name)
            count += 1
            size += (DIST / assets_sub / item.name).stat().st_size

    # 2d. Файлы макетов копируются целиком, а не выборочно.
    #
    #     У папок из demo внутри лежит всё, что страница скачала вместо
    #     внешних загрузок: картинки, шрифты, таблицы стилей, чужие
    #     скрипты (three.min.js, OrbitControls.js). Перечислять их в
    #     списке текстовых файлов бессмысленно — их имена задаёт
    #     генератор, и каждый прогон они другие.
    #
    #     Раньше копировались только перечисленные файлы, и сборка
    #     честно останавливалась: страница ссылалась на свой же
    #     `three.min.js`, а в сборке его не было. Список на 25 папок
    #     с неизвестными именами — это то же самое, от чего мы уходили
    #     с рекламными витринами.
    for folder in DEMO_FOLDERS:
        source_dir = SRC / folder
        if not source_dir.is_dir():
            continue
        (DIST / folder).mkdir(parents=True, exist_ok=True)
        for item in source_dir.iterdir():
            if not item.is_file():
                continue
            target = DIST / folder / item.name
            shutil.copy2(item, target)
            count += 1
            size += target.stat().st_size


    # 2c. Каждая локальная ссылка из страниц должна вести в сборку.
    #     Проверка нужна, потому что пропущенный в копировании файл
    #     даёт 404 на живом сайте и выглядит как «слайдер сломался»,
    #     хотя сборщик отчитался об успехе: страниц он не смотрит.
    #
    #     Строгость разная, и это осознанно:
    #       * js и css — без них страница не работает, сборка стоп;
    #       * картинки — оформление. Останавливать из-за них выкладку
    #         нельзя: тогда не выйдет залить вообще ничего, пока
    #         художник не нарисует три фона. Их перечисляем, чтобы
    #         починить, но не блокируем.
    missing_code: list[str] = []
    missing_pics: list[str] = []
    # Все страницы сборки, а не только две: подпапка `tex/` иначе
    # проверялась бы вслепую, и сломанная ссылка в ней прошла бы
    # незамеченной.
    pages = sorted(p for p in DIST.rglob("*.html"))
    for page_file in pages:
        page = page_file.relative_to(DIST).as_posix()
        body = page_file.read_text(encoding="utf-8")
        for ref in re.findall(r'(?:src|href)="([A-Za-z0-9_./-]+\.(?:js|css|png|webp|ico))"',
                              body):
            ref = ref.split("?")[0]
            if (DIST / ref).is_file():
                continue
            # Ссылка из подпапки на свой файл разрешается от неё самой.
            if (page_file.parent / ref).is_file():
                continue
            line = f"{page} -> {ref}"
            if ref.endswith((".js", ".css")):
                missing_code.append(line)
            else:
                missing_pics.append(line)

    if missing_code:
        print("НЕ СОБРАНО — страница ссылается на код, которого нет:")
        for line in sorted(set(missing_code)):
            print(f"   {line}")
        return 1

    if missing_pics:
        print("ВНИМАНИЕ — страница ссылается на картинки, которых нет:")
        for line in sorted(set(missing_pics)):
            print(f"   {line}")
        print("   Сборка продолжена: оформление можно поправить позже.")

    # 2c. Картинки и видео сайтов в подпапках. Копируются как есть:
    #     пережимать видео нельзя, а постеры уже готового размера.
    for folder in KEEP_FOLDERS:
        source_dir = SRC / folder
        if not source_dir.is_dir():
            continue
        # `jpg` и `jpeg` добавлены ради пяти рекламных витрин: их макеты
        # лежат именно в jpg. Раньше в списке были только png, mp4 и
        # ico, и картинки витрин оставались в исходниках — страница
        # собиралась, ссылка на `hero.jpg` вела в никуда, а проверка
        # путей писала про это лишь в списке «картинки можно поправить
        # позже». То есть молча, и сборка уходила на сервер битой.
        for pattern, dest_name in (("*.png", folder), ("*.jpg", folder),
                                   ("*.jpeg", folder), ("*.webp", folder),
                                   ("*.mp4", folder), ("*.ico", folder)):
            for item in source_dir.glob(pattern):
                # Референсные листы — черновики для согласования, а не
                # часть страницы: в разметку они не подключены, и
                # выкладывать их на хостинг незачем.
                if item.name.startswith("ref-"):
                    continue
                target = DIST / dest_name / item.name
                shutil.copy2(item, target)
                count += 1
                size += target.stat().st_size

    # 3. Проверка: в собранных файлах не должно остаться ссылок на
    #    вложенные пути. Ищем `папка/имя.файл`, а не просто `папка/`:
    #    слово «ruffle/» в комментарии или в minified-коде движка — не
    #    ссылка, и ругаться на него нельзя. Сам движок и package.json
    #    не проверяем: они приходят из дистрибутива Ruffle как есть.
    checked = ("index.html", "catalog.html", "guide/vk-api.html",
               "guide/pandas.html", "guide/opencv.html", "guide/neural.html",
               "tex/index.html", "tex/css.css", "tex/javascript.js",
               "tex/demo.css", "style.css", "app.js",
               "catalog.json", "catalog.css", "fonts.css", "chat.css",
               "chat.js", "config.json")
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.-])(assets|ruffle|swf|fonts)/([A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,5})")
    leftovers: list[str] = []
    for name in checked:
        item = DIST / name
        if not item.exists():
            leftovers.append(f"{name}: нет в сборке")
            continue
        for match in pattern.finditer(item.read_text(encoding="utf-8")):
            leftovers.append(f"{name}: {match.group(0)}")
    if leftovers:
        print("НЕ СОБРАНО — остались вложенные пути:")
        for line in leftovers:
            print("   " + line)
        return 1

    # 4. Загружаемых внешних ресурсов быть не должно: правило проекта —
    #    без CDN, иначе сайт не откроется без интернета. Обычная
    #    гиперссылка в тексте (например, на ruffle.rs) не считается:
    #    её не нужно, чтобы страница загрузилась.
    external = []
    for name in checked:
        body = (DIST / name).read_text(encoding="utf-8")
        external += [m.group(0) for m in
                     re.finditer(r'(?:src|<link[^>]*href)="https?://[^"]+', body)]
    if external:
        print("ВНИМАНИЕ — страница тянет что-то снаружи:")
        for line in external:
            print("   " + line)
        return 1

    stamp_assets()
    print(f"site-dist: {count} файлов, {size / 1024 / 1024:.1f} МБ")
    print("проверка путей: чисто")

    # 5. Каталог лежит в корне, а портфолио — в подпапках. Проверяем,
    #    что на каждую ссылку каталога в сборке действительно есть
    #    файл: иначе витрина обещает страницы, которые отдадут 404.
    catalog = DIST / "catalog.html"
    if catalog.is_file():
        body = catalog.read_text(encoding="utf-8")
        # Относительные адреса вида `/aurum/` в плоской сборке остаются
        # такими же: подпапки портфолио на сервере есть, их выкладывает
        # отдельный загрузчик. Проверяем только те, что лежат в корне.
        # Хвост `?v=…` допускается и здесь: после добавления меток
        # версий ссылки на css и js перестали совпадать с этим
        # образцом, и проверка молча перестала убеждаться, что файлы
        # в корне вообще есть. Число падало — но никто его не смотрел.
        local = re.findall(
            r'(?:src|<link[^>]*href)="([A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,5})(?:\?[^"]*)?"',
            body)
        # Карточки гайдов и лендинга — обычные ссылки с ведущим
        # слэшем: `/guide/pandas.html`, `/tex/`. Их старая проверка
        # не видела, поэтому витрина могла обещать страницу, которой
        # в сборке нет, и узнать об этом можно было только кликом по
        # живому сайту.
        #
        # Хвост `?v=…` обязателен в образце: после добавления меток
        # версий ссылки перестали совпадать, и проверка молча
        # перестала проверять три ссылки — число падало с 19 до 16,
        # а никто этого не замечал.
        cards = re.findall(
            r'<a[^>]*href="/([A-Za-z0-9_./-]+\.html)(?:\?[^"]*)?"', body)
        folders = re.findall(
            r'<a[^>]*href="/([A-Za-z0-9_.-]+/)"', body)
        for name in cards:
            if not (DIST / name).is_file():
                print(f"НЕ СОБРАНО — каталог обещает страницу, которой нет: "
                      f"{name}")
                return 1
        local += cards

        # Ссылка на папку обязана содержать index.html: иначе витрина
        # ведёт в никуда и на сервере покажет листинг или 404.
        for name in folders:
            stem = name.rstrip("/")
            index = DIST / name / "index.html"
            if index.is_file():
                continue
            if stem in EXTERNAL_FOLDERS:
                print(f"каталог: {name} выкладывается загрузчиком портфолио")
                continue
            if (DIST / name).is_dir():
                # Папка есть, но без index.html — витрина ведёт в
                # листинг каталога, а это не страница.
                print(f"НЕ СОБРАНО — в папке {name} нет index.html")
                return 1
            print(f"НЕ СОБРАНО — каталог обещает папку {name}, "
                  f"которой нет")
            return 1
        for name in local:
            if not (DIST / name).is_file():
                print(f"НЕ СОБРАНО — каталог ссылается на отсутствующий "
                      f"{name}")
                return 1
        print(f"каталог: проверено ссылок — {len(local) + len(folders)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
