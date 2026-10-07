#!/usr/bin/env python3
r"""Запуск агента с фоновой очередью и живым интерфейсом.

    python tools\serve.py               # http://127.0.0.1:8783
    python tools\serve.py --port 9000
    python tools\serve.py --no-open

Отличие от tools\web.py: задачи агента выполняются в фоне и переживают
закрытие вкладки, журнал приходит в браузер потоком (SSE), состояние
хранится в SQLite и восстанавливается при перезапуске.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import bridge as donor_bridge  # noqa: E402
from hub.server import serve  # noqa: E402


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(description="zagent: фоновый агент")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8783)
    parser.add_argument("--no-open", action="store_true", help="не открывать браузер")
    parser.add_argument("--base", default=".", help="рабочая директория агента")
    parser.add_argument("--no-bridge", action="store_true",
                        help="не поднимать донорский шлюз")
    parser.add_argument("--bridge-port", type=int,
                        default=donor_bridge.DEFAULT_PORT,
                        help="порт донорского шлюза")
    args = parser.parse_args(argv)

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # Донорский шлюз поднимается ДО основного сервера и на отдельном
    # порту: он нужен дебагеру и прямому доступу к моделям opencode, и
    # ждать его рядом с основным интерфейсом незачем. Если opencode
    # выключен, шлюз всё равно поднимается и честно пишет «недоступен».
    if not args.no_bridge:
        donor_bridge.start_with(root=Path(args.base).resolve(),
                                port=args.bridge_port)

    serve(args.host, args.port, root=Path(args.base).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
