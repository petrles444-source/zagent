"""Локальный сервер для проверки сайта — без кэша.

Зачем свой, а не `python -m http.server`: тот отдаёт файлы с обычным
кэшированием, и браузер молча показывает старую версию `app.js`. После
правки страница выглядит как «ничего не изменилось», хотя изменилось
всё, и правку приходится искать не там.

Заголовки отправляются и для HTML, и для скриптов: без `Cache-Control`
браузер применяет эвристику и держит файл до устаревания.

Запуск:
    .venv\Scripts\python.exe tools\serve_site.py [порт]
"""

from __future__ import annotations

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
DEFAULT_PORT = 8901


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Отдача файлов сайта с запретом кэша."""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def log_message(self, *args: object) -> None:
        # Доступы не интересны: их будет много, а пользы ноль.
        pass


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    handler = partial(NoCacheHandler, directory=str(SITE))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"сайт на http://127.0.0.1:{port}/ из {SITE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
