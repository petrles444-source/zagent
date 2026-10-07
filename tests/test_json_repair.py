"""Единый JSON-ремонтник — Волна 2 п.5 плана update-07-10-26.txt.

Раньше у агента и у роя были два разных разбора ответов модели, причём у
роя — более узкий (без BOM, без хвостовых запятой и кавычек). Один и тот
же ответ принимался в одном месте и отвергался в другом: «разбить не
вышло» тихо откатывал параллельную работу в одиночную.

Проверяется цепочка ремонта (общая функция), поведение через публичные
функции обоих читателей и сохранение прежних смыслов `_safe_loads`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.agent import _safe_loads, _strip_trailing_commas, load_json_any  # noqa: E402
from hub.subagents import _loads, parse_parts  # noqa: E402


# ------------------------------------------------------- общий ремонтник


def test_честный_json_разбирается_без_ремонта() -> None:
    data, error = load_json_any('{"a": 1}')
    assert (data, error) == ({"a": 1}, "")


def test_bom_не_считается_поломкой() -> None:
    """Windows Notepad кладёт метку кодировки перед текстом."""
    data, error = load_json_any('﻿{"a": 1}')
    assert (data, error) == ({"a": 1}, "")


def test_питоновский_литерал_с_одинарными_кавычками() -> None:
    data, error = load_json_any("{'parts': [{'title': 'а'}]}")
    assert error == ""
    assert data == {"parts": [{"title": "а"}]}


def test_хвостовая_запятая_перед_null_чинится() -> None:
    """`literal_eval` здесь не помощник: null — не литерал Python."""
    data, error = load_json_any('{"parts": [{"title": "а",}], }')
    assert error == ""
    assert data == {"parts": [{"title": "а"}]}


def test_запятая_внутри_строки_не_страдает() -> None:
    """Наивная регулярка портила бы текст — сканер обязан видеть строки."""
    raw = '{"t": "конец,}", "b": null,}'
    assert _strip_trailing_commas(raw) == '{"t": "конец,}", "b": null}'
    data, error = load_json_any(raw)
    assert error == ""
    assert data == {"t": "конец,}", "b": None}


def test_явная_порча_не_лечится_в_рабочий_вызов() -> None:
    """`{,}` — не хвостовая запятая, а мусор: он обязан дойти как ошибка.

    Иначе `{"tool": "read_file", "args": {,},}` превратился бы в вызов
    read_file без пути: агент получил бы его как настоящий шаг, а сообщение
    «формат испорчен» — то, что заставляет модель переписать ответ, —
    потерялось бы.
    """
    # Запятая после `{` — порча, её сканер не трогает (в отличие от
    # честной хвостовой после значения).
    assert _strip_trailing_commas('{"a": {,}}') == '{"a": {,}}'
    data, error = load_json_any('{"tool": "read_file", "args": {,},}')
    assert data is None
    assert error


def test_мусор_даёт_описание_ошибки() -> None:
    data, error = load_json_any("просто текст")
    assert data is None
    assert error, "ошибка обязана описывать, что именно не так"


def test_пустой_фрагмент_не_падает() -> None:
    data, error = load_json_any("   ")
    assert data is None
    assert error


def test_экранирование_в_строке_переживает_ремонт() -> None:
    # В JSON кавычка внутри строки экранирована: \" — и поломка в ней
    # (хвостовая запятая после) не должна её испортить.
    data, error = load_json_any(r'{"t": "скобка } и \" кавычка",}')
    assert error == ""
    assert data["t"] == 'скобка } и " кавычка'


# ------------------------------------------------- агент: вызовы инструментов


def test_агент_принимает_инструмент_под_bom() -> None:
    calls, error = _safe_loads('﻿{"tool": "read_file", "args": {"path": "a.py"}}')
    assert error == ""
    assert calls == [{"tool": "read_file", "args": {"path": "a.py"}}]


def test_агент_по_прежнему_сообщает_об_ошибке() -> None:
    """Ошибка нужна, чтобы отличить «ответ словами» от «формат испорчен»."""
    calls, error = _safe_loads("это не вызов")
    assert calls == []
    assert error


# --------------------------------------------------------- рой: разбиение


def test_рой_понимает_ответ_под_bom_и_в_литерале() -> None:
    # Та же структура, но написанная как Python-литерал (одинарные кавычки)
    # и с BOM — раньше рой её отвергал, а агент принимал.
    assert _loads("﻿{'parts': [{'title': 'титул'}]}") == {
        "parts": [{"title": "титул"}],
    }
    text = "﻿```json\n{'parts': [{'title': 'титул', 'brief': 'сделать'}]}\n```"
    assert [p.title for p in parse_parts(text)] == ["титул"]


def test_два_объекта_в_ответе_находят_нужный() -> None:
    """Жадные срезы склеивают два объекта в мусор — точный обход спасает."""
    text = ('Вот разбивка. {"note": "черновик"} '
            '{"parts": [{"title": "а", "brief": "сделать а"}]}')
    parsed = parse_parts(text)
    assert len(parsed) == 1
    assert parsed[0].title == "а"


def test_fenced_блок_по_прежнему_в_почёте() -> None:
    text = '```json\n{"parts": [{"title": "б", "brief": "сделать б"}]}\n```'
    parsed = parse_parts(text)
    assert [p.title for p in parsed] == ["б"]


def test_пустой_ответ_рой_считает_провалом() -> None:
    assert parse_parts("") == []
    assert parse_parts("не смог разбить") == []
