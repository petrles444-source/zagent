#!/usr/bin/env python3
"""Запуск веб-интерфейса zagent.

    python tools/web.py                 # http://127.0.0.1:8777
    python tools/web.py --port 9000
    python tools/web.py --no-open       # не открывать браузер

Интерфейс: статус моделей с кнопкой пинга, проверка адекватности, одиночные
запросы через failover, агент с уровнями доступа, снимки экрана для
vision-моделей.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.web import serve  # noqa: E402


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(description="Веб-интерфейс zagent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--no-open", action="store_true", help="не открывать браузер")
    args = parser.parse_args(argv)

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
