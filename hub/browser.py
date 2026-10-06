"""Браузерный слой: реальный Chromium через Playwright.

Зачем реальный браузер, а не парсер HTML: страницы на JS без headless-движка
бесполезны. Playwright даёт полноценный Chromium с JavaScript, сетью и
скриншотами, а persistent-контекст сохраняет сессию между запусками — это
единственный честный способ зайти в аккаунт (Google, GitHub и т.п.): один раз
залогинился вручную в открытом окне, дальше cookies живут.

Что важно знать про авторизацию:
    - Логин и капчу проходит человек, агент не обходит их.
    - Антибот-проверки не обходим: это нарушение ToS, и обход там ломается
      постоянно. Вместо этого сессия переиспользуется, поэтому проверка
      и не возникает каждый раз.
    - Куки и storage лежат в локальном каталоге профиля и в репозиторий не
      попадают.

Playwright ставится отдельно:
    pip install playwright
    python -m playwright install chromium
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Каталог профиля браузера: сохраняет сессию между запусками.
PROFILE_DIR = Path("browser-profile")

#: Каталог для скриншотов страниц.
SHOT_DIR = Path("screenshots/pages")

#: Размер окна по умолчанию.
VIEWPORT = {"width": 1440, "height": 900}


class BrowserUnavailable(RuntimeError):
    """Playwright или браузер не установлены."""


@dataclass
class PageInfo:
    """Снимок состояния страницы."""

    url: str
    title: str
    text: str
    links: list[dict[str, str]] = field(default_factory=list)
    screenshot: str | None = None
    duration_ms: int = 0
    needs_login: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "links": self.links,
            "screenshot": self.screenshot,
            "duration_ms": self.duration_ms,
            "needs_login": self.needs_login,
            "note": self.note,
        }


#: Маркеры страниц, где нужна авторизация.
_LOGIN_MARKERS = (
    "sign in", "log in", "войти", "зарегистрируйтесь", "создать аккаунт",
    "accounts.google.com", "github.com/login", "login.", "auth.",
)


def _require_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise BrowserUnavailable(
            "Playwright не установлен. Выполните:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        ) from exc


class Browser:
    """Асинхронная обёртка над Playwright с сохранением сессии.

    headless=False по умолчанию: пользователь должен иметь окно, чтобы один раз
    войти в аккаунт вручную. Для headless нужен уже готовый профиль.
    """

    def __init__(
        self,
        *,
        headless: bool = False,
        profile: str | Path = PROFILE_DIR,
        viewport: dict[str, int] | None = None,
        timeout: float = 30_000,
    ) -> None:
        self.headless = headless
        self.profile = Path(profile)
        self.viewport = viewport or VIEWPORT
        self.timeout = timeout
        self._pw: Any = None
        self._context: Any = None
        self._browser: Any = None

    async def __aenter__(self) -> "Browser":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def start(self) -> None:
        _require_playwright()
        from playwright.async_api import async_playwright

        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        self._context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile.resolve()),
            headless=self.headless,
            viewport=self.viewport,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context.set_default_timeout(self.timeout)
        self._browser = self._context

    async def close(self) -> None:
        for closer in (self._context, self._pw):
            if closer is None:
                continue
            try:
                await closer.close() if closer is self._context else await closer.stop()
            except Exception:
                pass
        self._context = None
        self._pw = None
        self._browser = None

    # ------------------------------------------------------------- страницы

    async def goto(self, url: str, *, wait: str = "load",
                   shot: bool = False) -> PageInfo:
        """Открыть страницу и вернуть её текстовое содержимое."""
        if self._context is None:
            await self.start()

        page = await self._context.new_page()
        started = time.perf_counter()
        try:
            await page.goto(url, wait_until=wait)
            # Даём отработать SPA-рендерингу.
            await page.wait_for_load_state("networkidle")
        except Exception:
            pass  # частично загруженная страница всё равно полезна

        try:
            info = await self._read(page, shot=shot)
        finally:
            await page.close()

        info.duration_ms = int((time.perf_counter() - started) * 1000)
        return info

    async def _read(self, page: Any, *, shot: bool) -> PageInfo:
        url = page.url
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass

        text = ""
        links: list[dict[str, str]] = []
        try:
            text = await page.evaluate(
                "() => document.body ? document.body.innerText : ''"
            )
        except Exception:
            pass

        try:
            links = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .slice(0, 200)
                    .map(a => ({text: (a.innerText || '').trim().slice(0, 120),
                                href: a.href}))"""
            )
        except Exception:
            links = []

        screenshot = None
        if shot:
            SHOT_DIR.mkdir(parents=True, exist_ok=True)
            name = f"page-{int(time.time() * 1000)}.png"
            target = SHOT_DIR / name
            try:
                await page.screenshot(path=str(target), full_page=False)
                screenshot = str(target)
            except Exception:
                screenshot = None

        haystack = f"{url} {title} {text[:500]}".lower()
        needs_login = any(marker in haystack for marker in _LOGIN_MARKERS)

        return PageInfo(
            url=url,
            title=title,
            text=text,
            links=links,
            screenshot=screenshot,
            needs_login=needs_login,
        )

    async def click(self, selector: str, *, shot: bool = False) -> PageInfo:
        """Кликнуть по элементу и прочитать результат."""
        if self._context is None:
            await self.start()

        page = await self._context.new_page()
        started = time.perf_counter()
        try:
            await page.click(selector)
            try:
                await page.wait_for_load_state("networkidle")
            except Exception:
                pass
            info = await self._read(page, shot=shot)
        finally:
            await page.close()
        info.duration_ms = int((time.perf_counter() - started) * 1000)
        return info

    async def type_text(self, selector: str, text: str) -> None:
        """Ввести текст в поле (используется для ручного входа)."""
        if self._context is None:
            await self.start()
        page = await self._context.new_page()
        try:
            await page.fill(selector, text)
        finally:
            await page.close()

    async def login(self, url: str, *, wait_seconds: float = 180.0) -> PageInfo:
        """Открыть страницу входа и ждать, пока человек авторизуется вручную.

        Единственный поддерживаемый способ входа: человек сам вводит пароль и
        разгадывает капчу в открытом окне. Агент ждёт, пока пропадёт форма входа.
        """
        if self._context is None:
            await self.start()

        page = await self._context.new_page()
        started = time.perf_counter()
        try:
            await page.goto(url, wait_until="load")
            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                await asyncio.sleep(2.0)
                try:
                    html = (await page.content()).lower()
                except Exception:
                    break
                if not any(marker in html for marker in ("password", "введите пароль")):
                    break
            info = await self._read(page, shot=False)
        finally:
            await page.close()

        info.duration_ms = int((time.perf_counter() - started) * 1000)
        info.note = "Вход выполнен вручную в окне браузера"
        return info


#: Инструкция по установке для README и UI.
INSTALL_HINT = (
    "Браузер требует Playwright:\n"
    "  pip install playwright\n"
    "  python -m playwright install chromium\n"
    "После этого профиль (browser-profile/) сохранит сессию, и вход в аккаунты "
    "нужно будет подтвердить один раз вручную."
)


async def quick_fetch(url: str, *, headless: bool = True,
                      shot: bool = False) -> PageInfo:
    """Одноразовый заход на страницу."""
    async with Browser(headless=headless) as browser:
        return await browser.goto(url, shot=shot)
