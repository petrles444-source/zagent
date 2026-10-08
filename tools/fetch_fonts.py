r"""Скачать веб-шрифты и положить их локально.

Зачем
----
Пользователь попросил «тяни любые шрифты какие хочешь из интернета».
Прямая ссылка на Google Fonts нарушает правило проекта: страница без
интернета разваливается, и правило это проверяет сборкой.

Поэтому шрифты скачиваются ОДИН РАЗ и кладутся рядом со страницей.
Итог тот же, какой просил пользователь — настоящие веб-шрифты,
а не системные, — но правило не нарушается: файлы свои, и страница
открывается без сети.

Почему нужен нормальный User-Agent
----------------------------------
С Google Fonts по умолчанию приходит TTF — это старый формат, в
четыре раза тяжелее. Если сказать, что пришёл современный браузер,
сервер отдаёт WOFF2, который весит в разы меньше при том же виде.
Разница на всём наборе — десятки мегабайт.

Что кладём
----------
Для каждой гарнитуры — латиница и кириллица. Русский текст без
кириллических подмножеств показывается заменами, и это видно глазом.

Запуск:
    .venv\\Scripts\\python.exe tools\\fetch_fonts.py
    .venv\\Scripts\\python.exe tools\\fetch_fonts.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Куда кладутся сами файлы шрифтов. В корень сборки они попадают
#: отсюда: build_site.py копирует содержимое папки в корень.
OUT = ROOT / "site" / "assets" / "fonts"

#: Куда пишется правило @font-face.
#:
#: Именно сюда, а не в `OUT / "fonts.css"`. Сборщик уже кладёт в корень
#: `assets/fonts.css` — обработанный, с путями без `fonts/`. Если
#: написать второй `fonts.css` внутрь папки со шрифтами, он при
#: копировании ляжет поверх и затёрёт правильный файл: собственный
#: вариант сборщика с неверными путями. Сборка падает уже на
#: проверке, и выглядит это нелепо — страницы подключают `fonts.css`,
#: файлы рядом, а ругается сборщик на `fonts/inter-…`.
#:
#: Здесь же берутся уже объявленные гарнитуры, чтобы новую не дублировать.
CSS = ROOT / "site" / "assets" / "fonts.css"

#: Современный браузер: иначе Google отдаёт TTF вместо WOFF2.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

#: Гарнитуры и начертания. Подмножества: latin + cyrillic, чтобы
#: русский текст не подменялся чужой гарнитурой.
FAMILIES = (
    {"family": "Inter", "slug": "inter",
     "weights": (400, 600, 800), "axes": ""},
    {"family": "Playfair Display", "slug": "playfair",
     "weights": (400, 700), "axes": ""},
    {"family": "JetBrains Mono", "slug": "jetbrains-mono",
     "weights": (400,), "axes": ""},
)


def build_url(family: str, weights: tuple[int, ...], axes: str) -> str:
    """Собрать адрес таблицы стилей Google Fonts.

    Пробелы в названии гарнитуры заменяются на `+`, начертания
    разделяются точкой с запятой. Раньше здесь стояло
    `family.replace(' ', '+')` внутри f-строки с вложенными
    кавычками, и результат получался `I+n+t+e+r+` — сервер отвечал
    400, и скрипт тихо рапортовал «файлов: 0».
    """
    name = family.strip().replace(" ", "+")
    wght = ";".join(str(w) for w in weights)
    spec = f"{name}:wght@{wght}"
    if axes:
        spec += axes
    return f"https://fonts.googleapis.com/css2?family={spec}&display=swap"


def parse_blocks(css: str) -> list[tuple[str, str, str]]:
    """Разобрать таблицу стилей на (подмножество, адрес, unicode-range).

    Порядок сохраняется: каждый блок — одно начертание одного
    подмножества, и подмножества одинакового начертания ошибочно
    склеятся в один @font-face, если не разделять по комментариям.
    """
    out = []
    # Комментарии с названием подмножества не удаляем: по ним ищем.
    current = ""
    for line in css.splitlines():
        line = line.strip()
        if line.startswith("/*") and line.endswith("*/"):
            current = line[2:-2].strip()
            continue
        if line.startswith("@font-face"):
            block = [line]
            # Остальные строки блока добираются по фигурной скобке.
            depth = line.count("{") - line.count("}")
            for nxt in css.splitlines()[css.splitlines().index(line) + 1:]:
                block.append(nxt.strip())
                depth += nxt.count("{") - nxt.count("}")
                if depth <= 0:
                    break
            text = "\n".join(block)
            url = re.search(r"url\((https://[^)]+)\)", text)
            if url:
                out.append((current, url.group(1), text))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="скачать веб-шрифты")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total = 0
    count = 0
    # Правило хранится вместе со своей гарнитурой. Плоский список не
    # годится: на гарнитуру приходится несколько блоков (латиница,
    # кириллица, латиница-расширенная), и при сопоставлении с
    # FAMILIES по порядку правило второй гарнитуры припишется к первой
    # — тогда фильтр «уже объявлена» отсёк бы не то и дописал бы чужое.
    rules: list[tuple[str, str]] = []

    for spec in FAMILIES:
        url = build_url(spec["family"], spec["weights"], spec["axes"])
        if args.dry_run:
            print(f"{spec['family']}: {url}")
            continue
        print(f"{spec['family']}: запрашиваю {url[:70]}…")

        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=60) as answer:
                css = answer.read().decode("utf-8")
        except Exception as exc:
            print(f"  {spec['family']}: не скачалась — {exc}",
                  file=sys.stderr)
            continue

        OUT.mkdir(parents=True, exist_ok=True)
        blocks = parse_blocks(css)
        kept = 0
        for subset, font_url, text in blocks:
            # Только латиница и кириллица: остальные подмножества —
            # вьетнамская, греческая и прочие, они этому сайту не
            # нужны, а весят столько же, сколько нужные.
            if subset not in ("latin", "cyrillic", "latin-ext"):
                continue
            try:
                freq = urllib.request.Request(
                    font_url, headers={"User-Agent": UA})
                with urllib.request.urlopen(freq, timeout=60) as f:
                    data = f.read()
            except Exception as exc:
                print(f"    {subset}: файл не скачался — {exc}",
                      file=sys.stderr)
                continue

            name = f"{spec['slug']}-{subset}-{kept}.woff2"
            (OUT / name).write_bytes(data)
            total += len(data)
            count += 1
            kept += 1

            # Правило переписывается на локальный файл и получает
            # уникальное имя — иначе все @font-face для одной
            # гарнитуры указывали бы на один и тот же файл.
            text = re.sub(r"url\(https://[^)]+\)",
                          f"url('fonts/{name}')", text)
            rules.append((spec["family"], text.strip()))

        print(f"  {spec['family']}: {kept} файлов")

    if args.dry_run:
        print("\nэто был просмотр: ничего не скачано")
        return 0

    header = (
        "/* Локальные веб-шрифты.\n"
        " *\n"
        " * Файлы скачаны один раз и лежат рядом со страницей. Прямая\n"
        " * ссылка на Google Fonts запрещена правилом проекта: без сети\n"
        " * страница разваливается, а страницы этого сайта обязаны её\n"
        " * переживать.\n"
        " *\n"
        " * Сгенерировано tools/fetch_fonts.py. Формат WOFF2, а не TTF:\n"
        " * если не сказать серверу, что пришёл современный браузер, он\n"
        " * отдаст старый формат вчетверо тяжелее.\n"
        " *\n"
        " * Подмножества только latin и cyrillic: без кириллицы русский\n"
        " * текст подменяется чужой гарнитурой, и это видно глазом.\n"
        " */\n\n")

    # Уже объявленные гарнитуры не трогаем: в файле их уже четыре
    # (Orbitron, ShareTechMono, Inter, JetBrainsMono), и сайт ими
    # пользуется. Новую дописываем в конец, а не переписываем файл
    # целиком — иначе скрипт снёс бы оформление главной страницы,
    # которая на Orbitron и ShareTechMono завязана.
    existing = CSS.read_text(encoding="utf-8") if CSS.is_file() else ""
    declared = set(re.findall(r"font-family:\s*['\"]([^'\"]+)['\"]", existing))

    # Правила сопоставлены со своими гарнитурами при сборе, поэтому
    # фильтруем прямо по паре, без попытки восстановить порядок.
    fresh = [text for family, text in rules if family not in declared]
    skipped = [spec["family"] for spec in FAMILIES
               if spec["family"] in declared]

    if not fresh:
        print(f"\nничего не дописываем: в файле уже есть "
              f"{', '.join(skipped) or 'все запрошенные гарнитуры'}")
    else:
        block = header + "\n\n".join(fresh) + "\n"
        CSS.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")
        print(f"\nдописано гарнитур: {len(FAMILIES) - len(skipped)}"
              + (f", пропущено (уже были): {', '.join(skipped)}"
                 if skipped else ""))

    print(f"файлов: {count}, вес: {total / 1024:.0f} КБ")
    print(f"правило: {CSS.relative_to(ROOT)}")

    # Дубль, из-за которого ломался бы сборщик, убираем.
    stray = OUT / "fonts.css"
    if stray.is_file():
        stray.unlink()
        print("удалён лишний site/assets/fonts/fonts.css: он затирал "
              "собранный fonts.css")
    return 0


if __name__ == "__main__":
    sys.exit(main())
