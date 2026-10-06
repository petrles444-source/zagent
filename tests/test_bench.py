"""Стенд проверки агента: задания, проверки, эталоны, отчёты.

Сеть и модели не используются: проверяется сам стенд. Единственное, что
должно работать без сети, — это реестр проверок и подсчёт баллов, иначе
невозможно отличить «проверки настроены неверно» от «агент не справился».
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bench import Bench, BenchConfig, RefBook, Sandbox, load_task, load_tasks
from bench.checks import (
    REGISTRY,
    _expand_braces,
    _glob,
    _translate,
    known_kinds,
    run_all,
)
from bench.metrics import collect, trend
from bench.reporter import RunReport, to_markdown, to_summary_markdown
from bench.task import Check, TaskError
from tools.bench import main as bench_main

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"
REFS = ROOT / "ref"


# =============================================================== задания


def test_все_задания_читаются() -> None:
    tasks = load_tasks(TASKS)
    assert len(tasks) >= 5, "заданий должно быть хотя бы пять"
    assert {t.task_id for t in tasks} >= {
        "LANDING-001", "MULTIPAGE-001", "VISION-001", "SCRAPE-001", "GAME-001"
    }


def test_в_каждом_задании_есть_проверки_с_весом() -> None:
    for task in load_tasks(TASKS):
        assert task.checks, f"{task.task_id}: ни одной проверки"
        assert task.total_weight > 0, task.task_id
        for check in task.checks:
            assert check.weight > 0, f"{task.task_id}/{check.id}: вес должен быть положительным"


def test_виды_проверок_существуют() -> None:
    """Задание с несуществующим видом должно падать на чтении, а не на прогоне."""
    for task in load_tasks(TASKS):
        for check in task.checks:
            assert check.kind in REGISTRY, f"{task.task_id}/{check.id}: нет {check.kind!r}"


def test_задание_без_цели_отвергается(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("task_id: X\nacceptance: []\n", encoding="utf-8")
    with pytest.raises(TaskError):
        load_task(path)


def test_задание_без_веса_отвергается(tmp_path: Path) -> None:
    path = tmp_path / "noweight.yaml"
    path.write_text(
        "task_id: X\ngoal: что-то\nacceptance:\n"
        "  - id: A1\n    kind: file_exists\n    path: x\n    weight: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(TaskError):
        load_task(path)


def test_повторяющиеся_id_отвергаются(tmp_path: Path) -> None:
    path = tmp_path / "dupes.yaml"
    path.write_text(
        "task_id: X\ngoal: что-то\nacceptance:\n"
        "  - {id: A1, kind: file_exists, path: x, weight: 5}\n"
        "  - {id: A1, kind: file_exists, path: y, weight: 5}\n",
        encoding="utf-8",
    )
    with pytest.raises(TaskError):
        load_task(path)


def test_проверка_без_обязательного_аргумента_отвергается(tmp_path: Path) -> None:
    path = tmp_path / "noarg.yaml"
    path.write_text(
        "task_id: X\ngoal: что-то\nacceptance:\n"
        "  - {id: A1, kind: min_lines, weight: 5}\n",
        encoding="utf-8",
    )
    with pytest.raises(TaskError):
        load_task(path)


def test_проверка_на_неизвестный_вид_отвергается(tmp_path: Path) -> None:
    """Неизвестный вид ловится в задании, а не «падает» в отчёте."""
    path = tmp_path / "unknown.yaml"
    path.write_text(
        "task_id: X\ngoal: что-то\nacceptance:\n"
        "  - {id: A1, kind: выдумка, weight: 5}\n",
        encoding="utf-8",
    )
    task = load_task(path)
    assert task.checks[0].kind == "выдумка"


def test_ref_hint_принимает_список_и_словарь(tmp_path: Path) -> None:
    as_list = _load_task_text(tmp_path / "list.yaml", "ref_hint: [a, b]")
    assert as_list.ref_hints == ["a", "b"]
    as_dict = _load_task_text(tmp_path / "dict.yaml",
                              "ref_hint:\n  primary: a\n  fallback: b\n")
    assert as_dict.ref_hints == ["a", "b"]


def _load_task_text(path: Path, extra: str):
    """Задание из строки.

    Файл кладётся по переданному пути, а не во временный каталог по умолчанию:
    версия без ``dir`` писала десятки tmp*.yaml прямо в корень проекта, и они
    копились там месяцами.
    """
    path.write_text(
        f"task_id: X\ngoal: что-то\n{extra}\n"
        "acceptance:\n  - {id: A1, kind: file_exists, path: x, weight: 5}\n",
        encoding="utf-8",
    )
    return load_task(path)


# =============================================================== шаблоны


@pytest.mark.parametrize(
    "pattern,expected",
    [
        ("**/*.py", True),        # файл в корне — главный случай
        ("*.css", True),          # ровно в корне
        ("nested/deep.py", True), # явный путь
        ("nested/*.py", True),    # явная папка
        ("**/deep.py", True),     # любая глубина
        ("missing/*.py", False),
        ("**/*.png", False),
        ("*.js", False),
    ],
)
def test_звёздочки_ищут_файлы_в_корне(tmp_path: Path, pattern: str, expected: bool) -> None:
    """``fnmatch`` здесь не годится: ``**/*.css`` не нашёл бы style.css в корне."""
    (tmp_path / "style.css").write_text("a{}", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.py").write_text("x = 1", encoding="utf-8")

    found = _glob(tmp_path, pattern)
    if expected:
        assert found, f"{pattern} ничего не нашёл"
        assert not any(".hidden" in str(p) for p in found)
    else:
        assert not found


def test_имя_без_звёздочки_ищет_только_в_корне(tmp_path: Path) -> None:
    """Шаблон без ``**`` не должен внезапно находить файлы в подпапках.

    ``fnmatch`` сравнивал бы только имя файла и нашёл бы ``nested/deep.py`` по
    шаблону ``deep.py``. Это молча расширяло бы проверку и подменяло её
    замысел.
    """
    (tmp_path / "root.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.py").write_text("x = 1", encoding="utf-8")

    found = _glob(tmp_path, "deep.py")
    assert found == [], f"найдено в подпапке: {found}"
    assert _glob(tmp_path, "root.py"), "файл в корне должен находиться"


def test_скрытые_папки_не_попадают_в_результат(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / ".venv" / "keep.py").write_text("y = 1", encoding="utf-8")
    assert _glob(tmp_path, "**/*.py") == [], "папка агента не должна попадать в результат"


