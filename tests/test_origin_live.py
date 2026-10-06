"""Защита POST от чужого Origin — настоящим HTTP-запросом.

Проверять это через `fetch` из браузера бессмысленно: браузер не даёт задать
заголовок `Origin` вручную, он просто не уходит, и запрос проходит как свой.
Тесты на JS показали бы «всё хорошо» при полностью открытой дыре.

Здесь запрос уходит сокетом напрямую — так же, как это сделала бы посторонняя
страница.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from hub.server import ApiServer, Handler
from hub.store import Store
from hub.worker import Worker


@pytest.fixture(scope="module")
def live() -> Any:
    """Настоящий сервер на случайном порту.

    Сервер и база закрываются до удаления временной папки: на Windows файл
    SQLite держится открытым, и `TemporaryDirectory` падает с
    `PermissionError`, если соединение не разорвано.
    """
    import shutil
    import tempfile
    from http.server import ThreadingHTTPServer
    from pathlib import Path

    tmp = tempfile.mkdtemp(prefix="zagent_origin_")
    root = Path(tmp)
    (root / "config").mkdir(parents=True)

    store = Store(root)
    worker = Worker(root, store)
    api = ApiServer(root, worker)
    handler = type("BoundHandler", (Handler,), {"api": api})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, root, store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        store.close()
        shutil.rmtree(root, ignore_errors=True)


def request(port: int, path: str, headers: dict[str, str],
             body: str = "{}", keep_alive: bool = False) -> tuple[int, str, str]:
    """POST с произвольными заголовками, мимо браузера."""
    lines = [
        f"POST {path} HTTP/1.1",
        f"Host: 127.0.0.1:{port}",
        "Content-Type: application/json",
        "Content-Length: " + str(len(body.encode("utf-8"))),
    ]
    if keep_alive:
        lines.append("Connection: keep-alive")
    else:
        lines.append("Connection: close")
    lines += [f"{k}: {v}" for k, v in headers.items()]
    raw = ("\r\n".join(lines) + "\r\n\r\n" + body).encode("utf-8")

    with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:
        sock.sendall(raw)
        chunks = []
        while True:
            piece = sock.recv(65536)
            if not piece:
                break
            chunks.append(piece)
    text = b"".join(chunks).decode("utf-8", errors="replace")
    head, _, payload = text.partition("\r\n\r\n")
    first = head.split("\r\n", 1)[0].split()
    status = int(first[1]) if len(first) > 1 and first[1].isdigit() else 0
    return status, payload, head


# =============================================================== Origin


def test_свой_origin_проходит(live: Any) -> None:
    port = live[0]
    status, body, _ = request(port, "/api/permissions",
                             {"Origin": f"http://127.0.0.1:{port}"})
    assert status == 200, body


def test_без_origin_проходит(live: Any) -> None:
    """curl и сам интерфейс Origin не присылают — им нельзя мешать."""
    port = live[0]
    status, body, _ = request(port, "/api/permissions", {})
    assert status == 200, body


def test_чужой_origin_отклоняется(live: Any) -> None:
    port = live[0]
    status, body, _ = request(port, "/api/permissions",
                             {"Origin": "https://evil.test"})
    assert status == 403, f"{status} {body}"
    assert "чужого" in body.lower()


def test_origin_null_отклоняется(live: Any) -> None:
    """`null` приходит от file:// и из песочницы — это тоже внешний источник."""
    port = live[0]
    status, body, _ = request(port, "/api/permissions", {"Origin": "null"})
    assert status == 403, f"{status} {body}"


# =============================================================== Content-Type


def test_text_plain_отклоняется(live: Any) -> None:
    """Ровно этим запросом посторонняя страница дёргала все маршруты."""
    port = live[0]
    status, body, _ = request(port, "/api/permissions", {})
    assert status == 200, "для сравнения: с application/json всё проходит"

    raw_lines = [
        f"POST /api/permissions HTTP/1.1",
        f"Host: 127.0.0.1:{port}",
        "Content-Type: text/plain",
        "Content-Length: 2",
        "Connection: close",
    ]
    raw = ("\r\n".join(raw_lines) + "\r\n\r\n{}").encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:
        sock.sendall(raw)
        data = b""
        while True:
            piece = sock.recv(65536)
            if not piece:
                break
            data += piece
    text = data.decode("utf-8", errors="replace")
    assert " 403 " in text.split("\r\n")[0], text[:200]


# =============================================================== keep-alive


def test_отказ_закрывает_соединение(live: Any) -> None:
    """Иначе чужое тело останется в буфере и испортит следующий запрос."""
    port = live[0]
    raw = (
        f"POST /api/permissions HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        "Content-Type: text/plain\r\nContent-Length: 2\r\n"
        "Connection: keep-alive\r\nOrigin: https://evil.test\r\n\r\n{}"
    ).encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:
        sock.sendall(raw)
        sock.settimeout(10)
        data = b""
        try:
            while True:
                piece = sock.recv(65536)
                if not piece:
                    break
                data += piece
        except socket.timeout:
            pass
    text = data.decode("utf-8", errors="replace")
    assert " 403 " in text.split("\r\n", 1)[0]
    assert "close" in text.lower(), "соединение не закрыто"


# =============================================================== маршруты живы


def test_все_маршруты_отвечают(live: Any) -> None:
    """После разрыва класса половина маршрутов перестала существовать."""
    import httpx

    port = live[0]
    base = f"http://127.0.0.1:{port}"
    with httpx.Client(timeout=30) as client:
        assert client.get(base + "/").status_code == 200, "главная страница"
        assert client.get(base + "/api/state").status_code == 200, "состояние"
        assert client.get(base + "/api/tasks").status_code == 200, "задачи"
        assert client.get(base + "/api/permissions").status_code == 200
        # Поток событий открывается и сразу закрывается сервером при обрыве.
        with client.stream("GET", base + "/api/events?since=999999999") as resp:
            assert resp.status_code == 200, "поток событий"


def test_файлы_читаются(live: Any) -> None:
    """Маршрут /api/files был среди потерянных при разрыве класса."""
    import httpx

    port = live[0]
    with httpx.Client(timeout=30) as client:
        r = client.post(base_url := f"http://127.0.0.1:{port}/api/files",
                        json={"path": "."}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True


def test_base_dir_из_post_ограничен(live: Any) -> None:
    """Неаутентифицированный клиент не может выбрать границу доступа."""
    import httpx

    port = live[0]
    with httpx.Client(timeout=30) as client:
        r = client.post(f"http://127.0.0.1:{port}/api/config",
                        json={"base_dir": "C:/"})
        assert r.status_code >= 400 or r.json().get("ok") is not True
        assert "воркспейс" in r.text.lower() or r.json().get("ok") is not True