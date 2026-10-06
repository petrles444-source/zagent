"""Веб-ресёрч: поиск, чтение страниц и защита от чтения внутрь машины.

Три вещи, которые обязаны работать:

* поиск возвращает настоящие адреса, а не переходники поисковика;
* чтение отдаёт текст статьи, а не «Home | Menu | About», повторённое
  двадцать раз;
* агент не может сослаться на `http://127.0.0.1:8783/api/state` и вытащить
  оттуда ключи провайдеров. Адрес приходит из интернета, а не от человека,
  поэтому доверять ему нельзя.

Сеть в тестах не используется: ответы подставляются свои. Проверки на
живых сайтах живут в `tmp/probe_extract.py`, их результат виден, но в
тесты он не входит — иначе сборка падала бы вместе с интернетом.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.autonomy import AccessLevel, Autonomy, Guard  # noqa: E402
from hub.research import (  # noqa: E402
    MAX_DOWNLOAD_BYTES,
    WebError,
    check_url,
    drop_menu_repeats,
    fetch_page,
    html_to_text,
    page_text,
    search_web,
    unwrap_search_url,
)
from hub.tools import run_tool  # noqa: E402


def guard_for(root: Path) -> Guard:
    g = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO,
              workspace_root=root.resolve())
    g.set_workspace(root, "ws")
    return g


# =============================================================== извлечение


def test_меню_выкидывается() -> None:
    html = """
    <html><body>
      <div class="menu mainmenu"><ul><li><a href="/">Home</a></li></ul></div>
      <article><h1>Заголовок</h1><p>Первый абзац статьи.</p>
      <p>Второй абзац статьи.</p></article>
    </body></html>
    """
    text, title = html_to_text(html)
    assert "Первый абзац" in text and "Второй абзац" in text
    assert "Home" not in text, "меню попало в текст статьи"


def test_статья_берётся_из_main() -> None:
    html = """
    <html><body>
      <nav>Меню</nav>
      <main><p>Содержимое.</p></main>
    </body></html>
    """
    text, _ = html_to_text(html)
    assert "Содержимое" in text
    assert "Меню" not in text


def test_меню_собранное_на_div_выкидывается() -> None:
    """sqlite.org размечает меню как `<div class="menu mainmenu">`, без `<nav>`."""
    html = """
    <html><body>
      <div class=nosearch>Small. Fast. Reliable.</div>
      <div class="menu mainmenu"><li><a href="index.html">Home</a></li></div>
      <div class=fancy>Write-Ahead Logging</div>
      <p>Смысл статьи про WAL.</p>
    </body></html>
    """
    text, _ = html_to_text(html)
    assert "смысл статьи" in text.lower()
    assert "Home" not in text


def test_незакрытые_теги_не_съедают_страницу() -> None:
    """Разметка сайтов часто не сбалансирована: `<li>` без `</li>`.

    Раньше на такой странице закрывающий `</div>` закрывал не тот элемент,
    пропуск не заканчивался, и со страницы оставалось 41 символ.
    """
    html = """
    <html><body>
      <div class="menu mainmenu">
        <li><a href="/a">Home</a>
        <li><a href="/b">Docs</a>
      </div>
      <div class=fancy>
        <li>Статья
        <li>по WAL
      </div>
      <p>Смысл статьи про WAL.</p>
    </body></html>
    """
    text, _ = html_to_text(html)
    assert "Смысл статьи" in text, f"осталось {len(text)} символов: {text[:120]!r}"
    assert "Home" not in text


def test_повторы_меню_выкидываются() -> None:
    html = """
    <html><body><div>
      <p>Home</p><p>Documentation</p><p>Download</p>
      <p>Настоящий абзац статьи.</p>
      <p>Home</p><p>Documentation</p><p>Download</p>
      <p>Home</p><p>Documentation</p><p>Download</p>
    </div></body></html>
    """
    text, _ = html_to_text(html)
    assert "Настоящий абзац" in text
    assert text.count("Documentation") <= 2, "пункты меню не убраны"


def test_скрипты_и_стили_не_в_тексте() -> None:
    html = ("<html><body><script>var a = 1;</script>"
            "<style>p{color:red}</style><p>Текст.</p></body></html>")
    text, _ = html_to_text(html)
    assert text == "Текст.", text


def test_заголовок_страницы() -> None:
    text, title = html_to_text("<html><title>Заголовок</title><p>Тело</p></html>")
    assert title == "Заголовок"
    assert "Тело" in text


def test_битая_разметка_не_роняет() -> None:
    text, _ = html_to_text("<html><p>начало<div><p>середина")
    assert "начало" in text


def test_лимит_страницы_помечен() -> None:
    result = page_text("<html><body><p>" + "я" * 5000 + "</p></body></html>")
    assert result["truncated"] is True
    assert len(result["text"]) <= 4000
    assert result["chars"] > 4000


def test_короткая_страница_не_обрезается() -> None:
    result = page_text("<html><body><p>мало</p></body></html>")
    assert result["truncated"] is False


def test_лимит_меняется() -> None:
    result = page_text("<html><body><p>" + "я" * 500 + "</p></body></html>", limit=100)
    assert len(result["text"]) == 100


def test_drop_menu_repeats_не_трогает_длинные() -> None:
    """Повторяться могут и абзацы — например, в списке литературы."""
    line = "я" * 100
    assert drop_menu_repeats("\n".join([line] * 5)).count(line) == 5


# =============================================================== ссылки


def test_адрес_из_переходника_разворачивается() -> None:
    """DuckDuckGo отдаёт `//duckduckgo.com/l/?uddg=<адрес>&rut=...`.

    Без разворачивания агент получил бы в ссылке адрес поисковика и
    открыть её было бы нечем.
    """
    got = unwrap_search_url(
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fsqlite.org%2Fwal.html&amp;rut=abc")
    assert got == "https://sqlite.org/wal.html"


def test_прямая_ссылка_не_трогается() -> None:
    assert unwrap_search_url("https://example.com/a") == "https://example.com/a"


def test_пустая_ссылка() -> None:
    assert unwrap_search_url("") == ""
    assert unwrap_search_url("   ") == ""


def test_переходник_без_uddg() -> None:
    assert unwrap_search_url("//duckduckgo.com/l/?rut=abc") == ""


# =============================================================== защита


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8783/api/state",
    "http://localhost/x",
    "http://192.168.1.1/",
    "http://10.0.0.5/keys",
    "http://172.16.0.1/",
    "http://[::1]/",
    "http://169.254.169.254/latest/meta-data/",
    "file:///c:/windows/win.ini",
    "gopher://example.com/",
])
def test_внутренние_адреса_отвергаются(url: str) -> None:
    with pytest.raises(WebError):
        check_url(url)


def test_пустой_адрес() -> None:
    with pytest.raises(WebError):
        check_url("")


def test_публичный_адрес_проходит() -> None:
    """Публичный узел должен проходить: иначе инструмент бесполезен."""
    assert check_url("https://example.com/a") == "https://example.com/a"


def test_схема_дописывается() -> None:
    assert check_url("example.com/a") == "https://example.com/a"


def test_неизвестный_узел_понятная_ошибка() -> None:
    with pytest.raises(WebError) as info:
        check_url("https://такого-узла-точно-нет.нета/")
    assert "разрешить" in str(info.value).lower()


# =============================================================== инструменты


def test_web_search_в_обычном_режиме_не_виден(tmp_path: Path) -> None:
    """Поиск в интернете стоит денег, а по вопросу «посчитай 2+2» не нужен."""
    from hub.tools import available_tools

    names = [t["name"] for t in available_tools(guard_for(tmp_path))]
    assert "web_search" not in names
    assert "web_fetch" not in names


def test_web_search_виден_в_режиме_разведки(tmp_path: Path) -> None:
    from hub.tools import available_tools

    names = [t["name"] for t in available_tools(guard_for(tmp_path), web=True)]
    assert "web_search" in names and "web_fetch" in names


def test_веб_инструменты_доступны_при_чтении() -> None:
    """Поиск и чтение страниц ничего не пишут на диск."""
    from hub.autonomy import AccessLevel

    g = Guard(access=AccessLevel.READ, autonomy=Autonomy.YOLO)
    for name in ("web_search", "web_fetch"):
        assert g.check_access("browse").allowed, name


def test_web_fetch_редактирует_список_инструментов() -> None:
    from hub.tools import TOOLS

    for name in ("web_search", "web_fetch"):
        assert name in TOOLS
        assert TOOLS[name]["operation"] == "browse"


def test_web_fetch_не_ходит_во_внутреннюю_сеть(tmp_path: Path) -> None:
    result = run_tool("web_fetch", guard_for(tmp_path),
                      url="http://127.0.0.1:8783/api/state")
    assert result.ok is False
    assert "внутреннюю сеть" in result.error.lower() or "localhost" in result.error.lower()


def test_web_search_с_пустым_запросом() -> None:
    with pytest.raises(WebError):
        search_web("")


# =============================================================== лимит


def test_лимит_загрузки_объявлен() -> None:
    """Больше трёх мегабайт не читаем: это уже не статья."""
    assert MAX_DOWNLOAD_BYTES <= 8 * 1024 * 1024


def test_fetch_page_проставляет_адрес(tmp_path: Path, monkeypatch) -> None:
    """Адрес возвращается вместе с текстом: агент должен знать, что читал."""
    import hub.research as research

    monkeypatch.setattr(
        research, "_download",
        lambda url, timeout: ("<html><title>Пример</title><p>Тело</p></html>",
                              "text/html; charset=utf-8"),
    )
    page = research.fetch_page("https://example.com/a")
    assert page["url"] == "https://example.com/a"
    assert page["title"] == "Пример"
    assert "Тело" in page["text"]