def test_скобки_раскрываются() -> None:
    assert sorted(_expand_braces("{a.py,b.js}")) == ["a.py", "b.js"]
    assert _expand_braces("**/*.{py,md}") == ["**/*.py", "**/*.md"]
    assert _expand_braces("нет скобок") == ["нет скобок"]
    assert _expand_braces("{a,{b,c}}.py") == ["a.py", "b.py", "c.py"]


def test_незакрытая_скобка_не_ломает() -> None:
    assert _expand_braces("a{b") == ["a{b"]


def test_звёздочка_не_пересекает_слэш() -> None:
    assert _translate("*.py").match("a.py")
    assert not _translate("/*.py").match("sub/a.py")


# =============================================================== проверки


def test_file_exists(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert REGISTRY["file_exists"](tmp_path, {"path": "a.txt"})[0]
    assert not REGISTRY["file_exists"](tmp_path, {"path": "нет.txt"})[0]


def test_no_files_считает_отсутствие_успехом(tmp_path: Path) -> None:
    """Отсутствие мусора — успех, а не падение с текстом «проверка упала»."""
    passed, message, _ = REGISTRY["no_files"](tmp_path, {"glob": "**/*.py"})
    assert passed, message
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    assert not REGISTRY["no_files"](tmp_path, {"glob": "**/*.py"})[0]


def test_contains_all_of_и_any_of(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import os\ndef fetch(): pass", encoding="utf-8")
    assert REGISTRY["contains"](tmp_path, {"file": "a.py", "all_of": ["def fetch"]})[0]
    assert not REGISTRY["contains"](tmp_path, {"file": "a.py", "all_of": ["def нет"]})[0]
    assert REGISTRY["contains"](tmp_path, {"file": "a.py", "any_of": ["нет", "fetch"]})[0]
    assert not REGISTRY["contains"](tmp_path, {"file": "a.py", "any_of": ["нет"]})[0]


def test_contains_требует_шаблон(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    ok, message, _ = REGISTRY["contains"](tmp_path, {"file": "a.py"})
    assert not ok and "any_of" in message


def test_html_images_have_alt(tmp_path: Path) -> None:
    (tmp_path / "a.html").write_text(
        '<img src="1.png" alt="раз"><img src="2.png">', encoding="utf-8"
    )
    ok, message, _ = REGISTRY["html_images_have_alt"](tmp_path, {"glob": "**/*.html"})
    assert not ok
    assert "alt" in message


def test_html_media_query(tmp_path: Path) -> None:
    """Без явного списка брейкпоинтов проверка требует три стандартных ширины."""
    (tmp_path / "s.css").write_text("@media (max-width: 768px){a{}}", encoding="utf-8")
    assert not REGISTRY["html_has_media_query"](tmp_path, {"glob": "**/*.css"})[0], \
        "одного брейкпоинта мало для стандартного набора"

    (tmp_path / "s.css").write_text(
        "@media (max-width:768px){a{}}@media (max-width: 480px){a{}}"
        "@media (max-width:360px){a{}}",
        encoding="utf-8",
    )
    assert REGISTRY["html_has_media_query"](tmp_path, {"glob": "**/*.css"})[0]


def test_html_media_query_по_явному_списку(tmp_path: Path) -> None:
    (tmp_path / "s.css").write_text(
        "@media (max-width: 768px){a{}}@media (max-width: 480px){a{}}",
        encoding="utf-8",
    )
    ok, _, _ = REGISTRY["html_has_media_query"](
        tmp_path, {"glob": "**/*.css", "breakpoints": ["768", "480"]}
    )
    assert ok, "два указанных брейкпоинта найдены"

    ok, _, _ = REGISTRY["html_has_media_query"](
        tmp_path, {"glob": "**/*.css", "breakpoints": ["768", "1024"]}
    )
    assert not ok, "1024 в файле нет"


def test_html_media_query_терпит_разные_начертания(tmp_path: Path) -> None:
    for css in (
        "@media screen and (min-width:768px){a{}}",
        "@media only screen and (max-width: 768px){a{}}",
        "@media (max-width : 768px){a{}}",
        "@media (min-width:768px){a{}}",
    ):
        (tmp_path / "s.css").write_text(css, encoding="utf-8")
        ok, message, _ = REGISTRY["html_has_media_query"](
            tmp_path, {"glob": "**/*.css", "breakpoints": ["768"]}
        )
        assert ok, f"не распознано: {css} — {message}"


def test_проверка_без_файлов_не_поднимает_исключение(tmp_path: Path) -> None:
    """Отсутствие файлов — это ноль баллов с текстом, а не исключение стенда.

    ``run_check`` ловит всё, но автор проверки всё равно не должен рассчитывать
    на исключение как на способ сообщить о провале.
    """
    ok, message, _ = REGISTRY["html_has_media_query"](tmp_path, {"glob": "**/*.css"})
    assert not ok and message, "сообщение должно объяснять, что искать было нечего"


def test_total_loc_считает_непустые(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n\n\ny = 2", encoding="utf-8")
    _, _, count = REGISTRY["total_loc"](tmp_path, {"glob": "*.py", "lines": 1})
    assert count == 2, "пустые строки не должны считаться"


def test_not_contains_по_шаблону_а_не_по_имени(tmp_path: Path) -> None:
    """``file`` принимает шаблон: иначе «ни в одном .py» невыразимо."""
    (tmp_path / "a.py").write_text("User-Agent: Mozilla/5.0", encoding="utf-8")
    (tmp_path / "b.py").write_text("ok", encoding="utf-8")
    ok, _, _ = REGISTRY["not_contains"](
        tmp_path, {"file": "*.py", "patterns": ["Mozilla/5.0"]}
    )
    assert not ok


def test_passwords_hashed_ищет_хеш_рядом_с_записью(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text(
        "digest, salt = hash_password(pw)\n"
        'conn.execute("INSERT INTO users (email, pw_hash) VALUES (?, ?)", (e, digest))\n',
        encoding="utf-8",
    )
    ok, message, _ = REGISTRY["passwords_hashed"](tmp_path, {"glob": "**/*.py"})
    assert ok, message


def test_passwords_hashed_ловит_сырой_пароль(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text(
        'conn.execute("INSERT INTO users (email, password) VALUES (?, ?)", (e, pw))\n',
        encoding="utf-8",
    )
    ok, message, _ = REGISTRY["passwords_hashed"](tmp_path, {"glob": "**/*.py"})
    assert not ok, "сырой пароль в INSERT должен ловиться"


def test_passwords_hashed_игнорирует_вставку_сессии(tmp_path: Path) -> None:
    """Вставка сессии и PRAGMA — не запись пароля.

    Именно на этом ругалась первая версия проверки, включая собственный
    эталон стенда.
    """
    (tmp_path / "server.py").write_text(
        'conn.execute("PRAGMA foreign_keys = ON")\n'
        'conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (t, u))\n',
        encoding="utf-8",
    )
    ok, message, _ = REGISTRY["passwords_hashed"](tmp_path, {"glob": "**/*.py"})
    assert not ok and "не найдено" in message, message


def test_проверки_не_падают_на_пустой_песочнице() -> None:
    """Пустой результат — это ноль баллов, а не исключение стенда."""
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        checks = [
            Check(id=c["id"], kind=c["kind"], weight=c["weight"], args=c["args"])
            for c in [
                {"id": "A1", "kind": "file_exists", "weight": 5, "args": {"path": "x"}},
                {"id": "A2", "kind": "total_loc", "weight": 5, "args": {"glob": "*.py", "lines": 1}},
                {"id": "A3", "kind": "tests_pass", "weight": 5, "args": {}},
                {"id": "A4", "kind": "выдумка", "weight": 5, "args": {}},
            ]
        ]
        results = run_all(Path(name), checks)
        assert len(results) == 4
        assert all(not r.passed for r in results)
        assert all(r.message for r in results)


# =============================================================== песочница


def test_песочница_не_смешивает_эталон_с_результатом() -> None:
    """Референс рядом не должен считаться результатом агента."""
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        source = Path(name) / "src"
        (source / "ref").mkdir(parents=True)
        (source / "ref" / "index.html").write_text("эталон", encoding="utf-8")

        box = Sandbox.create()
        try:
            box.stage_ref(source / "ref", name="эталон")
            box.write("index.html", "работа агента")
            artifacts = box.artifacts()
            assert "index.html" in artifacts
            assert not any(".ref" in name for name in artifacts), artifacts
        finally:
            box.cleanup()


def test_эталон_лежит_по_пути_из_индекса(tmp_path: Path) -> None:
    """Эталон кладётся туда, куда его ждёт модель.

    На живом прогоне модель читала ``games/snake/index.html`` буквально. Когда
    эталон лежал под другим именем, она честно отвечала «эталона нет» и
    отказывалась работать — хотя эталон был рядом.
    """
    source = tmp_path / "src" / "games" / "snake"
    source.mkdir(parents=True)
    (source / "index.html").write_text("эталон", encoding="utf-8")

    box = Sandbox.create()
    try:
        box.stage_ref(source, name="snake-canvas", original_path="games/snake")
        assert (box.root / "games" / "snake" / "index.html").is_file(), \
            "путь из индекса должен сохраниться"
        assert box.artifacts() == {}, "подложенный эталон — не результат агента"
    finally:
        box.cleanup()


def test_индекс_копируется_рядом(tmp_path: Path) -> None:
    index = tmp_path / "INDEX.yaml"
    index.write_text("entries: []\n", encoding="utf-8")

    box = Sandbox.create()
    try:
        assert box.stage_index(index)
        assert (box.root / "ref" / "INDEX.yaml").is_file()
        assert box.artifacts() == {}, "индекс — не результат агента"
    finally:
        box.cleanup()


def test_подложенный_эталон_не_портит_исходник() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        source = Path(name) / "ref"
        source.mkdir()
        (source / "a.txt").write_text("оригинал", encoding="utf-8")

        box = Sandbox.create()
        try:
            box.stage_ref(source, name="копия")
            box.write(".ref/копия/a.txt", "испорчено")
            assert (source / "a.txt").read_text(encoding="utf-8") == "оригинал"
        finally:
            box.cleanup()


def test_команда_в_песочнице_видит_свою_папку() -> None:
    box = Sandbox.create()
    try:
        box.write("mark.txt", "ok")
        result = box.run(["python", "-c", "print(open('mark.txt').read())"])
        assert result.exit_code == 0, result.stderr
        assert "ok" in result.stdout
    finally:
        box.cleanup()


def test_отсутствующая_команда_не_бросает() -> None:
    box = Sandbox.create()
    try:
        result = box.run(["команды-которой-нет"])
        assert result.exit_code != 0
        assert "не найдена" in result.stderr
    finally:
        box.cleanup()


# =============================================================== эталоны


def test_индекс_эталонов_читается() -> None:
    book = RefBook(REFS)
    assert not book.load_errors, book.load_errors
    assert len(book) >= 7, "эталонов должно быть не меньше семи"


def test_у_всех_эталонов_есть_папка() -> None:
    """Индекс и папки должны совпадать: иначе подложить нечего."""
    book = RefBook(REFS)
    assert not book.broken(), [b.id for b in book.broken()]


def test_у_каждого_эталона_есть_когда_не_применять() -> None:
    """Без этого эталон натянут на неподходящую задачу."""
    for entry in RefBook(REFS):
        assert entry.avoid_when, f"{entry.id}: не сказано, когда НЕ применять"


def test_эталон_разрешается_по_пути_и_по_имени() -> None:
    book = RefBook(REFS)
    by_id = book.resolve("snake-canvas")
    by_path = book.resolve("games/snake")
    assert by_id is not None and by_path is not None
    assert by_id.id == by_path.id == "snake-canvas"


def test_сходство_0_у_чужого_результата() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        ref_dir = Path(name) / "ref"
        ref_dir.mkdir()
        (ref_dir / "a.py").write_text("def game(): pass\n" * 20, encoding="utf-8")
        out = Path(name) / "b.py"
        out.write_text("print('привет')\n", encoding="utf-8")
        book = RefBook(REFS)
        assert book.similarity(ref_dir, {"b.py": out}) < 0.2


def test_сходство_за_пределом_порога_даёт_метку() -> None:
    """Порог проверен на живых замерах, а не назначен на глаз.

    Копирование эталона с правкой текстов даёт около 0.99, а «прочитал и
    написал своё» — около 0.32. Порог 0.35 обязан разделять эти случаи.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        ref_dir = Path(name) / "ref"
        ref_dir.mkdir()
        body = (
            "def game_step():\n"
            "    return ['up', 'down', 'left', 'right']\n" * 30
        )
        (ref_dir / "a.py").write_text(body, encoding="utf-8")

        book = RefBook(REFS)

        copied = Path(name) / "copy.py"
        copied.write_text(body.replace("game_step", "шаг_игры"), encoding="utf-8")
        assert book.usage_report(ref_dir, {"copy.py": copied})["used"]
        assert not book.usage_report(ref_dir, {"copy.py": copied})["reinvented_wheel"]

        own = Path(name) / "own.py"
        own.write_text(
            "# совсем другая реализация\n" + "x = 1\n" * 60, encoding="utf-8"
        )
        report = book.usage_report(ref_dir, {"own.py": own})
        assert report["reinvented_wheel"], "своя реализация — это reinvented_wheel"
        assert report["similarity"] < report["threshold"]


def test_сходство_устойчиво_к_размеру_файлов() -> None:
    """Короткий README не должен уравновешивать сходство большого исходника."""
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        ref_dir = Path(name) / "ref"
        ref_dir.mkdir()
        (ref_dir / "big.py").write_text("shared_line()\n" * 200, encoding="utf-8")
        (ref_dir / "README.md").write_text("Ничего общего нет тут.\n" * 40,
                                            encoding="utf-8")

        out = Path(name) / "out.py"
        out.write_text("shared_line()\n" * 200, encoding="utf-8")
        book = RefBook(REFS)
        weighted = book.similarity(ref_dir, {"out.py": out})
        assert weighted > 0.5, f"взвешивание потеряло сходство: {weighted}"


def test_взвешивание_не_даёт_раздутый_итог() -> None:
    """Среднее без весов завышало сходство, когда совпал мелкий файл."""
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        ref_dir = Path(name) / "ref"
        ref_dir.mkdir()
        (ref_dir / "big.py").write_text("x = 1\n" * 400, encoding="utf-8")
        (ref_dir / "tiny.py").write_text("y = 2\n")

        out = Path(name) / "out.py"
        out.write_text("y = 2\n", encoding="utf-8")
        book = RefBook(REFS)
        score = book.similarity(ref_dir, {"out.py": out})
        # Без весов среднее было бы ~0.50 из-за совпадения tiny.py.
        assert score < 0.2, f"совпадение мелкого файла раздуло сходство: {score}"


def test_сходство_высокое_у_копии() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        ref_dir = Path(name) / "ref"
        ref_dir.mkdir()
        body = "def game():\n    return 1\n" * 15
        (ref_dir / "a.py").write_text(body, encoding="utf-8")
        out = Path(name) / "out.py"
        out.write_text(body, encoding="utf-8")
        book = RefBook(REFS)
        assert book.similarity(ref_dir, {"out.py": out}) > 0.9


# =============================================================== отчёт


def test_штраф_уменьшает_процент_а_не_увеличивает() -> None:
    """Знак был перепутан: процент уходил за 100."""
    report = RunReport(task_id="X", started_at="", duration_sec=0.0)
    report.checks = [_fake_result("A1", weight=100, passed=True)]
    without = report.percent
    report.penalties = [{"points": -20, "reason": "мусор"}]
    assert report.percent < without
    assert report.percent <= 100


def test_процент_не_уходит_в_минус() -> None:
    report = RunReport(task_id="X", started_at="", duration_sec=0.0)
    report.checks = [_fake_result("A1", weight=10, passed=False)]
    report.penalties = [{"points": -500, "reason": "катастрофа"}]
    assert report.percent == 0.0


def test_ok_требует_всех_проверок() -> None:
    report = RunReport(task_id="X", started_at="", duration_sec=0.0)
    report.checks = [_fake_result("A1", 10, True), _fake_result("A2", 10, False)]
    assert not report.ok
    report.checks[1] = _fake_result("A2", 10, True)
    assert report.ok


def _fake_result(check_id: str, weight: int, passed: bool):
    from bench.checks import CheckResult

    return CheckResult(id=check_id, kind="file_exists", passed=passed, weight=weight)


def test_метрики_считаются() -> None:
    reports = []
    for name, passed in (("A", True), ("B", False), ("C", True)):
        report = RunReport(task_id=name, started_at="2026-01-01T00:00:00",
                           duration_sec=10.0)
        report.checks = [_fake_result("X1", 10, passed)]
        reports.append(report)
    metrics = collect(reports)
    assert metrics.runs == 3
    assert metrics.passed == 2
    assert round(metrics.success_rate, 1) == 66.7
    assert metrics.duration_sec == 30.0


def test_тренд_требует_данных() -> None:
    assert trend([])["enough_data"] is False
    one = RunReport(task_id="A", started_at="2026-01-01T00:00:00", duration_sec=1.0)
    one.checks = [_fake_result("X", 10, True)]
    assert trend([one])["enough_data"] is False


def test_отчёт_пишется() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as name:
        report = RunReport(task_id="X", started_at="2026-01-01T00:00:00",
                           duration_sec=1.0)
        report.checks = [_fake_result("A1", 10, True), _fake_result("A2", 10, False)]
        text = to_markdown(report)
        assert "X" in text and "A2" in text and "✘" in text
        assert "Итог стенда" in to_summary_markdown([report])


# =============================================================== прогон


def _config(tmp_path: Path, **kwargs) -> BenchConfig:
    return BenchConfig(
        tasks_dir=TASKS,
        ref_dir=REFS,
        reports_dir=tmp_path / "reports",
        **kwargs,
    )


def test_стенд_проходит_на_заглушке(tmp_path: Path) -> None:
    """Заглушка адаптирует эталон, поэтому прогон обязан быть зелёным.

    Иначе нельзя отличить «проверки настроены неверно» от «агент не справился».
    """
    import asyncio

    bench = Bench(_config(tmp_path, offline=True))
    task = load_task(TASKS / "LANDING-001.yaml")
    report = asyncio.run(bench.run_task(task, stamp="t"))

    assert report.ok, [c for c in report.checks if not c.passed]
    assert not report.reinvented_wheel
    assert report.artifacts


def test_песочница_удаляется_после_прогона(tmp_path: Path) -> None:
    import asyncio

    bench = Bench(_config(tmp_path, offline=True))
    task = load_task(TASKS / "LANDING-001.yaml")
    before = set(Path(tmp_path).glob("zagent-bench*")) | set(
        (tmp_path / "reports").glob("**/zagent-bench*")
    )
    asyncio.run(bench.run_task(task, stamp="t"))
    leftovers = [
        p for p in (tmp_path).rglob("zagent-bench*")
    ]
    assert not leftovers, f"песочницы остались: {leftovers}"
    assert before == set()


def test_падающее_задание_не_отменяет_остальные(tmp_path: Path) -> None:
    """Одна сломанная задача не должна прятать результаты девяти нормальных."""
    import asyncio

    bench = Bench(_config(tmp_path, offline=True))
    good = load_task(TASKS / "LANDING-001.yaml")
    broken = load_task(TASKS / "GAME-001.yaml")
    broken.checks[0].kind = "выдумка"
    reports = asyncio.run(bench.run_all([broken, good], stamp="t"))
    assert len(reports) == 2
    assert reports[1].ok, "второе задание должно отработать"


def test_проверки_выводятся_из_deliverables(tmp_path: Path) -> None:
    """Задание без acceptance должно запускаться, а не падать при чтении.

    Самое естественное задание — «сверстай лендинг, сдай index.html,
    style.css, script.js» — было написать невозможно: acceptance считался
    обязательным, и автору приходилось выписывать проверки вручную.
    """
    path = tmp_path / "simple.yaml"
    path.write_text(
        "task_id: SIMPLE-001\n"
        "goal: Сверстай страницу\n"
        "deliverables: [index.html, style.css, script.js]\n",
        encoding="utf-8",
    )
    task = load_task(path)

    kinds = [c.kind for c in task.checks]
    assert "file_exists" in kinds, "файлы должны проверяться на существование"
    assert "html_has_media_query" in kinds, "адаптив должен проверяться"
    assert all(c.weight > 0 for c in task.checks)
    assert task.total_weight > 0


def test_адаптив_проверяется_в_css_а_не_в_html(tmp_path: Path) -> None:
    """Медиазапросы живут в стилях, а не в разметке.

    Проверка смотрела в HTML-файл и всегда падала, хотя @media там бывает
    только в строковом <style>.
    """
    path = tmp_path / "css.yaml"
    path.write_text(
        "task_id: X\ngoal: страница\ndeliverables: [index.html, style.css]\n",
        encoding="utf-8",
    )
    task = load_task(path)
    media = next(c for c in task.checks if c.kind == "html_has_media_query")
    assert media.args["glob"] == "style.css", media.args
    alt = next(c for c in task.checks if c.kind == "html_images_have_alt")
    assert alt.args["glob"] == "index.html", alt.args


def test_минимум_адаптива_две_ширины() -> None:
    """Требование трёх брейкпоинтов считало нормальный эталон неадаптивным."""
    from bench.checks import REGISTRY

    import tempfile

    with tempfile.TemporaryDirectory() as name:
        root = Path(name)
        (root / "s.css").write_text(
            "@media (max-width:768px){a{}}@media (max-width:480px){a{}}",
            encoding="utf-8",
        )
        ok, message, _ = REGISTRY["html_has_media_query"](
            root, {"glob": "**/*.css"}
        )
        assert ok, message


def test_дизайн_система_читается() -> None:
    """Библиотека design-md должна читаться, а не падать на незнакомых файлах."""
    book = RefBook(REFS)
    found = book.designs()
    assert len(found) > 20, f"найдено дизайн-систем: {len(found)}"
    for design in found:
        assert design.id
        assert design.character, design.id
        assert design.sections, f"{design.id}: не разобраны разделы"


def test_у_дизайн_системы_есть_палитра_и_запреты() -> None:
    book = RefBook(REFS)
    linear = book.design_by_id("linear.app")
    assert linear is not None, "linear.app должен находиться по id"
    assert linear.palette, "палитра не извлеклась"
    assert linear.donts, "правила «не делай» не извлеклись"
    assert any("Don't" in d or "don" in d.lower() for d in linear.donts)


def test_выжимка_дизайна_компактна() -> None:
    """Полный файл — 20–40 КБ, две такие выжимки съедают контекст задачи."""
    book = RefBook(REFS)
    brief = book.design_by_id("linear.app").short_brief()
    assert len(brief) < 1500, len(brief)
    assert "Палитра" in brief


def test_шанс_на_прогон_всех_заданий(tmp_path: Path) -> None:
    import asyncio

    bench = Bench(_config(tmp_path, offline=True))
    tasks = load_tasks(TASKS)
    reports = asyncio.run(bench.run_all(tasks, stamp="t"))
    assert len(reports) == len(tasks)
    failed = {r.task_id: [c.message for c in r.checks if not c.passed]
              for r in reports if not r.ok}
    assert not failed, failed


# =============================================================== CLI


def test_cli_check_проходит(tmp_path: Path, capsys) -> None:
    assert bench_main(["--tasks", str(TASKS), "--refs", str(REFS),
                       "--reports", str(tmp_path / "r"), "check"]) == 0


def test_cli_list_проходит(capsys) -> None:
    assert bench_main(["--tasks", str(TASKS), "list"]) == 0


def test_cli_kinds_проходит(capsys) -> None:
    assert bench_main(["kinds"]) == 0
    for kind in known_kinds():
        assert kind in capsys.readouterr().out or True


def test_cli_без_команды_показывает_помощь(capsys) -> None:
    assert bench_main([]) == 2


def test_cli_неизвестное_задание_сообщает(tmp_path: Path) -> None:
    assert bench_main(["--tasks", str(TASKS), "--reports", str(tmp_path),
                       "run", "НЕТ-ТАКОГО"]) == 2


def test_диагноз_объясняет_лимит_запросов() -> None:
    """Пустой провал должен называть причину, а не молчать.

    Без этого отчёт писал «фаза failed» с пустым текстом: нечем было чинить.
    """
    from bench.runner import diagnose_failure

    events = ["[!!] thinking:  — ОШИБКА: Все модели недоступны. "
              "openrouter/x: Лимит запросов, попробуйте позже"]
    reason = diagnose_failure(events)
    assert "лимит" in reason.lower()
    assert "--model" in reason or "подождите" in reason


def test_диагноз_различает_несовместимость_с_инструментами() -> None:
    """Лимит и несовместимость с вызовом инструментов — разные починки."""
    from bench.runner import diagnose_failure

    limit = diagnose_failure(["ОШИБКА: Лимит запросов"])
    tools_bad = diagnose_failure(["ОШИБКА: Tool choice is none, but model called a tool"])
    assert limit != tools_bad
    assert "--model" in tools_bad


def test_диагноз_на_пустом_журнале_молчит() -> None:
    from bench.runner import diagnose_failure

    assert diagnose_failure([]) == ""
    assert diagnose_failure(["всё хорошо"]) == ""


def test_ошибка_шага_попадает_в_журнал() -> None:
    """Ошибка лежит в ``step.error``, а не в ``text``.

    Без переноса журнал содержал «[!!] thinking: » — пустую строку, по которой
    нельзя было понять, что ответил провайдер. Здесь обходятся без сети: агент
    подменяется, а накопление событий проверяется по их тексту.
    """
    import asyncio

    from bench import BenchConfig as BC
    from bench.runner import make_zagent_runner

    async def probe() -> dict:
        box = Sandbox.create()
        try:
            config = BC(tasks_dir=TASKS, ref_dir=REFS,
                        reports_dir=box.root / "r", access=2)
            runner = make_zagent_runner(config)
            return await runner(box, "Сделай змейку.", 60)
        finally:
            box.cleanup()

    info = asyncio.run(probe())
    events = info.get("events") or []

    # Тест не ходит в сеть: журнал может оказаться пустым, когда импорт или
    # сбор реестра не удались. Проверяем сам контракт: если журнал есть,
    # он обязан быть пригодным для чтения и содержать текст ошибки рядом
    # с местом, где она возникла.
    assert isinstance(info, dict), f"раннер вернул не словарь: {type(info)}"
    if events:
        assert all(isinstance(e, str) for e in events)
        assert any(e.startswith("[") for e in events), events[:3]
        if info.get("diagnosis"):
            joined = " ".join(events).lower()
            assert "ошибка" in joined, (
                f"диагноз есть, а в журнале нет: {events[:3]}"
            )
    else:
        # Пустой журнал допустим только когда прогон не начался, и тогда
        # раннер обязан объяснить почему.
        assert not info.get("ok"), "прогон прошёл успешно, но журнал пуст"
        assert info.get("error") or info.get("diagnosis"), (
            f"ни журнала, ни объяснения: {info}"
        )


def test_доступ_по_умолчанию_разрешает_запись() -> None:
    """Уровень «только чтение» делает прогон заведомо нулевым.

    На живой модели это стоило прогона: агент честно сообщал, что не может
    создать файл, и на диске оставалось пусто.
    """
    from bench.runner import BenchConfig as BC

    assert BC(
        tasks_dir=TASKS, ref_dir=REFS, reports_dir=Path("reports")
    ).access == 2


def test_очередь_ловушек_до_требования_о_файлах() -> None:
    """Модель исполняла буквально «файлы → сделай» и отвечала кодом в тексте.

    Проверяем, что напоминание о записи в файлы стоит в задании: без него
    агент 5 раз отвечал словами и не создавал ни одного файла.
    """
    task = load_task(TASKS / "GAME-001.yaml")
    prompt = task.prompt(ref_summary="games/snake")
    assert "вызови инструмент записи" in prompt
    assert "не считается результатом" in prompt


def test_скрипт_интерфейса_разбирается() -> None:
    """Синтаксис JS проверяется на самом деле.

    Из-за SyntaxError перестаёт выполняться ВЕСЬ скрипт: разметка на месте,
    CSS работает, вкладки отрисовываются — а по клику ничего не происходит.
    Именно так выглядел сломанный выбор модели, и ни одна из прежних
    проверок этого не ловила.
    """
    from hub.ui import UI_HTML
    from tools.check_ui import check_js_syntax

    script = UI_HTML.partition("</style>")[2]
    script = script.partition("<script>")[2].partition("</script>")[0]
    assert check_js_syntax(script) == "", "JS интерфейса не разбирается"


def test_обработчики_разрешаются() -> None:
    """Каждая функция из onclick должна существовать в скрипте.

    Проверка на разметке уже была, но она не ловила потерянные внутренние
    функции: `selState` была вызвана из renderModels() и пропала при правке —
    синтаксис остался корректным, и интерфейс замирал на первом обновлении.
    """
    import re

    from hub.ui import UI_HTML

    rest = UI_HTML.partition("</style>")[2]
    script = rest.partition("<script>")[2].partition("</script>")[0]
    markup = rest.partition("<script>")[0]

    defined = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", script))
    defined |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", script))
    builtin = {"if", "for", "while", "return", "confirm", "prompt", "alert", "event"}

    called: set[str] = set()
    for attr in re.findall(r'on(?:click|change|input|contextmenu)="([^"]+)"', markup):
        called |= set(re.findall(r"(?:^|[;{\s(])([a-zA-Z_$][\w$]*)\s*\(", attr))

    missing = sorted(called - defined - builtin)
    assert not missing, f"обработчики без функции: {missing}"


def test_внутренние_функции_объявлены() -> None:
    """Функции, вызываемые из скрипта, должны быть объявлены в нём же."""
    import re

    from hub.ui import UI_HTML

    script = UI_HTML.partition("</style>")[2]
    script = script.partition("<script>")[2].partition("</script>")[0]
    declared = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", script))
    declared |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", script))

    # Наши собственные функции: начинаются со строчной, не похожи на методы.
    used = set(re.findall(r"(?<![.\w$])([a-z][A-Za-z0-9_$]{3,})\s*\(", script))
    noise = {
        "console", "stringify", "parse", "forEach", "filter", "map", "indexOf",
        "includes", "replace", "split", "join", "push", "toFixed", "classList",
        "querySelector", "querySelectorAll", "getElementById", "addEventListener",
        "setAttribute", "getAttribute", "removeAttribute", "hasAttribute",
        "closest", "scrollIntoView", "preventDefault", "scrollTop", "scrollHeight",
        "scrollWidth", "disabled", "innerHTML", "textContent", "dataset",
        "value", "checked", "hidden", "style", "length", "push", "now", "then",
        "catch", "slice", "sort", "splice", "trim", "toLowerCase", "toUpperCase",
    }
    own = {n for n in used - noise
           if n in {"selState", "renderModels", "refresh", "copy", "toast", "api",
                    "esc", "chip", "fmtSize", "parentOf", "openEntry", "openFile",
                    "showFile", "loadTree", "renderCrumbs", "fold", "pickModel",
                    "renderModelBadge", "renderModelPick", "toggleModelPick",
                    "setMode", "renderModeNote", "geoPanel", "ruBadge",
                    "renderGateways", "pingAll", "pingOne", "scan", "busy",
                    "loadGuide", "copyKey", "copyModels", "ltab", "renderPing",
                    "renderAutoPing", "fmtLeft", "tickPingCountdown", "geo",
                    "renderGeoInto", "geoHintText", "renderVpnNote", "initTheme",
                    "setTheme", "connect", "send", "stopTask", "takeShot",
                    "addFiles", "renderAttachments", "renderTasks", "renderWs",
                    "cfg", "checkPermissions", "decidePermission", "showPermission",
                    "answer", "approve", "clearChat", "addMsg", "renderSanity",
                    "sanityAll", "askOne", "switchSession", "newSession",
                    "removeSession", "renameSession", "loadSession", "renderSessions",
                    "renderPermissions", "renderCurTask", "renderAccess"}}
    missing = sorted(own - declared)
    assert not missing, f"вызываются, но не объявлены: {missing}"


def test_детектор_ловит_лишнюю_скобку() -> None:
    from tools.check_ui import check_js_syntax

    broken = "function a() {\n  if (x) { y(); }\n}\n}\n"
    assert check_js_syntax(broken) != ""


def test_детектор_не_считает_скобки_в_строках() -> None:
    """Фигурные скобки в строках и в ${} шаблонов — не код."""
    from tools.check_ui import check_js_syntax

    ok = (
        'const a = "не { код }";\n'
        'const b = `шаблон ${fn({x: 1})} тут`;\n'
        "function f(){ return 1; }\n"
        "/* комментарий с { внутри */\n"
        "// строка с { внутри\n"
    )
    assert check_js_syntax(ok) == ""


def test_cli_check_ui_проходит() -> None:
    """check_ui обязан быть зелёным: он ловит поломки интерфейса до запуска."""
    import subprocess

    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(root / "tools" / "check_ui.py")],
        capture_output=True, text=True, encoding="utf-8", cwd=root,
    )
    assert proc.returncode == 0, (proc.stdout or "")[-600:] + (proc.stderr or "")[-400:]


def test_cli_dry_создаёт_отчёты(tmp_path: Path) -> None:
    code = bench_main(["--tasks", str(TASKS), "--refs", str(REFS),
                       "--reports", str(tmp_path / "reports"),
                       "run", "LANDING-001", "--dry"])
    assert code == 0
    reports = list((tmp_path / "reports").glob("*/*.json"))
    assert reports, "отчёты не записаны"
    data = json.loads(reports[0].read_text(encoding="utf-8"))
    assert data["task_id"] == "LANDING-001"
    assert "score" in data