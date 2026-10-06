"""Декларативные проверки результата.

Каждая проверка из ``acceptance`` задания — словарь с ``kind`` и параметрами.
Здесь живёт реестр видов проверок: добавить новый вид — значит написать одну
функцию и зарегистрировать её. Никакой правки вызывающего кода.

Все проверки получают корень песочницы и **обязаны** вернуть ``CheckResult``,
а не бросить исключение: проверка не прошла — это результат, а не поломка
стенда.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: Сколько символов файла читать. Меньше — проверки «есть alt у картинок» и
#: «есть @media» на больших файлах врали бы в минус.
MAX_READ = 2_000_000

#: Сколько совпадений показывать в сообщении: больше — уже шум.
MAX_SAMPLES = 5


@dataclass
class CheckResult:
    """Итог одной проверки."""

    id: str
    kind: str
    passed: bool
    weight: int
    message: str = ""
    evidence: Any = None
    elapsed_ms: int = 0

    @property
    def earned(self) -> int:
        return self.weight if self.passed else 0


# --------------------------------------------------------------- вспомогательное


def _text(path: Path) -> str:
    """Прочитать файл как текст, не падая на бинарниках и кривых кодировках."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"не читается: {exc}") from exc
    if b"\x00" in data[:8000]:
        return data.decode("utf-8", errors="ignore")
    return data.decode("utf-8", errors="replace")


def _translate(pattern: str) -> "re.Pattern[str]":
    """Собрать регулярку из нашего синтаксиса шаблонов.

    ``fnmatch`` здесь не годится: в нём ``*`` совпадает и со слэшем, поэтому
    ``**/*.css`` не находит ``style.css`` в корне песочницы — а это самый
    естественный шаблон, который напишет автор задания.

    Поддерживаем:
      ``**/``    ноль или больше папок (в том числе ни одной)
      ``**``     любая строка, включая слэши
      ``*``      любые символы кроме слэша
      ``?``      один символ кроме слэша
      ``[...]``  класс символов
    """
    out: list[str] = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            if pattern[index:index + 3] == "**/":
                out.append("(?:[^/]+/)*")
                index += 3
                continue
            if pattern[index:index + 2] == "**":
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
            index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        elif char == "[":
            end = index + 1
            if end < length and pattern[end] in "!^":
                end += 1
            if end < length and pattern[end] == "]":
                end += 1
            while end < length and pattern[end] != "]":
                end += 1
            if end >= length:
                out.append(re.escape("["))
                index += 1
                continue
            body = pattern[index + 1:end]
            if body.startswith(("!", "^")):
                body = "^" + body[1:]
            out.append("[" + body + "]")
            index = end + 1
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile("(?s:" + "".join(out) + r")\Z")


def _glob(root: Path, pattern: str) -> list[Path]:
    """Файлы под шаблоном, без директорий и без скрытых папок.

    Скрытое отбрасывается: песочница может содержать ``.venv`` агента, и он не
    имеет отношения к результату задания.
    """
    regexes = [_translate(one) for one in _expand_braces(pattern)]
    hits: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue
        if any(rx.match(rel) for rx in regexes):
            hits.append(path)
    return sorted(hits)


def _expand_braces(pattern: str) -> list[str]:
    """Раскрыть ``{a,b}`` в список шаблонов.

    В YAML это самая естественная запись для «один из файлов», а ``fnmatch``
    скобки не понимает и молча не находит ничего. Поддерживается любой уровень
    вложенности — раскрытие рекурсивное.
    """
    start = pattern.find("{")
    if start < 0:
        return [pattern]
    depth = 0
    end = -1
    for index in range(start, len(pattern)):
        char = pattern[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end < 0:
        # Незакрытая скобка — не молчим, а трактуем как обычный символ.
        return [pattern]

    head, body, tail = pattern[:start], pattern[start + 1:end], pattern[end + 1:]
    variants: list[str] = []
    # Делим по запятой на своём уровне: при вложенных скобках «{a,{b,c}}»
    # обычный split даёт «{a» и «c}» — сломанные шаблоны, которые молча
    # ничего не находят.
    depth = 0
    piece = []
    for char in body:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if char == "," and depth == 0:
            variants.extend(_expand_braces(head + "".join(piece).strip() + tail))
            piece = []
        else:
            piece.append(char)
    variants.extend(_expand_braces(head + "".join(piece).strip() + tail))
    return variants


def _loc(text: str) -> int:
    """Число непустых строк: чистый LOC ближе к размеру работы, чем wc -l."""
    return sum(1 for line in text.splitlines() if line.strip())


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value or []]


