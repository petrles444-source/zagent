"""gzip, ETag и 304 — Волна 3 п.11 плана update-07-10-26.txt.

Интерфейс раз в секунду тянет `/api/state` и раз за сессию грузит страницу:
без валидаторов каждый раз едут одни и те же байты. Здесь проверяется
сжатие, условный повтор и — отдельно — что соединение не рассыпается после
304 без тела: протокол HTTP/1.1, тело не отправлено, и любая ошибка в
рамке (Content-Length, порядок заголовков) немедленно ломает следующий
запрос на том же сокете.

Запросы идут сырыми сокетами, минуя браузер: заголовок If-None-Match
нельзя подделать через fetch, а браузерные тесты показали бы «всё
работает» при полностью битой рамке.
"""

from __future__ import annotations

import gzip
import json
import shutil
import socket
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from hub.server import ApiServer, Handler
from hub.store import Store
from hub.worker import Worker


@pytest.fixture(scope="module")
def live() -> Any:
    """Настоящий сервер на случайном порту (схема из test_origin_live)."""
    tmp = tempfile.mkdtemp(prefix="zagent_cache_")
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


def _read_response(reader: Any) -> tuple[int, dict[str, str], bytes]:
    """Прочитать один ответ, точно следуя Content-Length.

    Заголовки собираем по байту: точный размер неизвестен, а сокет может
    отдать что угодно. Тело читаем строго по Content-Length — в 304 этого
    заголовка нет, и читается ноль байт, что и есть правда.
    """
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = reader.read(1)
        if not chunk:
            raise AssertionError("соединение оборвалось до конца заголовков")
        head += chunk
    head = head.split(b"\r\n\r\n", 1)[0]

    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    length = int(headers.get("content-length", 0))
    body = reader.read(length) if length else b""
    return status, headers, body


def get(port: int, path: str, headers: dict[str, str] | None = None
        ) -> tuple[int, dict[str, str], bytes]:
    """Один GET с заголовками, каких требует проверка."""
    lines = [f"GET {path} HTTP/1.1",
             f"Host: 127.0.0.1:{port}",
             "Connection: close"]
    lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:
        sock.sendall(raw)
        reader = sock.makefile("rb")
        return _read_response(reader)


# --------------------------------------------------------------- заголовки


def test_state_отдаёт_etag_и_no_cache(live: Any) -> None:
    port, _root, _store = live
    status, headers, body = get(port, "/api/state")

    assert status == 200
    assert headers["etag"].startswith('"') and headers["etag"].endswith('"')
    # no-cache значит «перед использованием спроси», а не «не храни»:
    # именно на этом построен 304 ниже.
    assert headers["cache-control"] == "no-cache"
    assert json.loads(body.decode("utf-8"))


def test_короткий_ответ_не_сжимается(live: Any) -> None:
    """Порог GZIP_MIN_BYTES: на трёх байтах экономия отрицательная."""
    port, _root, _store = live
    status, headers, _body = get(
        port, "/api/tasks?limit=1", {"Accept-Encoding": "gzip"})
    assert status == 200
    assert "content-encoding" not in headers


