"""Радио: список станций, пинг, маршруты API, вкладка интерфейса, CLI.

Тесты короткие, но кусающие: каждая проверка ловит конкретную мутацию
(подмена порядка станций, удаление фолбэка HEAD→GET, убраный DoEvents
из плеера, пропавшая вкладка радио).
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Импорт tools/zradio.py без запуска main()
_spec = importlib.util.spec_from_file_location("zradio", ROOT / "tools" / "zradio.py")
assert _spec and _spec.loader
zradio = importlib.util.module_from_spec(_spec)
sys.modules["zradio"] = zradio
_spec.loader.exec_module(zradio)

from hub import radio as radio_mod  # noqa: E402


# ------------------------------------------------------------ stations.json


class TestStationsJson:
    """Единый источник списка станций."""

    def test_личная_подборка_сверху(self) -> None:
        """Три личные станции пользователя — первые в списке."""
        stations = radio_mod.load_stations(ROOT)
        assert len(stations) >= 30, "список станций не должен пустеть"
        personal = [s for s in stations if s.get("group") == "Личная подборка"]
        assert len(personal) == 3, "личная подборка должна быть из 3 станций"
        # Первые три станции — личная подборка
        assert stations[0]["group"] == "Личная подборка"
        assert stations[1]["group"] == "Личная подборка"
        assert stations[2]["group"] == "Личная подборка"
        # Конкретные URL из запроса пользователя
        urls = {s["url"] for s in personal}
        assert "https://edge22.stream.maxfive.com/max5-city23/stream/mp3" in urls
        assert "https://stream.studio21.ru/studio2196.aacp" in urls
        assert "https://radiorecord.hostingradio.ru/phonk96.aacp" in urls

    def test_url_уникальны(self) -> None:
        """Дубли URL сломали бы поиск и пинг."""
        stations = radio_mod.load_stations(ROOT)
        urls = [s["url"] for s in stations]
        assert len(urls) == len(set(urls)), "URL станций должны быть уникальны"

    def test_все_url_http(self) -> None:
        """Плеер и пинг работают только с http/https."""
        stations = radio_mod.load_stations(ROOT)
        for s in stations:
            assert s["url"].startswith(("http://", "https://")), \
                f"недопустимый URL: {s['url']}"

    def test_обязательные_поля(self) -> None:
        """Каждая станция имеет name и url."""
        stations = radio_mod.load_stations(ROOT)
        for s in stations:
            assert s.get("name"), f"станция без имени: {s}"
            assert s.get("url"), f"станция без URL: {s}"


# ------------------------------------------------------------ пинг


class _PingHandler(BaseHTTPRequestHandler):
    """HTTP-сервер для тестов пинга.

    Пути подобраны так, чтобы методы отвечали по-разному — иначе
    проверка фолбэка вырождается: `/405` на HEAD и 200 на GET не
    отличить от «фолбэка не было, HEAD просто ответил 200».

    `/head405` — HEAD отвечает 405 (сервер не умеет HEAD), GET отдаёт
    живой поток. Станция обязана оказаться online только если пинг
    действительно повторил запрос методом GET.
    `/hang` — оба метода молчат: проверяем, что таймаут ограничивает
    ожидание. Если бы HEAD отвечал мгновенно, до GET дело не дошло бы
    и тест прошёл бы вхолостую.
    """

    def _ok(self, with_body: bool) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", "1024")
        self.end_headers()
        if with_body:
            self.wfile.write(b"\x00" * 1024)

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path == "/hang":
            time.sleep(30)
        elif self.path in ("/head405", "/both405"):
            # 405 на обоих методах: повторный проход ничего не спасёт.
            self.send_response(405)
            self.end_headers()
        elif self.path == "/404":
            self.send_response(404)
            self.end_headers()
        else:
            self._ok(with_body=False)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/hang":
            time.sleep(30)
        elif self.path == "/404":
            self.send_response(404)
            self.end_headers()
        elif self.path == "/both405":
            self.send_response(405)
            self.end_headers()
        else:
            self._ok(with_body=True)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def ping_server() -> Any:
    """Локальный HTTP-сервер для тестов пинга."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PingHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestPing:
    """Проверка доступности станций."""

    def test_живой_сервер_online(self, ping_server: int) -> None:
        """Ответ 200 — станция жива."""
        result = radio_mod.ping(f"http://127.0.0.1:{ping_server}/live", timeout=2.0)
        assert result["ok"] is True
        assert result["ms"] >= 0

    def test_404_offline(self, ping_server: int) -> None:
        """404 — путь не существует, станция мертва."""
        result = radio_mod.ping(f"http://127.0.0.1:{ping_server}/404", timeout=2.0)
        assert result["ok"] is False

    def test_405_head_fallback_get(self, ping_server: int) -> None:
        """HEAD отвечает 405, GET отдаёт поток — станция обязана быть online.

        Тест кусающий: если убрать фолбэк HEAD→GET, пинг вернёт offline
        по коду 405, хотя станция живая. Именно так ведут себя Icecast на
        нестандартных портах и часть CDN.
        """
        result = radio_mod.ping(f"http://127.0.0.1:{ping_server}/head405", timeout=2.0)
        assert result["ok"] is True, "фолбэк HEAD→GET не сработал"
        assert result["status"] == 200

    def test_405_на_обоих_методах_offline(self, ping_server: int) -> None:
        """405 на HEAD и на GET — станция всё равно недоступна.

        Обратная сторона фолбэка: повторный проход не должен объявлять
        мёртвую станцию живой «по дороге».
        """
        result = radio_mod.ping(f"http://127.0.0.1:{ping_server}/both405", timeout=2.0)
        assert result["ok"] is False

    def test_закрытый_порт_offline(self) -> None:
        """Закрытый порт — станция недоступна."""
        # Находим свободный порт и закрываем его
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        result = radio_mod.ping(f"http://127.0.0.1:{port}/", timeout=1.0)
        assert result["ok"] is False
        assert "error" in result

    def test_таймаут(self, ping_server: int) -> None:
        """Сервер принял соединение и молчит — пинг обязан сдаться по таймауту.

        Кусающий по времени: сервер спит 30 секунд на обоих методах, поэтому
        если `timeout` перестанет уходить в `urlopen`, тест провалится по
        `elapsed`, а не молча пройдёт. Порог 5 секунд при двух проходах
        (HEAD, затем GET) и таймауте 0.5 секунды на каждый — щедрый запас,
        но всё же меньше тридцатисекундного сна.
        """
        t0 = time.monotonic()
        result = radio_mod.ping(f"http://127.0.0.1:{ping_server}/hang", timeout=0.5)
        elapsed = time.monotonic() - t0
        assert result["ok"] is False, "молчащий сервер не должен считаться живым"
        assert elapsed < 5.0, f"пинг ждал {elapsed:.1f}с — таймаут не сработал"
        assert "error" in result, "в отказе должно быть чему-то объяснение"