def _need(paths: list[Path], what: str) -> str:
    if not paths:
        raise ValueError(f"не найдено файлов под шаблоном ({what})")
    return ""


# --------------------------------------------------------------------- проверки
# Каждая функция: (root, args) -> (passed, message, evidence)
# Исключение внутри функции превращается в провал с текстом исключения.


def check_no_files(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    """Проверка на отсутствие мусора: Python-файлы в статичном лендинге.

    Отдельный вид, а не проверка с весом 0: отсутствие файлов здесь — успех,
    и сообщение об этом обязано так и звучать, иначе читатель отчёта видит
    «проверка упала» там, где всё в порядке.
    """
    hits = _glob(root, str(args["glob"]))
    if hits:
        names = [h.relative_to(root).as_posix() for h in hits[:MAX_SAMPLES]]
        return False, f"лишние файлы: {names}", names
    return True, f"файлов под {args['glob']!r} нет, как и требуется", None


def check_file_exists(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    pattern = str(args["path"])
    hits = _glob(root, pattern)
    if hits:
        return True, f"{len(hits)} шт.", [h.relative_to(root).as_posix() for h in hits[:MAX_SAMPLES]]
    return False, f"нет файла {pattern}", None


def check_min_files(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    hits = _glob(root, str(args["glob"]))
    need = int(args.get("count", args.get("min", 1)))
    ok = len(hits) >= need
    return ok, f"{len(hits)} шт., требовалось {need}", len(hits)


def check_max_files(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    hits = _glob(root, str(args["glob"]))
    limit = int(args.get("count", args.get("max", 1)))
    ok = len(hits) <= limit
    return ok, f"{len(hits)} шт., допустимо не больше {limit}", len(hits)


def _one_file(root: Path, args: dict[str, Any]) -> tuple[Path | None, str]:
    """Файл для проверок, которым он ровно один."""
    name = str(args["file"])
    direct = root / name
    if direct.is_file():
        return direct, ""
    hits = _glob(root, name)
    if not hits:
        return None, f"файл {name} не найден"
    if len(hits) > 1:
        return None, f"под шаблоном {name} {len(hits)} файлов, нужен ровно один"
    return hits[0], ""


def check_min_lines(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    path, problem = _one_file(root, args)
    if path is None:
        return False, problem, None
    count = _loc(_text(path))
    need = int(args["lines"])
    ok = count >= need
    return ok, f"{count} непустых строк, требовалось {need}", count


def check_max_lines(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    path, problem = _one_file(root, args)
    if path is None:
        return False, problem, None
    count = _loc(_text(path))
    limit = int(args["lines"])
    ok = count <= limit
    return ok, f"{count} непустых строк, допустимо не больше {limit}", count


def check_contains(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    path, problem = _one_file(root, args)
    if path is None:
        return False, problem, None
    body = _text(path)
    any_of = _as_list(args.get("any_of"))
    all_of = _as_list(args.get("all_of"))
    if not any_of and not all_of:
        any_of = _as_list(args.get("pattern"))
    if not any_of and not all_of:
        return False, "не задано ни any_of, ни all_of, ни pattern", None

    found_any = [p for p in any_of if p in body]
    found_all = [p for p in all_of if p in body]
    missing_all = [p for p in all_of if p not in body]

    if any_of:
        if not found_any:
            return False, f"нет ни одного из {any_of}", None
        return True, f"найдено {found_any}", found_any
    if missing_all:
        return False, f"не найдено {missing_all}", found_all
    return True, f"найдено всё из {all_of}", found_all


def check_not_contains(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    """Запрещённые подстроки отсутствуют.

    ``file`` принимает шаблон, а не только точное имя: иначе нельзя проверить
    «ни в одном .py», не перечисляя файлы по именам.
    """
    if "file" in args:
        paths = _glob(root, str(args["file"]))
    else:
        paths = _glob(root, str(args.get("glob", "**/*")))
    if not paths:
        return False, "проверять нечего: подходящих файлов нет", None
    forbidden = _as_list(args.get("patterns") or args.get("pattern") or args.get("any_of"))
    if not forbidden:
        return False, "не задано ни patterns, ни pattern", None
    bad: list[str] = []
    for path in paths:
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico"}:
            continue
        try:
            body = _text(path)
        except ValueError:
            continue
        low = body.lower()
        for pattern in forbidden:
            if pattern.lower() in low:
                bad.append(f"{path.relative_to(root).as_posix()}: {pattern}")
    if bad:
        return False, f"найдено запрещённое: {bad[:MAX_SAMPLES]}", bad
    return True, f"запрещённого нет (проверено {len(paths)} файлов)", None


def check_total_loc(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    hits = _glob(root, str(args["glob"]))
    _need(hits, str(args["glob"]))
    total = 0
    for path in hits:
        try:
            total += _loc(_text(path))
        except ValueError:
            continue
    need = int(args["lines"])
    ok = total >= need
    return ok, f"{total} непустых строк в {len(hits)} файлах, требовалось {need}", total


def check_max_loc_per_file(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    hits = _glob(root, str(args["glob"]))
    _need(hits, str(args["glob"]))
    limit = int(args["lines"])
    fat = []
    for path in hits:
        try:
            count = _loc(_text(path))
        except ValueError:
            continue
        if count > limit:
            fat.append(f"{path.relative_to(root).as_posix()}: {count}")
    if fat:
        return False, f"файлы крупнее {limit} строк: {fat[:MAX_SAMPLES]}", fat
    return True, f"все файлы не крупнее {limit} строк", None


def check_html_images_have_alt(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    hits = [p for p in _glob(root, str(args["glob"])) if p.suffix.lower() in {".html", ".htm"}]
    _need(hits, str(args["glob"]))
    missing: list[str] = []
    total = 0
    for path in hits:
        body = _text(path)
        for tag in re.findall(r"<img\b[^>]*>", body, re.IGNORECASE):
            total += 1
            if not re.search(r"\balt\s*=", tag, re.IGNORECASE):
                missing.append(f"{path.relative_to(root).as_posix()}: {tag[:60]}")
    if missing:
        return False, f"картинок без alt: {len(missing)} из {total} — {missing[:MAX_SAMPLES]}", total
    if total == 0:
        return True, "картинок нет — проверка не применима, засчитано как выполненная", 0
    return True, f"alt есть у всех {total} картинок", total


def check_html_has_media_query(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    """Есть ли медиазапросы и покрывают ли они узкие экраны.

    Набор брейкпоинтов по умолчанию — не «три модных числа», а минимум для
    адаптива от 360px. Раньше требовались 480, 768 и 360 одновременно, и
    эталон с брейкпоинтами 768 и 480 честно считался неадаптивным, хотя
    вёрстка рассыпалась бы уже на 400px.
    """
    hits = _glob(root, str(args["glob"]))
    if not hits:
        # Нет файлов — это провал с объяснением, а не исключение: стенд не
        # должен падать из-за задания, неверно написанного автором.
        return False, f"не найдено файлов под {args['glob']!r}: проверять нечего", None
    need = [str(v) for v in (args.get("breakpoints") or ["768", "480"])]
    bodies = {}
    for path in hits:
        try:
            bodies[path.relative_to(root).as_posix()] = _text(path)
        except ValueError:
            continue
    if not bodies:
        return False, "прочитать нечего: файлы не читаются как текст", None
    missing: list[str] = []
    for width in need:
        # Медиазапрос бывает двух видов: «@media (max-width: 768px)» и
        # «@media screen and (min-width:768px)». Класс символов после
        # max-width: позволяет пропускать пробел и «-» в «tablet-768px».
        pattern = re.compile(
            r"@media[^{]*?\b(?:max|min)-width\s*:?\s*[\w.-]*"
            + re.escape(width) + r"px",
            re.IGNORECASE,
        )
        if not any(pattern.search(body) for body in bodies.values()):
            missing.append(f"{width}px")
    if missing:
        return False, f"нет @media под {missing}", None
    return True, f"есть @media под {need}", None


def check_py_compiles(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    hits = [p for p in _glob(root, str(args.get("glob", "**/*.py")))]
    _need(hits, str(args.get("glob", "**/*.py")))
    broken = []
    for path in hits:
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()
            broken.append(f"{path.relative_to(root).as_posix()}: {tail[-1] if tail else '?'}")
    if broken:
        return False, f"не компилируется: {broken[:MAX_SAMPLES]}", broken
    return True, f"компилируются все {len(hits)} файлов", len(hits)


def _run(root: Path, args: dict[str, Any], *, what: str) -> tuple[bool, str, Any]:
    timeout = int(args.get("timeout", 300))
    command = args.get("command") or args.get("cmd")
    if isinstance(command, str):
        command = command.split()
    if not command:
        return False, "не задана команда", None
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        # pytest не должен падать из-за отсутствия сети.
        "NO_PROXY": "*",
    }
    try:
        proc = subprocess.run(
            [str(part) for part in command],
            cwd=root, capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"{what}: не уложился в {timeout} с", None
    except FileNotFoundError as exc:
        return False, f"{what}: команда не найдена — {exc}", None
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
        return False, f"{what}: код возврата {proc.returncode} — {tail}", proc.returncode
    return True, f"{what}: успешно", 0


def check_tests_pass(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    # pytest из воркспейса воркера не гарантирован, поэтому ищем рядом.
    pytest = root / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "pytest"
    command = [str(pytest) if pytest.exists() else sys.executable, "-m", "pytest", "-q"]
    if pytest.exists():
        command.append(str(root))
    else:
        command.append(".")
    return _run(root, {**args, "command": command}, what="тесты")


def check_command_succeeds(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    return _run(root, args, what=str(args.get("label", "команда")))


#: Файлы с тестами: пароль в тесте — это известный пароль, а не уязвимость.
#: Без исключения проверка ругается на каждый `test_auth.py`, где создаются
#: учётные записи для проверки.
TEST_GLOBS = ("**/test_*.py", "**/*_test.py", "**/tests/**", "**/testing/**")


def _code_files(root: Path, pattern: str, args: dict[str, Any]) -> list[Path]:
    """Файлы по шаблону, с выключенными тестами (если не сказано иначе)."""
    hits = _glob(root, pattern)
    if args.get("include_tests"):
        return hits
    test_patterns = [
        _translate(variant)
        for pattern in TEST_GLOBS
        for variant in _expand_braces(pattern)
    ]
    out = []
    for path in hits:
        rel = path.relative_to(root).as_posix()
        if any(rx.match(rel) for rx in test_patterns):
            continue
        out.append(path)
    return out


def check_sql_no_plaintext_password(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    """Пароль не должен лежать рядом с хешем в открытом виде.

    Грубая, но рабочая проверка: ищем строки, где рядом с «password» идёт
    присваивание литерала, и отдельно — пароль без хеша вообще.
    """
    hits = _code_files(root, str(args.get("glob", "**/*.py")), args)
    _need(hits, str(args.get("glob", "**/*.py")))
    hashed = re.compile(r"bcrypt|argon2|pbkdf2|scrypt|hashlib|sha256|sha512|generate_password_hash")
    plain = re.compile(
        r"(password|passwd|pwd)\s*=\s*[\"'](?![^\"']*(?:hash|bcrypt|salt))[\"'][^\"']{3,}[\"']",
        re.IGNORECASE,
    )
    problems: list[str] = []
    for path in hits:
        body = _text(path)
        if not re.search(r"password|парол", body, re.IGNORECASE):
            continue
        if hashed.search(body):
            continue  # хеширование есть — ищем только совсем голый пароль
        for match in plain.finditer(body):
            line = body[: match.start()].count("\n") + 1
            problems.append(f"{path.relative_to(root).as_posix()}:{line}")
    if problems:
        return False, f"пароль в открытом виде: {problems[:MAX_SAMPLES]}", problems
    return True, "пароль хешируется", None


def check_passwords_hashed(root: Path, args: dict[str, Any]) -> tuple[bool, str, Any]:
    """Хеширование должно происходить рядом с записью, а не где-то в файле.

    Проверяются сразу две слабые версии одной идеи:

    * «есть ли в файле вызов хеширования» — ложное срабатывание: функция
      ``hash_password`` может быть объявлена, а в запрос уходить сырой пароль;
    * «есть ли в файле слово INSERT» — тоже ложное срабатывание: вставка
      сессии и ``PRAGMA foreign_keys`` не имеют отношения к паролю. Именно так
      выглядела первая версия этой проверки, и она ругалась на свой же эталон.

    Поэтому местом записи считается только запрос, который **сам** упоминает
    пользователя и пароль, и уже рядом с ним ищется вызов хеширования.
    """
    hits = _code_files(root, str(args.get("glob", "**/*.py")), args)
    _need(hits, str(args.get("glob", "**/*.py")))

    hashing = re.compile(
        r"hashlib\.\w+|bcrypt\.|argon2\.|scrypt\.|pbkdf2_hmac|"
        r"hash_password|password_hash|make_password_hash|generate_password_hash",
        re.IGNORECASE,
    )
    verb = re.compile(r"\b(?:INSERT|UPDATE|execute|executemany|replace_into)\b", re.IGNORECASE)
    helper = re.compile(r"\b(?:add_user|create_user|save_user|register|signup|sign_up)\s*\(")
    about_user = re.compile(r"\buser", re.IGNORECASE)
    about_password = re.compile(r"pw_hash|password|passwd|pwd|парол", re.IGNORECASE)

    #: Сколько строк окна считать «рядом» с местом записи.
    window = int(args.get("window", 8))
    #: Сколько строк вперёд смотреть, чтобы прочитать текст запроса.
    ahead = int(args.get("ahead", 3))

    checked = 0
    problems: list[str] = []
    for path in hits:
        lines = _text(path).splitlines()
        for number, line in enumerate(lines):
            statement = "\n".join(lines[number:number + ahead + 1])
            if not (verb.search(line) or helper.search(line)):
                continue
            # Запись пользователя, а не сессии и не PRAGMA.
            if not (about_user.search(statement) and about_password.search(statement)):
                continue
            checked += 1
            low = max(0, number - window)
            high = min(len(lines), number + window + 1)
            if not hashing.search("\n".join(lines[low:high])):
                problems.append(f"{path.relative_to(root).as_posix()}:{number + 1}")
    if checked == 0:
        return False, "не найдено ни одной записи пароля в базу", None
    if problems:
        return False, (
            f"запись пароля без хеширования рядом: {problems[:MAX_SAMPLES]}"
        ), problems
    return True, f"хеширование есть у всех {checked} записей пароля", checked


#: Реестр видов проверок. Ключ — значение ``kind`` в YAML.
REGISTRY: dict[str, Callable[[Path, dict[str, Any]], tuple[bool, str, Any]]] = {
    "file_exists": check_file_exists,
    "no_files": check_no_files,
    "min_files": check_min_files,
    "max_files": check_max_files,
    "min_lines": check_min_lines,
    "max_lines": check_max_lines,
    "contains": check_contains,
    "not_contains": check_not_contains,
    "total_loc": check_total_loc,
    "max_loc_per_file": check_max_loc_per_file,
    "html_images_have_alt": check_html_images_have_alt,
    "html_has_media_query": check_html_has_media_query,
    "py_compiles": check_py_compiles,
    "tests_pass": check_tests_pass,
    "command_succeeds": check_command_succeeds,
    "sql_no_plaintext_password": check_sql_no_plaintext_password,
    "passwords_hashed": check_passwords_hashed,
}


def known_kinds() -> list[str]:
    return sorted(REGISTRY)


def run_check(root: Path, check: Any) -> CheckResult:
    """Выполнить одну проверку. Любая ошибка — это провал, а не исключение."""
    handler = REGISTRY.get(check.kind)
    if handler is None:
        return CheckResult(
            id=check.id, kind=check.kind, passed=False, weight=check.weight,
            message=f"неизвестный вид проверки {check.kind!r}; есть: {known_kinds()}",
        )
    try:
        passed, message, evidence = handler(root, check.args)
    except Exception as exc:  # noqa: BLE001 — проверка не должна ронять стенд
        return CheckResult(
            id=check.id, kind=check.kind, passed=False, weight=check.weight,
            message=f"проверка упала: {type(exc).__name__}: {exc}",
        )
    return CheckResult(
        id=check.id, kind=check.kind, passed=passed, weight=check.weight,
        message=message, evidence=evidence,
    )


def run_all(root: Path, checks: list[Any]) -> list[CheckResult]:
    return [run_check(root, check) for check in checks]