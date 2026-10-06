"""Веб-ресёрч: поиск и чтение страниц.

Зачем это агенту: модель помнит то, что видела при обучении, и ничего из
того, что вышло после. Поиск и чтение страниц дают два недостающих
инструмента: узнать новое и проверить, что известное ещё актуально.

Ограничения, которые заданы провайдером, а не нами:
- результаты поиска длиннее примерно 2000 символов на ответ обрезаются, то
  есть агент получает лишь верхние ссылки;
- из одной страницы читается не больше 4000 символов;
- страницы отдают и robots.txt, поэтому часть сайтов недоступна.

Из этого следует главное правило работы: найти — мало. Ссылку надо открыть
и прочитать, иначе в отчёт попадёт заголовок из выдачи, а не содержание.

Поиск сделан на DuckDuckGo: у него есть обычная страница результатов без
ключа и без капчи. Обход антиботов (Google, Cloudflare) намеренно не
делается: закрытый сайт — это честный отказ агенту, а не повод идти
обходить чужую защиту.
"""

from __future__ import annotations

import html as html_module
import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

#: Сколько символов отдаёт провайдер на один результат поиска.
SEARCH_RESULT_CHARS = 2000

#: Сколько символов можно взять с одной страницы.
PAGE_CHARS = 4000

#: Что выкидываем при извлечении текста. Меню и подвалы не несут смысла, но
#: съедают весь лимит, из-за чего полезный текст не влезает.
_STRIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer",
               "aside", "form", "iframe", "template"}

#: Теги, перед которыми стоит перенос строки: без него абзацы слипаются в
#: один поток и читать невозможно.
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
               "section", "article", "ul", "ol", "table", "blockquote", "pre"}

#: Теги без пары. Их нельзя класть в стек пропуска: у `<br>` нет закрывающего,
#: и счётчик разъезжался бы на каждом таком теге.
_VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "source", "wbr",
              "col", "area", "base", "embed", "param", "track"}

#: Теги с собственно статьёй внутри. Если они есть, берётся только то, что в
#: них: на sqlite.org из 31 600 символов полезных было меньше половины, а
#: остальное — «Home | Menu | About | Documentation» в двух экземплярах.
_CONTENT_TAGS = {"article", "main"}

#: Классы и id, по которым элемент считается оформлением сайта.
#:
#: Одних тегов мало: sqlite.org размечает меню как `<div class="menu
#: mainmenu">`, и никакого `<nav>` там нет вовсе. Разметка через классы — норма
#: для обычных сайтов, а не признак плохой вёрстки.
_BOILERPLATE_NAMES = {
    "menu", "mainmenu", "submenu", "searchmenu", "navbar", "navigation", "nav",
    "sidebar", "breadcrumb", "breadcrumbs", "footer", "site-footer",
    "cookie-banner", "cookies", "advert", "ads", "advertisement",
    "social", "share", "skip-link", "skiplink",
}

#: Начала имён классов: `menu-mainmenu`, `nav-item`, `sidebar-left`.
_BOILERPLATE_PREFIXES = ("menu", "nav-", "navbar", "sidebar", "footer",
                         "breadcrumb", "site-nav")

#: Сколько раз короткая строка может повториться, прежде чем её признают
#: пунктом меню. Три — потому что выпадающие списки бывают двухуровневые.
_MENU_REPEATS = 3

#: Короткой считается строка короче этого: у настоящего абзаца длина больше,
#: а «Documentation» — нет.
_MENU_LINE_CHARS = 70


def _is_boilerplate(attrs: list[tuple[str, str | None]]) -> bool:
    """Элемент с классом или id меню, подвала или рекламы."""
    for name, value in attrs:
        if name not in ("class", "id") or not value:
            continue
        for token in re.split(r"[\s,]+", value.strip().lower()):
            if not token:
                continue
            if token in _BOILERPLATE_NAMES:
                return True
            if token.startswith(_BOILERPLATE_PREFIXES):
                return True
    return False