def test_страница_тоже_под_тегом(live: Any) -> None:
    port, _root, _store = live
    status, headers, _body = get(port, "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert "etag" in headers


# ------------------------------------------------------------------- gzip


def test_gzip_по_желанию_клиента(live: Any) -> None:
    port, _root, _store = live
    _s, plain_h, plain = get(port, "/api/state")
    status, headers, body = get(
        port, "/api/state", {"Accept-Encoding": "gzip"})

    assert status == 200
    assert headers["content-encoding"] == "gzip"
    # Без Vary кэш смешал бы сжатую и несжатую версии разных клиентов.
    assert headers["vary"] == "Accept-Encoding"
    assert gzip.decompress(body) == plain
    assert len(body) < len(plain), "сжатый ответ должен быть меньше"
    # Разным представлениям — разные теги, иначе кэш путает размеры.
    assert headers["etag"] != plain_h["etag"]
    assert headers["etag"].endswith('-gzip"')


def test_клиент_без_gzip_получает_исходник(live: Any) -> None:
    port, _root, _store = live
    status, headers, body = get(
        port, "/api/state", {"Accept-Encoding": "identity"})
    assert status == 200
    assert "content-encoding" not in headers
    assert body.decode("utf-8").lstrip().startswith("{")


# ------------------------------------------------------------------- 304


def test_повтор_с_тем_же_тегом_отдаёт_304_без_тела(live: Any) -> None:
    port, _root, _store = live
    _s, headers, body = get(port, "/api/state")
    status, headers2, body2 = get(
        port, "/api/state", {"If-None-Match": headers["etag"]})

    assert status == 304
    assert body2 == b"", "тело в 304 быть не должно"
    assert headers2["etag"] == headers["etag"], \
        "тег обязан совпасть с присланным, иначе клиент обновит своё впустую"
    assert len(body2) < len(body), "смысл 304 — не платить за тело"


def test_304_работает_и_для_сжатой_версии(live: Any) -> None:
    """Клиент хранит gzip-копию и приходит с её тегом."""
    port, _root, _store = live
    _s, headers, _body = get(
        port, "/api/state", {"Accept-Encoding": "gzip"})
    status, headers2, body2 = get(port, "/api/state", {
        "Accept-Encoding": "gzip",
        "If-None-Match": headers["etag"],
    })
    assert status == 304
    assert body2 == b""
    assert headers2["etag"] == headers["etag"]


def test_чужой_тег_не_экономит(live: Any) -> None:
    """Не совпавший тег — обычный ответ с телом, а не молчаливый 304."""
    port, _root, _store = live
    status, _headers, body = get(
        port, "/api/state", {"If-None-Match": '"0000deadbeef0000"'})
    assert status == 200
    assert json.loads(body.decode("utf-8"))


def test_ошибка_не_превращается_в_304(live: Any) -> None:
    """Условный повтор действует только для 200.

    Иначе повторная ошибка (задача не найдена) скрывалась бы за пустым
    304, и клиент не узнал бы, что запрос провалился.
    """
    port, _root, _store = live
    status, headers, _body = get(port, "/api/task/999999")
    assert status == 404
    assert "etag" in headers

    status2, _h2, body2 = get(
        port, "/api/task/999999", {"If-None-Match": headers["etag"]})
    assert status2 == 404, "совпавший тег превратил ошибку в 304"
    assert body2, "тело ошибки обязано дойти до клиента"


# ----------------------------------------------------- живое соединение


def test_после_304_соединение_не_разваливается(live: Any) -> None:
    """Три запроса подряд на одном сокете: 200 → 304 → 200.

    304 идёт без тела и почти без заголовков; если рамка посчитана
    неверно, сервер ждёт тело, клиент ждёт заголовок — и оба висят до
    таймаута. Здесь это падает сразу и понятно.
    """
    port, _root, _store = live
    with socket.create_connection(("127.0.0.1", port), timeout=20) as sock:
        reader = sock.makefile("rb")

        def call(extra: list[str]) -> tuple[int, dict[str, str], bytes]:
            lines = [f"GET /api/state HTTP/1.1",
                     f"Host: 127.0.0.1:{port}",
                     *extra]
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
            return _read_response(reader)

        status1, headers1, body1 = call(["Connection: keep-alive"])
        assert status1 == 200 and body1

        status2, _h2, body2 = call([
            "Connection: keep-alive",
            f"If-None-Match: {headers1['etag']}",
        ])
        assert status2 == 304 and body2 == b""

        status3, _h3, body3 = call(["Connection: close"])
        assert status3 == 200
        assert body3 == body1, "после 304 состояние должно отдаваться как прежде"
