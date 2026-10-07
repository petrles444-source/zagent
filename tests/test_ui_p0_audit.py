"""P0 и P1 из аудита интерфейса: дефекты, которые ломали работу молча.

Что чинится здесь:

* тема писалась строкой, а читалась через `JSON.parse` — выбор человека
  терялся при каждом F5, и выглядело это как «иногда не та тема»;
* `setupGrips` стоял на верхнем уровне скрипта без `try`: испорченное
  значение в localStorage роняло скрипт целиком вместе со всеми
  обработчиками;
* переменная `--line` не была объявлена ни в одной теме, и полоса
  прогресса деградировала до `currentColor`;
* вложения не очищались после отправки — следующая задача молча
  переотправляла картинки предыдущей;
* путь артефакта вставлялся в атрибут через `JSON.stringify`: имя файла с
  кавычкой закрывало атрибут и ломало разметку;
* `esc()` внутри `onclick="copy('…')"` не годится: парсер декодирует
  `&#39;` обратно в апостроф уже после разбора атрибута, и строка рвётся;
* `api()` ловил только разбор JSON, но не сам запрос, поэтому падение
  сервера выглядело как «интерфейс завис»;
* `send()` очищал поле до запроса и при отказе терял текст задачи.

Тесты построены так, чтобы ломаться при возврате любой из правок:
каждый проверяет конкретную строку, а не «наличие файла».
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.ui import UI_HTML  # noqa: E402


def script() -> str:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    _, _, rest = src.partition("</style>")
    return rest.partition("<script>")[2].partition("</script>")[0]


def style() -> str:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    return src.partition("</style>")[0]


def body_of(body: str, header: str) -> str:
    """Текст функции по имени — чтобы проверка не задела соседние строки."""
    start = body.index(header)
    depth = 0
    for i in range(start, len(body)):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                return body[start : i + 1]
    raise AssertionError(f"не нашли конец функции {header}")


# ==================================================================== тема


def test_тема_читается_строкой_а_не_через_json() -> None:
    """Раньше setTheme писал 'dark', а initTheme делал JSON.parse — падало."""
    body = script()
    init = body_of(body, "function initTheme()")
    assert "JSON.parse" not in init, "тему нельзя читать через JSON.parse"
    assert "THEMES.includes(raw)" in init, "значение надо проверять по списку тем"


def test_тема_пишется_строкой() -> None:
    body = script()
    setter = body_of(body, "function setTheme(name)")
    assert "localStorage.setItem('zagent.theme', name)" in setter


def test_тема_раньше_не_сохранялась() -> None:
    """Памятка о том, что было: если вернут JSON.parse — тест упадёт."""
    body = script()
    head = body_of(body, "function initTheme()")
    assert "saved = raw ? JSON.parse(raw) : null;" in head or "JSON.parse" not in head


# ============================================================ инициализация


def test_setup_grips_разбирает_layout_в_try() -> None:
    """Испорченный layout ронял весь скрипт на верхнем уровне."""
    body = script()
    grips = body_of(body, "(function setupGrips()")
    assert "try {" in grips, "разбор localStorage должен быть в try"
    assert "catch" in grips
    assert "JSON.parse(localStorage.getItem('zagent.layout')" in grips


def test_grips_устойчив_к_null_и_мусору() -> None:
    """'null' — валидный JSON, но saved.lw на нём роняет скрипт."""
    body = script()
    grips = body_of(body, "(function setupGrips()")
    assert "|| {}" in grips, "нужен запасной объект на случай null"


# ==================================================================== темы CSS


def test_line_объявлена_в_темах() -> None:
    """Полоса прогресса ссылалась на переменную, которой не было нигде."""
    css = style()
    assert re.search(r"--line\s*:", css), "--line не объявлена ни в одной теме"


def test_line_связана_с_edge() -> None:
    """Чтобы не расходиться с темой: --line = var(--edge)."""
    css = style()
    assert "--line: var(--edge);" in css


def test_line_объявлена_один_раз_в_базовом_правиле() -> None:
    """Пять копий в пяти темах разъедутся при правке одной."""
    css = style()
    assert css.count("--line:") == 1, "переменная объявлена в нескольких местах"


# ================================================================ вложения


def test_вложения_чистятся_после_отправки() -> None:
    """Список картинок уезжал в следующую задачу вместе с накоплением."""
    body = script()
    send = body_of(body, "async function send()")
    assert "ATTACH = [];" in send, "вложения не очищаются после отправки"


def test_очистка_вложений_происходит_после_проверки_ошибки() -> None:
    """Иначе при отказе сервера вложения потеряются вместе с задачей."""
    body = script()
    send = body_of(body, "async function send()")
    assert send.index("if (!r.ok)") < send.index("ATTACH = [];")


# ============================================================ артефакты


def test_путь_артефакта_не_вставляется_через_json_stringify() -> None:
    """Кавычка в имени файла закрывала атрибут onclick."""
    body = script()
    arts = body_of(body, "function renderArtifacts(list)")
    assert "JSON.stringify(a.path)" not in arts, "путь снова попадает в onclick"
    assert "data-art=" in arts, "путь должен лежать в data-атрибуте"


def test_по_артефакту_есть_обработчик_клика() -> None:
    """Убрав onclick, надо повесить клик иначе ссылка мертва."""
    body = script()
    assert "addEventListener('click', ev => showArtifact" in body


# ============================================== строки внутри onclick


def test_в_onclick_используется_jsq_а_не_esc() -> None:
    """esc() кладёт &#39;, парсер декодирует его обратно в апостроф."""
    body = script()
    attr = re.compile(r'onclick="([^"]*)"')
    bad = [a for a in attr.findall(body) if "'${esc(" in a]
    assert not bad, f"в onclick остался esc: {bad[:3]}"