class _Text(HTMLParser):
    """Достать читаемый текст и заголовок из HTML.

    Пропуск оформления ведётся стеком открытых элементов, а не счётчиком.
    Разметка в интернете часто не сбалансирована: sqlite.org пишет `<li>` без
    закрывающего тега, и при «снять верхний элемент стека» закрывающий `</div>`
    снимал не тот элемент. Пропуск после первого меню не заканчивался, и со
    страницы оставалось 41 символ вместо статьи.

    Поэтому при закрытии ищем ближайший открытый тег с таким именем и
    снимаем всё до него включительно.
    """

    def __init__(self, *, only_content: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        # Открытые элементы: (имя тега, начинался ли на нём пропуск).
        self._stack: list[tuple[str, bool]] = []
        self._skip = 0
        self._in_title = False
        # Когда берём только статью, всё вне <main>/<article> пропускается.
        self._only_content = only_content
        self._outside = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        hide = tag in _STRIP_TAGS or _is_boilerplate(attrs)
        # Одиночные теги не имеют пары: иначе стек разъезжается на каждом
        # `<br>`, и пропуск перестаёт когда-либо заканчиваться.
        if tag not in _VOID_TAGS:
            self._stack.append((tag, hide))
        if hide:
            self._skip += 1
            return
        if self._only_content and tag in _CONTENT_TAGS and self._outside == 0:
            self._outside = 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        position = next((i for i in range(len(self._stack) - 1, -1, -1)
                         if self._stack[i][0] == tag), None)
        if position is None:
            # Закрывающий тег без пары: в кривой разметке так бывает, и это
            # не повод сдвигать пропуск.
            return
        for _, hide in self._stack[position:]:
            if hide:
                self._skip = max(0, self._skip - 1)
        del self._stack[position:]

        if self._skip:
            return
        if self._only_content and tag in _CONTENT_TAGS and self._outside:
            self._outside = 0
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data.strip()
            return
        if self._only_content and not self._outside:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        joined = "\n".join(self.parts)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def drop_menu_repeats(text: str) -> str:
    """Убрать пункты меню, повторяющиеся на странице десяток раз.

    Настоящий абзац так не выглядит: если короткая строка встречается
    трижды и больше, это пункт навигации, а не содержание. Длинные строки
    не трогаем — повторяться могут и абзацы, например в списке литературы.
    """
    seen: dict[str, int] = {}
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if len(stripped) < _MENU_LINE_CHARS:
            count = seen.get(stripped, 0) + 1
            seen[stripped] = count
            if count >= _MENU_REPEATS:
                continue
        kept.append(line)
    return "\n".join(kept)


def html_to_text(html: str) -> tuple[str, str]:
    """Текст и заголовок страницы. Возвращает ("", "") на мусоре.

    Сначала пробуем взять только статью: если она есть, она и есть смысл
    страницы. Если нет — берём всю страницу и отдельно выкидываем
    повторяющиеся пункты меню.
    """
    whole = _Text()
    content = _Text(only_content=True)
    try:
        whole.feed(html or "")
        content.feed(html or "")
    except Exception:
        # Некорректная разметка не должна ронять инструмент: вернём то,
        # что удалось разобрать.
        pass
    body = content.text() or whole.text()
    return drop_menu_repeats(body), whole.title


@dataclass
class SearchHit:
    """Один результат поиска."""

    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def parse_search(text: str) -> list[SearchHit]:
    """Разобрать ответ поисковика.

    Формат у всех примерно одинаков: заголовок, ссылка, описание. Разбираем
    построчно, а не по структуре, потому что разметка у сервисов разная, а
    видеть надо всё, что вернулось.
    """
    hits: list[SearchHit] = []
    current = {"title": "", "url": "", "snippet": ""}

    def flush() -> None:
        if current["url"]:
            hits.append(SearchHit(current["title"] or current["url"],
                                  current["url"], current["snippet"]))
        current.update(title="", url="", snippet="")

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # Ссылки приходят либо голой строкой, либо в markdown-скобках.
        match = re.match(r"^\[?<?(https?://[^\s>\]»]+)>?\]?", line)
        if match:
            if current["url"]:
                flush()
            current["url"] = match.group(1).rstrip(".,;:")
            continue
        if not current["url"] and line:
            current["title"] = line.lstrip("# ").strip()
        elif current["url"]:
            current["snippet"] = (current["snippet"] + " " + line).strip()
    flush()
    return hits


def page_text(html: str, limit: int = PAGE_CHARS) -> dict[str, Any]:
    """Читаемый текст страницы с обрезкой по лимиту провайдера."""
    text, title = html_to_text(html)
    cut = len(text) > limit
    return {
        "title": title,
        "text": text[:limit],
        "truncated": cut,
        "chars": len(text),
    }


# ==================================================================== сеть


#: Страница результатов DuckDuckGo. Ключа не требует, капчи не показывает.
SEARCH_URL = "https://html.duckduckgo.com/html/"

#: Запасной адрес. У полной версии периодически отдаётся пустая страница,
#: а лёгкая отвечает и в этом случае.
SEARCH_FALLBACK = "https://lite.duckduckgo.com/lite/"

#: Обычный браузер, а не бот. Поисковик без этого отдаёт пустую выдачу.
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

#: Больше этого не читаем. Страница на 20 МБ — это уже не статья, а мусор,
#: который съест память процесса и время ожидания.
MAX_DOWNLOAD_BYTES = 3 * 1024 * 1024

#: Ответы, которые невозможно превратить в текст.
_TEXTUAL_TYPES = ("text/html", "application/xhtml", "text/plain", "text/markdown",
                  "application/json", "application/xml", "text/xml")


class WebError(RuntimeError):
    """Сеть или сайт не дали того, что нужно. Текст — для агента."""


def check_url(url: str) -> str:
    """Проверить, что адрес годится для чтения. Вернёт его же.

    Отдельная проверка, а не предположение, потому что агент работает с
    текстом, который сам же и составил: в него может попасть адрес из
    найденной страницы. `http://127.0.0.1:8783/api/state` — это не ошибка
    поиска, это чтение собственного сервера агента, где лежат ключи
    провайдеров и содержимое чужих папок.
    """
    raw = str(url or "").strip()
    if not raw:
        raise WebError("Пустой адрес.")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise WebError(f"Схема {parsed.scheme or '?'} не поддерживается, "
                       "нужен http или https.")
    host = parsed.hostname
    if not host:
        raise WebError("В адресе нет узла.")

    if host.lower() in ("localhost",) or host.endswith(".local"):
        raise WebError(f"Адрес {host} указывает на эту же машину.")

    # Адрес может быть именем, и тогда без разрешения не проверить. В этом
    # списке только служебные сети: публичные адреса резолвятся все.
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise WebError(f"Не удалось разрешить {host}: {exc.strerror or exc}") from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise WebError(
                f"{host} ведёт во внутреннюю сеть ({address}). "
                "Внутренние адреса читать нельзя."
            )
    return raw


def _client(timeout: float) -> Any:
    import httpx

    # Редиректы **не** следуются автоматически. `check_url` запрещает читать
    # внутреннюю сеть, и это обходилось одним редиректом: публичный сайт
    # отвечает `302` на `http://127.0.0.1:8783/api/state`, httpx следует за
    # ним молча, и содержимое уходит агенту. Ровно тот случай, ради которого
    # проверка написана, а в её комментарии этот адрес назван прямо.
    return httpx.Client(follow_redirects=False, timeout=timeout,
                        headers=BROWSER_HEADERS)


def _download(url: str, timeout: float) -> tuple[str, str]:
    """Скачать адрес и вернуть (текст, content-type).

    Редирект обрабатывается здесь, а не клиентом: адрес назначения
    проходит ту же проверку, что и исходный. Просто «следовать» нельзя —
    это и есть обход.
    """
    target = url
    for _ in range(MAX_REDIRECTS):
        with _client(timeout) as client:
            with client.stream("GET", target) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise WebError("Сайт перенаправил, но не сказал куда.")
                    target = str(httpx.URL(target).join(location))
                    # Тот же барьер, что и для исходного адреса.
                    check_url(target)
                    continue
                if response.status_code >= 400:
                    raise WebError(f"Сайт ответил {response.status_code}.")
                content_type = str(
                    response.headers.get("content-type") or "").lower()
                if content_type and not any(t in content_type
                                            for t in _TEXTUAL_TYPES):
                    raise WebError(
                        f"По ссылке не текст, а {content_type.split(';')[0]}. "
                        "Читать нечего."
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_DOWNLOAD_BYTES:
                        break
                raw = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                return raw.decode(encoding, errors="replace"), content_type
    raise WebError(f"Слишком много редиректов: больше {MAX_REDIRECTS}.")


#: Сколько редиректов считать нормой. Браузер делает около двадцати.
MAX_REDIRECTS = 10


class _Results(HTMLParser):
    """Разбор страницы результатов поисковика.

    Разметка у полной и лёгкой версий разная, но классов-ориентиров хватает
    для обеих: `result__a` и `result-link` — это ссылка на результат,
    `result__snippet` и `result-snippet` — описание под ним.
    """

    _LINK_CLASSES = ("result__a", "result-link")
    _SNIPPET_CLASSES = ("result__snippet", "result-snippet")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[SearchHit] = []
        self._skip = 0
        self._url = ""
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._in_snippet = 0
        #: Сниппет этого результата уже собран — чтобы следующий результат
        #: не приписал к своему заголовку чужое описание.
        self._snippet_done = False

    @staticmethod
    def _classes(attrs: list[tuple[str, str | None]]) -> str:
        for name, value in attrs:
            if name == "class" and value:
                return value
        return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        if any(name in classes for name in self._SNIPPET_CLASSES):
            self._in_snippet += 1
            return
        if tag != "a":
            return
        if not any(name in classes for name in self._LINK_CLASSES):
            return
        href = next((v for k, v in attrs if k == "href" and v), "")
        url = unwrap_search_url(href)
        if not url:
            return
        self._flush()
        self._url = url
        self._snippet_done = False
        self._title = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if self._in_snippet and tag in ("td", "div", "p", "a"):
            # Блок сниппета закрыт. Он не привязан к `_url`: у полной версии
            # поисковика описание лежит отдельной ссылкой уже после
            # заголовка, и `_url` к этому моменту пуст.
            self._in_snippet = 0
            self._snippet_done = True
            return
        # `</a>` у ссылки **на заголовок** результата ничего не завершает.
        # Описание лежит в следующей ссылке и достаётся весь разумета раньше заголовка.
        # Закрывать на этом моменте означение подает пустым, а описание отдается следующему результату — агент получал перепутанные описания.
        # Результат закрывается на начале следующей ссылки и в `close()`.

    def handle_data(self, data: str) -> None:
        if self._skip or not data.strip():
            return
        if self._in_snippet:
            self._snippet.append(data.strip())
        elif self._url:
            self._title.append(data.strip())

    def _flush(self) -> None:
        if not self._url:
            return
        self.hits.append(SearchHit(
            title=" ".join(self._title) or self._url,
            url=self._url,
            snippet=" ".join(self._snippet)[:400],
        ))
        self._url = ""
        self._title = []
        self._snippet = []

    def close(self) -> None:  # noqa: D102
        super().close()
        self._flush()


def unwrap_search_url(href: str) -> str:
    """Настоящий адрес из ссылки поисковика.

    DuckDuckGo отдаёт переходник вида
    `//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F&rut=...`.
    Без разворачивания агент получил бы в ссылке адрес поисковика, а не
    сайта, и открыть её было бы нечем.
    """
    text = html_module.unescape(str(href or "").strip())
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = "https://duckduckgo.com" + text
    parsed = urlparse(text)
    if "duckduckgo.com" in parsed.netloc:
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else ""
    return text


def search_web(query: str, *, max_results: int = 6,
               timeout: float = 25.0) -> list[SearchHit]:
    """Найти в интернете. Пустой список — либо ничего не нашлось, либо
    поисковик закрыт.

    Различить эти два случая должен сам инструмент: агенту нужна разная
    подсказка. «Ничего не нашлось» ведёт к другому запросу, «поисковик
    закрыт» — к работе по уже имеющимся источникам.
    """
    question = str(query or "").strip()
    if not question:
        raise WebError("Пустой запрос.")

    last_error = ""
    for url in (SEARCH_URL, SEARCH_FALLBACK):
        try:
            page, _ = _download_with_params(url, {"q": question}, timeout)
        except WebError as exc:
            last_error = str(exc)
            continue
        parser = _Results()
        try:
            parser.feed(page)
            parser.close()
        except Exception as exc:  # кривая разметка — не повод падать
            last_error = f"Не удалось разобрать выдачу: {type(exc).__name__}"
            continue
        if parser.hits:
            return parser.hits[:max(1, int(max_results))]
        last_error = "Поисковик вернул пустую выдачу."
    raise WebError(last_error or "Поиск не дал результатов.")


def _download_with_params(url: str, params: dict[str, str],
                          timeout: float) -> tuple[str, str]:
    """Скачать адрес с параметрами запроса."""
    import httpx

    with httpx.Client(follow_redirects=True, timeout=timeout,
                      headers=BROWSER_HEADERS) as client:
        response = client.get(url, params=params)
        if response.status_code >= 400:
            raise WebError(f"Поисковик ответил {response.status_code}.")
        return response.text, str(response.headers.get("content-type") or "")


def fetch_page(url: str, *, limit: int = PAGE_CHARS,
               timeout: float = 25.0) -> dict[str, Any]:
    """Открыть страницу и вернуть её текст."""
    safe = check_url(url)
    html, content_type = _download(safe, timeout)
    result = page_text(html, limit=limit)
    result["url"] = safe
    result["content_type"] = content_type.split(";")[0]
    return result
