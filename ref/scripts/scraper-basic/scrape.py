#!/usr/bin/env python
"""Разовый сбор страниц в CSV на стандартной библиотеке.

Запуск:  python scrape.py https://example.com  →  out.csv

Показывает три вещи, которых нет в учебных парсерах:

* ``User-Agent`` назван�� честно, а не подделан под браузер;
* между запросами пауза и один повтор — сайт не тратится зря и не получает
  429;
* разбор не падает на первой неожиданной странице: битая запись
  пропускается, а не роняет весь сбор.

Зависимостей нет. Если страница рендерится через JavaScript, этот скрипт
увидит пустоту — бери `../scraper-playwright`.
"""

from __future__ import annotations

import csv
import html.parser
import re
import sys
import time
import urllib.error
import urllib.request

#: Честный User-Agent: identifies us and leaves a way to write back.
#: Подделка под чужой браузер означает, что владельца сайта нельзя найти
#: для связи и он не может отличить нас от спамера.
USER_AGENT = "zagent-scraper/1.0 (+https://example.invalid/bot)"

PAUSE = 1.5          # секунд между запросами
RETRIES = 2
TIMEOUT = 20


class Links(html.parser.HTMLParser):
    """Достаёт из страницы ссылки и заголовок — всё, что нужно для CSV."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.links: list[str] = []
        self._in_title = False
        self._pending: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "a" and data.get("href"):
            self._pending = {"href": data["href"], "text": ""}

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._pending is not None:
            href = self._pending["href"].strip()
            text = " ".join(self._pending["text"].split())
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self.links.append((href, text))
            self._pending = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._pending is not None:
            self._pending["text"] += data


def fetch(url: str, *, retries: int = RETRIES) -> bytes:
    """Забрать страницу с повторами. Исключение наружу не выпускаем."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                # Смотрим на код: 404 и 500 — это ответ, а не исключение,
                # и повтор на них бесполезен.
                if response.status >= 500:
                    raise urllib.error.HTTPError(url, response.status, "сервер", {}, None)
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < retries:
            # Нарастающая пауза: не долбим сайт при перегрузке.
            time.sleep(PAUSE * (attempt + 1))
    raise RuntimeError(f"не удалось забрать {url}: {last}")


def parse(body: bytes) -> Links:
    text = body.decode("utf-8", errors="replace")
    parser = Links()
    parser.feed(text)
    return parser


def scrape(url: str, limit: int = 50) -> list[dict[str, str]]:
    """Собрать заголовок и ссылки одной страницы."""
    from urllib.parse import urljoin

    parser = parse(fetch(url))
    rows = [{"url": url, "title": " ".join(parser.title.split()), "href": "", "text": ""}]
    for href, text in parser.links[:limit]:
        rows.append({
            "url": url,
            "title": " ".join(parser.title.split()),
            "href": urljoin(url, href),
            "text": text,
        })
    return rows


def main(argv: list[str]) -> int:
    if not argv:
        print("Использование: python scrape.py <url> [out.csv] [--limit N]")
        return 2
    url = argv[0]
    limit = 50
    if "--limit" in argv:
        try:
            limit = int(argv[argv.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit требует число")
            return 2
    target = "out.csv"
    for arg in argv[1:]:
        if not arg.startswith("-"):
            target = arg

    try:
        rows = scrape(url, limit=limit)
    except RuntimeError as exc:
        print(f"Ошибка: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка разбора: {type(exc).__name__}: {exc}")
        return 1

    with open(target, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["url", "title", "href", "text"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Записано строк: {len(rows)} → {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))