def test_jsq_объявлен_и_экранирует_апостроф() -> None:
    body = script()
    assert "function jsq(" in body
    jsq = body_of(body, "function jsq(")
    assert ".replace(/'/g, '\\\\u0027')" in jsq, "апостроф должен уходить в \\u0027"


def test_jsq_экранирует_обратный_слэш_и_переводы_строк() -> None:
    """Иначе путь с обратным слэшем или переносом снова ломает литерал."""
    body = script()
    jsq = body_of(body, "function jsq(")
    assert ".replace(/\\\\/g, '\\\\\\\\')" in jsq
    assert "/\\r/g" in jsq and "/\\n/g" in jsq


def test_jsq_закрывает_теги_после_экранирования() -> None:
    """Значение из данных не должно закрывать тег скрипта."""
    body = script()
    jsq = body_of(body, "function jsq(")
    assert "u003c" in jsq and "u003e" in jsq
    assert jsq.index("<") > jsq.index("function jsq")


def test_в_разметке_остались_jsq_вызовы() -> None:
    """Правка должна быть применена, а не только объявлена."""
    body = script()
    assert "${jsq(" in body


# ================================================================ api()


def test_api_lovit_setevuyu_oshibku() -> None:
    """Отказ fetch улетал наверх: refresh замирал, send — «в очереди…»."""
    body = script()
    api = body_of(body, "async function api(")
    assert api.count("try {") >= 2, "нужны два try: на запрос и на разбор JSON"
    assert "catch (e)" in api
    assert "ok:false" in api, "отказ должен выглядеть как {ok:false, error}"


def test_api_сообщает_о_недоступности() -> None:
    body = script()
    api = body_of(body, "async function api(")
    assert "сервер недоступен" in api


# ================================================================ send()


def test_send_возвращает_текст_при_ошибке() -> None:
    """Раньше задача исчезала бесследно: поле чистили до запроса."""
    body = script()
    send = body_of(body, "async function send()")
    assert "box.value = text;" in send, "текст не возвращается в поле при отказе"


def test_send_чистит_поле_до_запроса() -> None:
    """Поведение остаётся прежним: поле не мигает текстом во время отправки."""
    body = script()
    send = body_of(body, "async function send()")
    assert send.index("box.value = '';") < send.index("await api('/api/tasks'")


# ================================================================ HTML жив


def test_страница_собирается() -> None:
    """Дешёвая страховка: шаблон не должен развалиться при правках.

    Скриптов два: в <head> — мгновенная отрисовка темы без моргания,
    в конце body — основной код.
    """
    assert UI_HTML.count("<script") == UI_HTML.count("</script>") == 2
    assert UI_HTML.rstrip().endswith("</html>")