"""Сервер не должен отдавать то, что не belongs его владельцу.

Программа слушает только 127.0.0.1, но аутентификации у неё нет. Поэтому
единственная защита от посторонней страницы — заголовок Origin: запрос с
чужим адресом не доходит до обработчика вовсе.

Без этой проверки любая открытая вкладка отправляла `text/plain`-fetch
кросс-доменно (он не проходит preflight), то есть могла читать файлы и
запускать задачи от имени пользователя.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.server import Handler  # noqa: E402


class _Headers(dict):
    """Заголовки без учёта регистра, как у http.client.

    Именно так ведёт себя настоящий `self.headers`: имя `Content-Type`
    находится по `get("content-type")`. Обычный dict для этого не годится.
    """

    def get(self, name: str, default: Any = None) -> Any:  # type: ignore[override]
        for key, value in self.items():
            if key.lower() == name.lower():
                return value
        return default


def handler_with(headers: dict[str, str]) -> Any:
    """Обработчик с подставленными заголовками, без сокета."""
    handler = Handler.__new__(Handler)
    handler.headers = _Headers(headers)  # type: ignore[assignment]
    return handler


# =============================================================== Origin


def test_свой_origin_проходит() -> None:
    assert Handler._same_origin(handler_with({"Origin": "http://127.0.0.1:8783"}))
    assert Handler._same_origin(handler_with({"Origin": "http://localhost:8783"}))


def test_без_origin_проходит() -> None:
    """curl, тесты и сам интерфейс шлют запрос без Origin."""
    assert Handler._same_origin(handler_with({}))


def test_чужой_origin_отклоняется() -> None:
    assert not Handler._same_origin(handler_with({"Origin": "https://example.com"}))
    assert not Handler._same_origin(
        handler_with({"Origin": "http://127.0.0.1.evil.test"}))
    assert not Handler._same_origin(handler_with({"Origin": "null"}))
    assert not Handler._same_origin(handler_with({"Origin": "непонятно"}))


def test_подделка_в_скобках_отклоняется() -> None:
    """`[::1]:8783.evil` — настоящая дырка, если смотреть только hostname.

    `urlparse("http://[::1]:8783.evil").hostname` возвращает `::1`, поэтому
    проверка одного hostname принимала бы поддельный адрес за свой.
    """
    handler = handler_with({"Origin": "http://[::1]:8783.evil"})
    assert not Handler._same_origin(handler)


def test_origin_сравнивается_с_host() -> None:
    """Свой адрес отличается только портом — это тот же сервер."""
    same = handler_with({
        "Origin": "http://127.0.0.1:8783", "Host": "127.0.0.1:8783",
    })
    assert Handler._same_origin(same)

    # Тот же хост, но другой порт — это уже другой сервер.
    other = handler_with({
        "Origin": "http://127.0.0.1:9999", "Host": "127.0.0.1:8783",
    })
    assert not Handler._same_origin(other)


# =============================================================== Content-Type


def test_json_разбирается() -> None:
    handler = handler_with({"Content-Length": "9"})
    handler.rfile = _FakeStream('{"a": 1}')
    assert Handler._body(handler) == {"a": 1}


def test_не_json_отклоняется() -> None:
    """Именно этот путь используют кросс-доменные запросы."""
    handler = handler_with({
        "Content-Type": "text/plain;charset=UTF-8",
        "Content-Length": "7",
    })
    handler.rfile = _FakeStream('{"a":1}')
    with pytest.raises(ValueError) as exc:
        Handler._body(handler)
    assert "application/json" in str(exc.value)


def test_пустое_тело_не_ошибка() -> None:
    handler = handler_with({"Content-Length": "0"})
    handler.rfile = _FakeStream("")
    assert Handler._body(handler) == {}


def test_не_объект_отбрасывается() -> None:
    """Список вместо словаря — это ошибка вызова, а не настройки."""
    handler = handler_with({
        "Content-Type": "application/json", "Content-Length": "9",
    })
    handler.rfile = _FakeStream('[1, 2, 3]')
    assert Handler._body(handler) == {}


def test_битый_json_не_роняет() -> None:
    handler = handler_with({
        "Content-Type": "application/json", "Content-Length": "3",
    })
    handler.rfile = _FakeStream('{{ {')
    assert Handler._body(handler) == {}


class _FakeStream:
    def __init__(self, data: str) -> None:
        self._data = data.encode("utf-8")

    def read(self, count: int) -> bytes:
        head, self._data = self._data[:count], self._data[count:]
        return head


# =============================================================== base_dir


def test_base_dir_ограничен_списком_воркспейсов(tmp_path: Path) -> None:
    """Граница доступа сервера не должна задаваться посторонним клиентом.

    `base_dir` определяет, какие файлы вообще видит программа: по нему
    строится дерево `/api/files`, и туда же пишется снимок экрана. Если
    принять произвольный путь, то `{"base_dir": "C:/Users/HP"}` открывает
    чтение всего диска.
    """
    from hub.store import Store
    from hub.worker import Worker

    (tmp_path / "config").mkdir(parents=True)
    store = Store(tmp_path)
    worker = Worker(tmp_path, store)
    try:
        known = str(worker.workspaces.items[0].resolved())
        worker.set_base_dir(known)

        with pytest.raises(ValueError) as exc:
            worker.set_base_dir(str(tmp_path.parent))
        assert "воркспейс" in str(exc.value).lower()
    finally:
        store.close()


def test_set_base_dir_принимает_известную(tmp_path: Path) -> None:
    from hub.store import Store
    from hub.worker import Worker

    (tmp_path / "config").mkdir(parents=True)
    other = tmp_path / "моя-папка"
    other.mkdir()
    store = Store(tmp_path)
    worker = Worker(tmp_path, store)
    try:
        worker.workspaces.add(str(other), name="моя")
        worker.set_base_dir(str(other))
        assert worker.config.base_dir == str(other.resolve())
    finally:
        store.close()


def test_каталог_не_проходит(tmp_path: Path) -> None:
    """Даже если каталог существует, но в списке его нет — отказ."""
    from hub.store import Store
    from hub.worker import Worker

    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "чужая").mkdir()
    store = Store(tmp_path)
    worker = Worker(tmp_path, store)
    try:
        with pytest.raises(ValueError):
            worker.set_base_dir(str(tmp_path / "чужая"))
    finally:
        store.close()