# ------------------------------------------------------------ RadioBook


class TestRadioBook:
    """Кэш пинга и фоновая проверка."""

    def test_snapshot_пустой_без_пинга(self, tmp_path: Path) -> None:
        """Снимок без проверки — пустые статусы."""
        book = radio_mod.RadioBook(tmp_path)
        snap = book.snapshot()
        assert snap["stations"] == []
        assert snap["statuses"] == {}
        assert snap["pinging"] is False

    def test_start_ping_запускается(self, tmp_path: Path) -> None:
        """start_ping возвращает True при первом запуске."""
        book = radio_mod.RadioBook(tmp_path)
        assert book.start_ping() is True
        # Ждём завершения
        deadline = time.monotonic() + 5
        while book.snapshot()["pinging"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert book.snapshot()["pinging"] is False

    def test_start_ping_повторный_отклонён(self, tmp_path: Path) -> None:
        """Повторный start_ping во время проверки возвращает False."""
        book = radio_mod.RadioBook(tmp_path)
        assert book.start_ping() is True
        # Сразу второй запуск — должен быть отклонён
        assert book.start_ping() is False
        # Ждём завершения
        deadline = time.monotonic() + 5
        while book.snapshot()["pinging"] and time.monotonic() < deadline:
            time.sleep(0.05)


# ------------------------------------------------------------ сервер


class TestRadioAPI:
    """Маршруты /api/radio и /api/radio/ping."""

    @pytest.fixture()
    def live(self, tmp_path: Path) -> Any:
        """Сервер с тестовыми станциями."""
        from hub.server import ApiServer, Handler
        from hub.store import Store
        from hub.worker import Worker

        (tmp_path / "config").mkdir(parents=True)
        (tmp_path / "music").mkdir()
        stations = [
            {"name": "Test Live", "url": "http://127.0.0.1:1/live"},
            {"name": "Test 404", "url": "http://127.0.0.1:1/404"},
        ]
        (tmp_path / "music" / "stations.json").write_text(
            json.dumps(stations), encoding="utf-8")

        store = Store(tmp_path)
        worker = Worker(tmp_path, store)
        api = ApiServer(tmp_path, worker)
        handler = type("BoundHandler", (Handler,), {"api": api})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield port, tmp_path
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            store.close()

    def _get(self, port: int, path: str) -> dict[str, Any]:
        """GET-запрос к тестовому серверу."""
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            headers={"Host": f"127.0.0.1:{port}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    def _post(self, port: int, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST-запрос к тестовому серверу."""
        import urllib.request
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers={
                "Host": f"127.0.0.1:{port}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    def test_get_api_radio(self, live: Any) -> None:
        """GET /api/radio возвращает станции и статусы."""
        port, _ = live
        result = self._get(port, "/api/radio")
        assert "stations" in result
        assert "statuses" in result
        assert "pinging" in result
        assert len(result["stations"]) == 2

    def test_post_api_radio_ping(self, live: Any) -> None:
        """POST /api/radio/ping запускает проверку."""
        port, _ = live
        result = self._post(port, "/api/radio/ping", {})
        assert result["ok"] is True
        assert result["started"] is True
        # Ждём завершения пинга
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            snap = self._get(port, "/api/radio")
            if not snap["pinging"]:
                break
            time.sleep(0.1)
        snap = self._get(port, "/api/radio")
        assert snap["pinging"] is False
        # Статусы должны появиться
        assert len(snap["statuses"]) == 2


# ------------------------------------------------------------ UI


class TestRadioUI:
    """Вкладка радио в интерфейсе."""

    def test_вкладка_радио_есть(self) -> None:
        """Кнопка вкладки и секция существуют в разметке."""
        from hub.ui import UI_HTML
        assert 'data-p="radio"' in UI_HTML
        assert 'id="p-radio"' in UI_HTML

    def test_функции_радио_объявлены(self) -> None:
        """Все функции радио объявлены в скрипте."""
        from hub.ui import UI_HTML
        for func in ("loadRadio", "renderRadio", "radioPick", "radioToggle",
                     "radioStop", "radioNext", "radioVol", "radioPing"):
            assert f"function {func}" in UI_HTML, f"функция {func} не найдена"

    def test_радио_вызывается_из_ltab(self) -> None:
        """ltab('radio') загружает станции."""
        from hub.ui import UI_HTML
        assert "if (name === 'radio') loadRadio();" in UI_HTML


# ------------------------------------------------------------ CLI


class TestZradioCLI:
    """CLI-клиент радио."""

    def test_импорт_без_запуска(self) -> None:
        """Модуль импортируется без запуска окна и плеера."""
        assert hasattr(zradio, "RadioApp")
        assert hasattr(zradio, "Player")

    def test_resolve_по_номеру(self) -> None:
        """Поиск станции по номеру."""
        app = zradio.RadioApp.__new__(zradio.RadioApp)
        app.stations = [
            {"name": "Station A", "url": "http://a"},
            {"name": "Station B", "url": "http://b"},
        ]
        assert app._resolve("1") == 0
        assert app._resolve("2") == 1
        assert app._resolve("3") is None

    def test_resolve_по_имени(self) -> None:
        """Поиск станции по части имени."""
        app = zradio.RadioApp.__new__(zradio.RadioApp)
        app.stations = [
            {"name": "Nightride FM", "url": "http://a"},
            {"name": "Radio Record", "url": "http://b"},
        ]
        assert app._resolve("night") == 0
        assert app._resolve("record") == 1
        assert app._resolve("zzz") is None

    def test_ps_скрипт_содержит_doevents(self) -> None:
        """Без DoEvents плеер висит в Transitioning."""
        assert "DoEvents" in zradio.PS_PLAYER
        assert "WMPlayer.OCX" in zradio.PS_PLAYER

    def test_ps_скрипт_читает_stdin(self) -> None:
        """Плеер должен читать команды из stdin."""
        assert "ReadLine" in zradio.PS_PLAYER
        assert "ConcurrentQueue" in zradio.PS_PLAYER
