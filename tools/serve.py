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
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import bootlog  # noqa: E402  — после правки sys.path, иначе нет пакета
from hub import bridge as donor_bridge  # noqa: E402
from hub.server import serve  # noqa: E402


def _force_utf8() -> None:
    """Перевести вывод в UTF-8 и заставить его сбрасываться построчно.

    Без `line_buffering` окно запуска остаётся чёрным: когда stdout не
    считается терминалом (перенаправление, запуск через bat), Python
    держит текст в буфере и отдаёт его в самом конце. Человек запускает
    zagent.bat, видит пустую консоль — и это выглядит как зависание,
    хотя сервер уже работает. Сброс по строке ничего не стоит.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except (AttributeError, ValueError, OSError):
            pass


#: Где искать Chrome. Открываем его явно, а не «браузером по умолчанию»:
#: в Windows по умолчанию часто стоит Edge, а человек работает в Chrome,
#: и привычные расширения и горячие клавиши должны работать.
CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
)


def find_chrome() -> str:
    r"""Первый найденный Chrome. Пустая строка — не найден.

    Ищем здесь, а не только в .bat, потому что программу запускают ещё и
    напрямую (`python tools\serve.py`), и там браузер по умолчанию мог бы
    оказаться не тем.
    """
    import os

    for raw in CHROME_PATHS:
        path = Path(os.path.expandvars(raw))
        if path.exists():
            return str(path)
    return ""


def _open_in_browser(url: str, browser: str = "") -> None:
    """Открыть адрес в браузере.

    Порядок такой: указанный браузер, затем найденный Chrome, затем
    браузер системы. Ошибка запуска не должна ронять сервер: адрес
    человек откроет руками, а упавшая программа хуже.
    """
    for candidate in (browser, find_chrome()):
        if not candidate:
            continue
        exe = Path(candidate)
        if not exe.exists():
            continue
        try:
            subprocess.Popen([str(exe), url])
            print(f"Открываю в Chrome: {url}")
            return
        except OSError:
            continue
    try:
        webbrowser.open(url)
        print(f"Открываю в браузере по умолчанию: {url}")
    except Exception:  # noqa: BLE001 — браузер тут не главное
        print(f"Откройте вручную: {url}")


def _boot_state(args: Any, bridge_url: str) -> dict[str, Any]:
    """Собрать реальные данные для красного лога загрузки.

    Читаем ровно то, что успевает прочитаться быстро: конфиг шлюзов,
    секреты (только факт наличия ключа), базу и локальный рантайм. Тяжёлые
    вещи — сбор реестра моделей — в лог не попадают: лог должен печататься
    быстро и не мешать старту.
    """
    from typing import Any

    from hub import diag

    root = Path(args.base).resolve()
    state: dict[str, Any] = {
        "root": str(root),
        "python": sys.version.split()[0],
        "db": str(root / "web-state" / "zagent.db"),
        "diag": str(root / "web-state" / diag.DIAG_NAME),
        "gateways": [],
        "models": None,
        "bridge": {"running": False, "port": args.bridge_port, "models": 0},
        "local": {"running": False, "models": []},
    }
    try:
        from hub.config import load_gateways

        state["gateways"] = [
            {"id": g.get("id"), "has_key": bool(g.get("has_key"))}
            for g in load_gateways(root, env={})
        ]
    except Exception:  # noqa: BLE001 — лог не должен ломать старт
        pass
    try:
        from hub import local_llm

        found = local_llm.models()
        state["local"] = {"running": True,
                          "models": [m["id"] for m in found][:6]}
    except Exception:  # noqa: BLE001
        pass
    return state


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
    parser.add_argument("--browser", default="",
                        help="путь к браузеру (например chrome.exe); пусто — "
                             "найти Chrome самому, иначе браузер системы")
    parser.add_argument("--no-bootlog", action="store_true",
                        help="не печатать подробный лог загрузки")
    args = parser.parse_args(argv)

    url = f"http://{args.host}:{args.port}"
    bridge_url = f"http://127.0.0.1:{args.bridge_port}"

    # Красный лог загрузки печатается сразу: пустое окно выглядит как
    # зависание, даже когда сервер уже поднимается. Данные для него
    # собираем из настоящего состояния установки.
    if not args.no_bootlog:
        bootlog.run(_boot_state(args, bridge_url))

    # Донорский шлюз поднимается ДО основного сервера и на отдельном
    # порту: он нужен дебагеру и прямому доступу к моделям opencode, и
    # ждать его рядом с основным интерфейсом незачем. Если opencode
    # выключен, шлюз всё равно поднимается и честно пишет «недоступен».
    bridge = None
    if not args.no_bridge:
        bridge = donor_bridge.start_with(root=Path(args.base).resolve(),
                                         port=args.bridge_port)

    if not args.no_open:
        # Основной интерфейс — через 1.5 секунды, как раньше: за это
        # время сервер успевает подняться. Панель шлюза — вкладкой позже:
        # к её открытию адрес уже отвечает, и человек не видит страницы
        # «не удалось подключиться».
        threading.Timer(1.5, lambda: _open_in_browser(
            url, args.browser)).start()
        if bridge is not None:
            threading.Timer(3.0, lambda: _open_in_browser(
                bridge_url, args.browser)).start()

    serve(args.host, args.port, root=Path(args.base).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
