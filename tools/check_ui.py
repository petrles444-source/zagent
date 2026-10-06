"""Проверить интерфейс: жёсткие цвета, повторные объявления, битые ссылки на id.

Запуск: .venv\\Scripts\\python.exe tools\\check_ui.py
Ненулевой код возврата означает, что что-то сломано.

Проверка намеренно грубая и с исключениями на известные ложные срабатывания:
- `const`/`let`/`var` внутри функций — это локальные переменные, а не дубль
  глобального объявления. Дублем считаем только объявление верхнего уровня.
- id ищутся в разметке, а не во всём файле: строковые литералы в JS содержат
  куски HTML-подобного текста, и иначе они дают ложные «найденные» id.

Синтаксис JS проверяет node (`node --check`). Свой парсер шаблонных строк
обманчиво проигрывал вложенные интерполяции и объявлял рабочий интерфейс
сломанным, поэтому без node остаётся только парность скобок.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "hub" / "ui.py"


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    css, _, rest = src.partition("</style>")

    # Разметка — часть до <script>, но id из шаблонных строк тоже считаем:
    # интерфейс рендерит их через innerHTML, и они тоже должны существовать.
    main_script = rest.partition("<script>")[2].partition("</script>")[0]
    head_script = rest.partition("<script>")[0].partition("</body>")[0]
    body = rest.partition("</body>")[2]
    markup = rest.partition("<script>")[0] + body + head_script

    problems = 0

    # 1. Жёсткие цвета в компонентах: тема задаётся токенами, фиксированный
    #    цвет внутри компонента ломает светлую тему.
    lines = css.splitlines()
    start = next((i for i, line in enumerate(lines) if "--sans:" in line), 0)
    allowed_here = {"#fff"}  # булавка переключателя и блик — они не про тему
    colors = []
    for number, line in enumerate(lines[start:], start=start + 1):
        for match in re.finditer(r"#[0-9a-fA-F]{3,8}\b", line):
            color = match.group(0)
            if color in allowed_here:
                continue
            colors.append((number, color, line.strip()[:80]))
    print(f"жёсткие цвета в компонентах: {len(colors)}")
    for number, color, text in colors:
        print(f"  строка {number}: {color}  {text}")

    # Точки тем — исключение: по определению показывают цвет темы.
    dot_colors = [c for c in colors if "themeDot" in c[2]]
    colors = [c for c in colors if c not in dot_colors]
    problems += len(colors)
    print(f"  из них у переключателя тем (допустимо): {len(dot_colors)}")

    # 2. Повторные объявления верхнего уровня: SyntaxError останавливает ВЕСЬ
    #    <script>, и интерфейс перестаёт работать целиком.
    depth = 0
    seen: dict[str, list[int]] = {}
    for number, line in enumerate(main_script.splitlines(), start=1):
        stripped = line.strip()
        if depth == 0:
            match = re.match(r"(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)", stripped)
            if match:
                seen.setdefault(match.group(1), []).append(number)
        depth += line.count("{") - line.count("}")
        depth = max(depth, 0)
    dupes = {name: where for name, where in seen.items() if len(where) > 1}
    print(f"\nповторные объявления JS верхнего уровня: {len(dupes)}")
    for name, where in sorted(dupes.items()):
        print(f"  {name}: строки {where}")
    problems += len(dupes)

    # 3. Ссылки на несуществующие id: элемент не найдётся, блок останется пустым.
    ids = set(re.findall(r'id="([\w-]+)"', markup))
    # id, которые JS создаёт сам через разметку с id="..." внутри строк.
    ids |= set(re.findall(r"id=\\?['\"](\w[\w-]*)", main_script))
    used = set(re.findall(r"\$\('([\w-]+)'\)", main_script))
    missing = sorted(used - ids)
    print(f"\nссылки на несуществующие id: {len(missing)}")
    for name in missing:
        print(f"  {name}")
    problems += len(missing)

    # 4. Обработчики, вызывающие несуществующие функции: клик молча ничего
    #    не делает, и найти это в интерфейсе трудно.
    defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", main_script))
    defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", main_script))
    called: set[str] = set()
    for attr in re.findall(r'on(?:click|change|input|contextmenu)="([^"]+)"', markup):
        called |= set(re.findall(r"(?:^|[;{\s(])([a-zA-Z_$][\w$]*)\s*\(", attr))
    builtin = {"if", "for", "while", "return", "confirm", "prompt", "alert", "event"}
    unknown = sorted(n for n in called if n not in defined and n not in builtin)
    print(f"\nобработчики с несуществующей функцией: {len(unknown)}")
    for name in unknown:
        print(f"  {name}")
    problems += len(unknown)

    # 4b. Вызовы собственных функций внутри скрипта: проверка выше смотрит
    #     только на разметку. Потерянная функция ловилась уже на клике, а не
    #     при запуске — поэтому здесь считаем все известные имена.
    exported = set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", main_script))
    unresolved = sorted(
        n for n in called
        if n not in defined and n not in builtin and n not in exported
    )
    print(f"\nне разрешаются нигде: {len(unresolved)}")
    for name in unresolved:
        print(f"  {name}")
    problems += len(unresolved)

    # 4c. Имена в стиле Python, попавшие в браузерный скрипт: в Python они
    #     есть, в браузере их нет, и код падает с ReferenceError при первом
    #     же вызове. Подробности — в `python_names_in_js`.
    python_names = python_names_in_js(main_script)
    print(f"\nимена в стиле Python в браузерном скрипте: {len(python_names)}")
    for name, where in sorted(python_names.items()):
        print(f"  {name}: строки {where[:5]}")
    problems += len(python_names)

    # 5. Синтаксис JS. Из-за SyntaxError перестаёт выполняться ВЕСЬ скрипт:
    #    интерфейс выглядит живым (разметка на месте, CSS работает), но ни
    #    один обработчик не определён. Именно так выглядел сломанный выбор
    #    модели: вкладки отрисовывались, а по клику ничего не происходило.
    syntax = check_js_syntax(main_script)
    if syntax is None:
        # Отдельной строкой, а не проблемой: проверка не выполнена, и об этом
        # нужно знать. Но и засчитывать её нельзя — иначе любой запуск без
        # node заканчивался бы «найдена проблема» на исправном интерфейсе.
        print("\nсинтаксис JS: не проверен (node недоступен)")
    else:
        print(f"\nсинтаксис JS: {syntax or 'в порядке'}")
        if syntax:
            problems += 1

    print(f"\nитого проблем: {problems}")
    return 1 if problems else 0


def python_names_in_js(script: str) -> dict[str, list[int]]:
    """Имена в стиле Python, дошедшие до браузерного скрипта.

    `KEY_RING.snapshot()` в JS — это ровно то, чем заканчивается любая попытка
    дотянуться до серверного объекта из интерфейса: в Python такое имя есть, в
    браузере его нет, и строка падает с ReferenceError при первом же вызове.
    `node --check` такое пропускает: синтаксис корректный, имя просто не
    существует.

    Признак — ЗАГЛАВНЫЕ_С_ПОДЧЁРКИВАНИЯМИ: в JS такая запись не используется, а
    в Python означает константу. Объявленные в самом скрипте имена и строки-
    комментарии из проверки выпадают — иначе пришлось бы вычищать из кода
    объяснение, откуда взялось имя.
    """
    declared = set(re.findall(
        r"(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)", script))
    lines = [line.split("//")[0] for line in script.splitlines()]
    found: dict[str, list[int]] = {}
    for number, line in enumerate(lines, start=1):
        for name in re.findall(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", line):
            if name in declared:
                continue
            found.setdefault(name, []).append(number)
    return found


#: Куда складываем скрипт для node. Временный файл удаляется сразу.
TMP_JS = Path(tempfile.gettempdir()) / "zagent_check_ui.js"


def check_js_syntax(script: str) -> str | None:
    """Проверить, что скрипт вообще разбирается.

    Разбор отдаётся node: свой парсер шаблонных строк неизбежно путается с
    интерполяциями вида `` `вложенный ${`шаблон`}` `` и в какой-то момент
    объявляет рабочий интерфейс сломанным. Ложная тревога в проверке хуже её
    отсутствия: начинаешь чинить то, что не сломано.

    Если node недоступен, остаётся запасная проверка — парность скобок вне
    строк. Она грубее, но ничего не сообщает напрасно.

    `None` — проверка не выполнена вовсе. Раньше в этом случае возвращалась
    непустая строка, а вызывающий считал любую непустую строку проблемой:
    на машине без node проверка интерфейса находила хотя бы одну проблему
    всегда, независимо от состояния интерфейса. Проверка, которая всегда
    находит проблему, не находит ничего.
    """
    if node_available():
        return check_js_node(script)
    return check_js_braces(script) or None


def node_available() -> bool:
    """Есть ли node в системе."""
    try:
        done = subprocess.run(
            ["node", "--version"], capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def check_js_node(script: str) -> str:
    """Разобрать скрипт настоящим движком JS."""
    TMP_JS.write_text(script, encoding="utf-8")
    try:
        done = subprocess.run(
            ["node", "--check", str(TMP_JS)],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"node не отвечает: {exc}"
    finally:
        TMP_JS.unlink(missing_ok=True)

    if done.returncode == 0:
        return ""

    # Номер строки node считает по файлу, а не по скрипту внутри HTML, —
    # ровно то, что нужно, чтобы показать строку в ui.py.
    out = (done.stderr or "").strip()
    first = next((line for line in out.splitlines() if "Error" in line), out)
    return first.strip() or "node не смог разобрать скрипт"


def check_js_braces(script: str) -> str:
    """Запасная проверка без node: парность фигурных скобок вне строк.

    Ловит самое частое — лишнюю или недостающую скобку от неудачной правки.
    Про незакрытую строку молчит намеренно: не различать закрытую и
    незакрытую она не умеет, а врать не должна.
    """
    depth = 0
    in_block_comment = False
    index = 0
    length = len(script)
    while index < length:
        char = script[index]
        pair = script[index:index + 2]

        if in_block_comment:
            if pair == "*/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if pair == "/*":
            in_block_comment = True
            index += 2
            continue
        if pair == "//":
            newline = script.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if char in ("'", '"', "`"):
            index = skip_string(script, index, char) or length
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return "лишняя }"
        index += 1

    if in_block_comment:
        return "не закрыт /* комментарий"
    if depth != 0:
        return f"скобки не сошлись: не хватает {depth} }}"
    # Сошлось — значит, проблем нет, и возвращается пусто. Раньше здесь стояло
    # «(проверка скобок без node: строки не разбирались)», и это была самая
    # дорогая строка в файле: вызывающий считал любую непустую строку
    # проблемой, поэтому на машине без node проверка интерфейса находила
    # хотя бы одну проблему **всегда** — независимо от того, сломан
    # интерфейс или нет. Проверка, которая всегда находит проблему, не
    # находит ничего: её вывод перестают читать.
    return ""


def skip_string(script: str, start: int, quote: str) -> int:
    """Пропустить строковый литерал начиная с открывающей кавычки.

    Возвращает позицию сразу за закрывающей кавычкой, либо 0, если литерал
    не закрыт. Различать эти два случая обязательно: незакрытый литерал
    делает бессмысленной проверку скобок дальше по файлу.
    """
    index = start + 1
    length = len(script)
    while index < length:
        char = script[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        # В шаблонной строке ${...} живёт код: там и кавычки, и обратные
        # кавычки свои. Пропускаем блок целиком по балансу скобок.
        if quote == "`" and script[index:index + 2] == "${":
            depth = 1
            index += 2
            while index < length and depth:
                if script[index] == "{":
                    depth += 1
                elif script[index] == "}":
                    depth -= 1
                index += 1
            continue
        index += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
