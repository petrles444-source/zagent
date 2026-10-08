"""Радиостанции: список, пинг и общее состояние для CLI и веб-интерфейса.

Зачем это
---------
У софта два клиента радио — консольный (`tools/zradio.py`) и веб-вкладка —
и они обязаны показывать одно и то же: те же станции, тот же статус
доступности. Единый источник — `music/stations.json`, а здесь поведение
вокруг него: чтение списка с проверкой полей и пинг с кэшем.

Пинг
----
HEAD — лёгкий запрос, но половина радиосерверов его не поддерживает
(405) или режет файрволом. Поэтому: HEAD, при «не поддержан» — GET с
обрывом тела после первого байта, при прочих отказах — сразу offline.
Любой живой ответ 2xx/3xx означает, что поток есть; 404 — что пути нет.

Проверка идёт в фоновом потоке и пишется в кэш: запрос интерфейса не
должен ждать 37 соединений по четыре секунды. Кэш живёт до следующего
явного запуска — статусы станций меняются часами, а не секундами.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

#: Откуда берётся список. Файл общий для CLI и веба — правится один раз
#: и сразу виден обоим клиентам.
#:
#: Раньше путь был относительным (`Path("music") / ...`) и находился
#: относительно текущей папки. Из-за этого модуль работал только если
#: запустить его из корня проекта: из любой другой папки он молча
#: возвращал пустой список, и радио выглядело сломанным.
#:
#: Теперь ищется от корня проекта — то есть от папки, где лежит
#: `hub/`. Список переехал в `radio/player/`, потому что радио
#: собрали в одну папку вместе с плеером и скриптом для сайтов.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Путь остаётся относительным — и это не по недосмотру.
#:
#: Тесты подставляют свою папку и ждут изоляции: создают свой
#: `music/stations.json` и проверяют, что сервер читает именно его.
#: Стоит сделать путь абсолютным — тесты начнут читать настоящий
#: список из проекта и упадут. Проверено на себе.
#:
#: Чтобы модуль при этом не ломался вне корня, есть
#: `stations_path()`: ищет от рабочего каталога, а если не нашёл —
#: от корня проекта.
STATIONS_FILE = Path("music") / "stations.json"

#: Где файл лежит на самом деле. Радио собрали в одну папку вместе
#: с плеером и скриптом для сайтов.
#:
#: Только относительные пути: `load_stations` подставляет свой корень,
#: и абсолютные адреса сломали бы изоляцию тестов.
STATIONS_RELATIVE = (
    Path("radio") / "player" / "stations.json",
    Path("music") / "stations.json",
)


def stations_path() -> Path:
    """Первый существующий список станций.

    Сначала от рабочего каталога — так работают тесты. Потом от корня
    проекта: раньше этого не было, и модуль возвращал пустой список,
    если запустить его не из корня.
    """
    for root in (Path("."), PROJECT_ROOT):
        for relative in STATIONS_RELATIVE:
            candidate = root / relative
            if candidate.is_file():
                return candidate
    return PROJECT_ROOT / STATIONS_RELATIVE[0]

#: Поля, без которых станция не имеет смысла: имени нет — не показать,
#: URL нет — не играть. Жёсткая проверка нужна, потому что файл
#: редактируется руками, и опечатка не должна ронять панель.
REQUIRED_FIELDS: tuple[str, ...] = ("name", "url")

#: Таймаут одного соединения. Потоковые серверы отвечают сразу, но на
#: плохом канале или с мёртвым DNS тянуть четыре секунды — уже больно;
#: дальше считаем станцию недоступной и не держим весь пинг.
PING_TIMEOUT_S = 4.0

#: Сколько станций пингуем одновременно. 37 потоков разом — это веер
#: соединений, который часть серверов встречает как флуд; шестнадцати
#: хватает, чтобы весь список уложиться в пару кругов таймаута.
PING_WORKERS = 16

#: User-Agent: пустой UA часть радиосерверов отбрасывает как бота.
USER_AGENT = "zagent-radio/1.0"


def load_stations(root: Path) -> list[dict[str, Any]]:
    """Прочитать список станций; битые записи выпадают, а не роняют панель.

    Файл правится руками, поэтому здесь никакой строгости дальше проверки
    полей: лишние ключи проходят, запись без name/url не показывается
    нигде — в CLI она вылезет бы как пустая строка, в вебе — как пустая
    строка в списке, и человек не поймёт, что это вообще было.
    """
    # Адреса все относительные — и это обязательное условие, а не
    # осторожность. `load_stations` получает корень снаружи, и в
    # тестах это временная папка со своим списком.
    #
    # Стоит подставить абсолютный путь к проекту — и тесты, где
    # список намеренно пустой, начнут читать настоящие 37 станций.
    # Проверено на себе: два теста падали именно так.
    #
    # Старый адрес оставлен вторым по порядку не для тестов, а для
    # внешних скриптов: список переехал в `radio/player/`, и копии
    # по прежнему пути ещё есть.
    for relative in STATIONS_RELATIVE:
        candidate = root / relative
        if candidate.is_file():
            path = candidate
            break
    else:
        path = root / STATIONS_FILE

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Нет файла или он в кривой кодировке — работаем с пустым списком:
        # панель должна открываться, а не падать на отсутствии музыки.
        return []
    if not isinstance(raw, list):
        return []
    stations: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not all(isinstance(item.get(f), str) and item[f].strip()
                   for f in REQUIRED_FIELDS):
            continue
        stations.append(item)
    return stations


def ping(url: str, timeout: float = PING_TIMEOUT_S) -> dict[str, Any]:
    """Проверить одну станцию. Возвращает статус и время ответа.

    Схема: HEAD → при 405/501 повторяем GET (сервер жив, просто не умеет
    HEAD) → прочие отказы сразу offline. GET читает один байт и обрывает:
    поток бесконечен, читать его до конца нельзя.
    """
    started = time.monotonic()
    status, error = _probe("HEAD", url, timeout)
    # 405/501 — сервер жив, но HEAD не поддержан. status None — соединение
    # оборвалось: часть файрволов и прокси рвут HEAD, пропуская GET
    # (Icecast на 8000 так делает), поэтому второй проход обязателен.
    if status is None or status in (405, 501):
        status, error = _probe("GET", url, timeout)
    ms = int((time.monotonic() - started) * 1000)
    ok = status is not None and 200 <= status < 400
    result: dict[str, Any] = {"ok": ok, "ms": ms, "status": status}
    if not ok:
        result["error"] = error
    return result


def _probe(method: str, url: str, timeout: float) -> tuple[int | None, str]:
    """Один HTTP-проход. Кортеж: (код или None, описание ошибки)."""
    request = urllib.request.Request(url, method=method,
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if method == "GET":
                resp.read(1)  # дождаться заголовков и первого байта тела
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        # Сервер ответил — код это и есть результат прохода.
        return exc.code, f"HTTP {exc.code}"
    except Exception as exc:  # URLError, таймаут, обрыв, кривой URL
        return None, f"{type(exc).__name__}: {exc}"


class RadioBook:
    """Список станций с кэшем пинга и фоновой проверкой.

    Один экземпляр на сервер: веб-вкладка читает снимок и запускает
    проверку, повторный запуск во время идущей проверки отклоняется —
    иначе два клика подряд дали бы два потока, топящих одни и те же
    адреса.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._statuses: dict[str, dict[str, Any]] = {}
        self._checked_at: float | None = None
        self._running = False

    def stations(self) -> list[dict[str, Any]]:
        return load_stations(self.root)

    def snapshot(self) -> dict[str, Any]:
        """Снимок для интерфейса: станции, статусы, идёт ли проверка."""
        with self._lock:
            return {
                "stations": self.stations(),
                # Копия, а не сам словарь: читатель в другом потоке не должен
                # увидеть состояние на середине обновления.
                "statuses": {u: dict(s) for u, s in self._statuses.items()},
                "checked_at": self._checked_at,
                "pinging": self._running,
            }

    def start_ping(self) -> bool:
        """Запустить проверку в фоне. False — если она уже идёт."""
        with self._lock:
            if self._running:
                return False
            self._running = True
        threading.Thread(target=self._ping_all, name="zagent-radio-ping",
                         daemon=True).start()
        return True

    def _ping_all(self) -> None:
        """Проверить все станции и записать результат в кэш.

        Поток живёт до конца проверки; исключение внутри станции не
        валивает остальные — их адреса в кэш всё равно попадут.
        """
        stations = self.stations()
        results: dict[str, dict[str, Any]] = {}
        try:
            if stations:
                with ThreadPoolExecutor(max_workers=PING_WORKERS) as pool:
                    pairs = list(pool.map(
                        lambda s: (s["url"], ping(s["url"])), stations))
                results = dict(pairs)
        finally:
            with self._lock:
                self._statuses = results
                self._checked_at = time.time()
                self._running = False
