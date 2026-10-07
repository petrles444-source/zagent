"""HTTP-сервер на стандартной библиотеке: API агента + SSE для событий.

Отдельно от hub/web.py, который остаётся старым интерфейсом: этот сервер
обслуживает фонового воркера, поэтому живёт дольше запроса и умеет
отдавать поток событий.

Маршруты:
    GET  /                     панель
    GET  /api/state            состояние реестра, очереди и настроек
    GET  /api/events           SSE-поток событий (?since=<id>&task=<id>)
    POST /api/scan             пересобрать каталог шлюзов
    POST /api/ping             пинг одной модели или всех
    POST /api/sanity           проверка адекватности
    POST /api/ask              одиночный вопрос через failover
    POST /api/mode             режим auto / manual / chain
    POST /api/config           уровни доступа, автономия, бюджет
    POST /api/tasks            поставить задачу в очередь
    GET  /api/tasks            список задач
    POST /api/tasks/answer     ответить на вопрос агента
    POST /api/tasks/cancel     отменить задачу
    POST /api/pause            пауза / продолжение
    GET  /api/shot             снимок экрана как data-URL
"""

from __future__ import annotations

import gzip
import hashlib
import json
import queue
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from hub import blackbox
from hub.config import (
    ConfigError,
    build_settings,
    edit_gateway_models,
    edit_secret,
)
from hub.failover import AutoCaller, FailoverError
from hub.registry import collect, probe_models
from hub.regions import RegionBook, summarize as region_summary
from hub.report import build_snapshot, render_legend
from hub.sanity import build_probe_prompt, evaluate
from hub.tools import capture_screen, image_to_data_url
from hub.tiers import edit_model
from hub.ui import UI_HTML
from hub.worker import Worker

HOST = "127.0.0.1"
PORT = 8783

#: Как часто SSE отдаёт пустой keep-alive, чтобы прокси не рвали соединение.
KEEPALIVE_S = 15.0

#: Сколько событий копить на подписчика, прежде чем считать его отставшим.
SUBSCRIBER_BACKLOG = 500


class ApiServer:
    """Держит воркер и отдаёт его состояние."""

    def __init__(self, root: Path | None = None, worker: Worker | None = None) -> None:
        self.root = root or Path(__file__).resolve().parent.parent
        self.worker = worker or Worker(self.root)

    def start(self) -> None:
        self.worker.start()
        # Основной цикл воркера — отдельный поток, чтобы HTTP-запросы
        # не ждали выполнения задачи.
        threading.Thread(target=self.worker.loop_forever, name="zagent-queue",
                         daemon=True).start()


#: Допустимый вид Origin без заголовка Host: точный loopback с необязательным
#: портом и ничего больше. Хвост вроде `[::1]:8783.evil` под правило не
#: подходит, а `urlparse` его hostname всё равно отдал бы как `::1`.
_LOOPBACK_NETLOC = re.compile(
    r"^(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?$",
    re.IGNORECASE,
)

#: Сжимать только то, где есть что сжимать. Порог — килобайт: короткие
#: ответы («ok», ошибки в пару строк) ужимаются почти в ноль, но хэш и
#: заголовок на них стоят дороже выгоды. Страница интерфейса и `/api/state`
#: — десятки и сотни килобайт, там gzip даёт пяти-десятикратную экономию
#: на каждом опросе.
GZIP_MIN_BYTES = 1024


def _in_session(event: dict[str, Any], session_id: str) -> bool:
    """Событие относится к этой сессии.

    Сессия принадлежит папке, а не задаче: у события может быть `session_id`,
    а может не быть вовсе (пинги, состояние моделей). Такие события показываем
    всегда — иначе вкладка не видела бы изменения, пока в ней идёт задача.
    """
    got = event.get("session_id")
    return not got or str(got) == session_id


class Handler(BaseHTTPRequestHandler):
    server_version = "zagent"
    api: ApiServer = None  # type: ignore[assignment]

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # тихий режим

    def handle_one_request(self) -> None:
        """Обёртка: оборванное соединение — обычное дело, не падение.

        Клиент закрывает вкладку во время SSE-потока, и http.server бросает
        ConnectionAbortedError из readline. Это не ошибка сервера, поэтому
        гасим её здесь, а не пишем трейсбек в консоль.
        """
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError):
            self.close_connection = True

    def _reply(self, body: bytes, ctype: str, status: int = 200) -> None:
        """Отдать тело с ETag, сжатием и 304 на повтор (Волна 3 п.11).

        Интерфейс раз в секунду опрашивает `/api/state` (состояние всех
        моделей, задач и журнал) и раз за сессию грузит страницу целиком.
        Без этой функции каждый раз по сети едут одни и те же байты. Теперь:

        * клиент с `Accept-Encoding: gzip` (все браузеры) получает сжатый
          JSON — обычно в 5–10 раз меньше;
        * если `If-None-Match` совпал с нашим тегом, уходит один статус
          304 и ни байта тела: клиент пользуется своей копией;
        * `Cache-Control: no-cache` — не «не кэшировать», а «перед
          использованием спроси меня»: данные живые, но спрашивать дёшево.

        ETag считается по исходному телу, а для сжатого варианта получает
        суффикс `-gzip`. Без разделения прокси-кэш, отдавший gzip по
        несжатому тегу, ломает кэш классическим образом — клиент сверяет
        тег сжатого тела с несжатым и либо вечно промахивается, либо
        подкладывает не тот размер.

        304 отдаём только на успех (status 200): условный повтор ошибки
        или ответа на изменение данных смысла не имеет.
        """
        sha = hashlib.sha256(body).hexdigest()[:32]
        raw_etag = f'"{sha}"'
        gzip_etag = f'"{sha}-gzip"'
        offered = {tag.strip()
                   for tag in (self.headers.get("If-None-Match") or "").split(",")
                   if tag.strip()}

        if status == 200:
            for tag in (raw_etag, gzip_etag):
                if tag in offered:
                    # Эхо того тега, что прислал клиент: он обновит своё
                    # хранилище тем, что мы подтвердили, и следующий раз
                    # снова придёт с ним же.
                    self.send_response(304)
                    self.send_header("ETag", tag)
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    return

        compressed = ("gzip" in (self.headers.get("Accept-Encoding") or "")
                      and len(body) >= GZIP_MIN_BYTES)
        payload = gzip.compress(body, 6) if compressed else body
        etag = gzip_etag if compressed else raw_etag

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if compressed:
            self.send_header("Content-Encoding", "gzip")
            # Ответ зависит от заголовка клиента: без Vary кэш смешал бы
            # сжатую и несжатую версии для разных браузеров.
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._reply(body, "application/json; charset=utf-8", status)

    def _html(self, text: str) -> None:
        self._reply(text.encode("utf-8"), "text/html; charset=utf-8")

    def _download(self, text: str, filename: str) -> None:
        """Отдать файл на скачивание: браузер сохранит его, а не откроет.

        Имя файла приходит от нас же (номер задачи), посторонние строки в
        заголовок не попадают. Тип `application/x-ndjson` — по одной записи
        на строку: файл открывается редактором и граблится grep'ом.
        """
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: Exception, status: int = 500) -> None:
        """Ошибка клиенту — без трейсбека.

        Трейсбек уходит в консоль, а не в ответ: он раскрывает абсолютные
        пути и устройство кода любой вкладке браузера. Для локального
        инструмента это терпимо, но незачем отдавать подробности всем,
        кто откроет страницу, — тем более что страница тянет шрифты с CDN.
        """
        traceback.print_exc()
        self._json({
            "error": " ".join(str(exc).split())[:400],
            "type": type(exc).__name__,
        }, status)

    def _reject(self, reason: str) -> None:
        """Ответ с отказом до чтения тела запроса.

        Тело при отказе не читается намеренно: иначе кросс-доменный запрос
        останется в буфере сокета и следующий запрос по тому же соединению
        будет разобран как продолжение чужих данных.
        """
        body = json.dumps({"error": reason}, ensure_ascii=False).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _body(self) -> dict[str, Any]:
        # Разбираем JSON только при application/json. Иначе любой `text/plain`
        # считался бы данными, а такие запросы отправляются кросс-доменно без
        # preflight — это и есть путь, которым посторонняя страница дёргала бы
        # все POST-эндпоинты.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        if ctype and ctype != "application/json":
            raise ValueError(f"Ожидался application/json, пришёл {ctype}")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _same_origin(self) -> bool:
        """Запрос пришёл со страницы, открытой в этом же браузере.

        Сервер не имеет аутентификации и слушает только 127.0.0.1, поэтому
        защита строится на заголовке Origin: запрос без него — это curl,
        тест или сам интерфейс, запрос с чужим — посторонняя страница.

        Сравнение идёт с адресом, на котором сервер себя видит (Host), а не
        со списком допустимых хостов. Проверка одного `hostname` была бы дырой:
        `urlparse("http://[::1]:8783.evil").hostname` возвращает `::1`, и
        поддельный адрес проходил бы как свой.
        """
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True

        # Origin вида `null` приходит от file:// и из песочницы — пропускать
        # его нельзя: это тоже внешний источник.
        parsed = urlparse(origin)
        if not parsed.netloc:
            return False

        host = (self.headers.get("Host") or "").strip()
        if host:
            return parsed.netloc.lower() == host.lower()

        # Host отсутствует только в нестандартных клиентах. Проверяем форму
        # адреса целиком, а не только hostname: `urlparse` вытащит из
        # `[::1]:8783.evil` ровно `::1`, и подделка прошла бы как свой адрес.
        return _LOOPBACK_NETLOC.match(parsed.netloc) is not None

    def _host_is_local(self) -> bool:
        """Страница пришла на этот же процесс, а не на чужой хост.

        Одной проверки `Origin == Host` недостаточно: при DNS-rebinding
        браузер ходит на `evil.test`, но IP этого имени уже указывает на
        127.0.0.1, и подставленные `Host` с `Origin` совпадают — оба
        `evil.test`. Совпадение честное, а запрос-то чужой. Лечится это
        проверкой того, что адресат — loopback: настоящий интерфейс на
        чужой хост не открывается, сервер и так слушает только 127.0.0.1.
        """
        host = (self.headers.get("Host") or "").strip()
        if not host:
            # HTTP/1.0 и отдельные тесты присылают запрос без Host. Такой
            # запрос не может быть перехвачен переопределением DNS: браузер
            # заголовок всегда ставит.
            return True
        return _LOOPBACK_NETLOC.match(host) is not None

    def _own_request(self) -> bool:
        """Запрос свой: и адресат наш, и страница наша."""
        return self._host_is_local() and self._same_origin()

    def _write_event(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))

    # ----------------------------------------------------------------- POST

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        # Сервер слушает только 127.0.0.1 и без аутентификации, поэтому любой
        # POST обязан быть своим. Без проверки любая открытая вкладка в
        # браузере отправляла бы `text/plain`-fetch кросс-доменно: такой
        # запрос не проходит preflight и доходит до обработчика, то есть
        # посторонняя страница могла бы читать файлы и запускать задачи.
        # Host проверяется отдельно от Origin: при DNS-rebinding оба
        # заголовка чужие, но друг с другом совпадают.
        if not (self._host_is_local() and self._same_origin()):
            self._reject("Запрос с чужого адреса отклонён")
            return

        try:
            body = self._body()
        except ValueError as exc:
            self._reject(str(exc))
            return
        try:
            routes = {
                "/api/scan": self._scan,
                "/api/ping": self._ping,
                # Состояние автоматической проверки моделей: что проверено,
                # когда и что ожило. Отдельный маршрут, а не часть /api/state,
                # потому что он меняется раз в 12 минут и в состоянии только
                # мешал бы.
                "/api/ping/status": self._ping_status,
                "/api/sanity": self._sanity,
                "/api/ask": self._ask,
                "/api/mode": self._mode,
                "/api/config": self._config,
                "/api/tasks": self._enqueue,
                "/api/tasks/answer": self._answer,
                "/api/tasks/cancel": self._cancel,
                "/api/pause": self._pause,
                "/api/shot": self._shot,
                "/api/connect": self._connect,
                "/api/workspaces": self._workspaces,
                "/api/sessions": self._sessions,
                "/api/region": self._region,
                "/api/geo": self._region,
                "/api/files": self._files,
                "/api/permissions": self._permissions,
                # Вкладка «Настройки»: читает поля секретов (без значений)
                # и пишет ключи/модели в конфигурацию.
                "/api/settings": self._settings,
                "/api/keys": self._keys,
                "/api/models": self._models,
            }
            handler = routes.get(path)
            if handler is None:
                return self._json({"error": "not found"}, 404)
            return self._json(handler(body))
        except Exception as exc:
            traceback.print_exc()
            return self._error(exc)

    # ------------------------------------------------------------- обработчики

    def _scan(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.api.worker.scan()

    def _settings(self, body: dict[str, Any]) -> dict[str, Any]:
        """Что показывает вкладка «Настройки»: поля и счётчики, без значений."""
        return build_settings(self.api.worker.root)

    def _keys(self, body: dict[str, Any]) -> dict[str, Any]:
        """Добавить/заменить/удалить ключи одного поля secrets.local.json.

        После успешной записи каталог пересобирается: `ring()` перечитывает
        список ключей сам, но модели шлюза попадут в реестр только вместе
        с новым collect() — первый ключ открывает шлюзу и его модели.
        """
        worker = self.api.worker
        single = body.get("single")
        try:
            result = edit_secret(
                body.get("name") or body.get("gateway"),
                body.get("keys"),
                action=str(body.get("action") or "add"),
                single=single if isinstance(single, bool) else None,
                root=worker.root,
            )
        except ConfigError as exc:
            return {"ok": False, "error": str(exc)}
        if result.get("ok"):
            result["scan"] = worker.scan()
        return result

    def _models(self, body: dict[str, Any]) -> dict[str, Any]:
        """Добавить/убрать модель: tiers.json (ранг) + free_models (каталог).

        Правятся оба файла сразу — иначе хвост: модель есть в каталоге, но
        без паспорта, или паспорт есть, а селектор её не видит.
        """
        worker = self.api.worker
        action = str(body.get("action") or "add")
        gateway = body.get("gateway")
        model = body.get("model")
        try:
            if action == "add":
                spec = edit_model(
                    gateway, model,
                    action="add",
                    tier=body.get("tier"),
                    notes=str(body.get("notes") or ""),
                    root=worker.root,
                )
                try:
                    catalog = edit_gateway_models(
                        gateway, model, action="add", root=worker.root
                    )
                except ConfigError:
                    # Шлюза не оказалось — откатываем паспорт, чтобы файлы
                    # не разъехались.
                    if spec.get("changed") == "added":
                        edit_model(gateway, model, action="remove", root=worker.root)
                    raise
                ok = bool(spec.get("ok")) and bool(catalog.get("ok"))
            else:
                spec = edit_model(gateway, model, action="remove", root=worker.root)
                catalog = edit_gateway_models(
                    gateway, model, action="remove", root=worker.root
                )
                # Убрать достаточно в одном из двух: модель может быть только
                # в каталоге (живая) или только в паспорте (ручная).
                ok = bool(spec.get("ok")) or bool(catalog.get("ok"))
        except ConfigError as exc:
            return {"ok": False, "error": str(exc)}

        result: dict[str, Any] = {
            "ok": ok, "action": action, "gateway": str(gateway or ""),
            "model": str(model or ""), "spec": spec, "catalog": catalog,
        }
        if ok:
            result["scan"] = worker.scan()
        return result

    def _ping(self, body: dict[str, Any]) -> dict[str, Any]:
        # ref не задан — пингуется весь реестр. Раньше интерфейс слал ref
        # всегда, и «Пинг» проверял одну модель вместо всех.
        ref = body.get("ref") or None
        # Список ‒ для кнопки «Пинг недоступных»: без него сервер проверял весь реестр.
        refs = [str(x) for x in (body.get("refs") or []) if x] or None
        result = self.api.worker.ping(ref, refs=refs)
        if not result.get("ok", True):
            return result
        return {"ok": True, "pinged": result.get("pinged", 0),
                "ref": ref or "все модели"}

    def _ping_status(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.api.worker.ping_status()

    def _sanity(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.api.worker.sanity(body.get("ref"), body.get("lang", "ru"))

    def _ask(self, body: dict[str, Any]) -> dict[str, Any]:
        text = str(body.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "пустой запрос"}
        worker = self.api.worker
        if worker.selector is None:
            return {"ok": False, "error": "реестр не загружен"}

        caller = AutoCaller(worker.selector, timeout=120.0)
        try:
            result = _run(worker, caller.ask(
                [{"role": "user", "content": text}],
                max_tokens=int(body.get("max_tokens") or 2000),
                images=body.get("images"),
                include_attempts=True,
            ))
        except FailoverError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "model": result.get("model"),
            "status": result.get("status"),
            "duration_ms": result.get("duration_ms"),
            "tokens_in": result.get("tokens_in"),
            "tokens_out": result.get("tokens_out"),
            "cost": result.get("cost"),
            "answer": str(result.get("text") or result.get("reasoning") or ""),
            "attempts": result.get("attempts") or [],
        }

    def _mode(self, body: dict[str, Any]) -> dict[str, Any]:
        worker = self.api.worker
        mode = str(body.get("mode") or "auto")
        manual = body.get("manual_ref")
        worker.configure(prefer_speed=bool(body.get("prefer_speed")),
                         require_vision=bool(body.get("require_vision")))
        return worker.set_mode(mode, manual_ref=manual)

    def _config(self, body: dict[str, Any]) -> dict[str, Any]:
        # soft_boundary обязан быть в списке: без него переключатель «жёсткая
        # граница» в интерфейсе молча не применялся, а пользователь считал,
        # что агент заперт в папке.
        allowed = {k: v for k, v in body.items()
                   if k in ("access", "autonomy", "escalation", "max_steps",
                            "base_dir", "prefer_speed", "require_vision",
                            "avoid_vpn", "soft_boundary")}
        return self.api.worker.configure(**allowed)

    def _enqueue(self, body: dict[str, Any]) -> dict[str, Any]:
        task = str(body.get("task") or "").strip()
        if not task:
            return {"ok": False, "error": "пустая задача"}
        payload: dict[str, Any] = {}
        if body.get("images"):
            payload["images"] = body["images"]
        if body.get("plan_only"):
            payload["plan_only"] = True
        # Флаги режимов работы: субагенты и веб-поиск. `auto_mode` означает
        # «реши сам»: режим выбирается после постановки задачи, потому что
        # решение зависит от её текста и от числа свободных аккаунтов.
        for flag in ("subagents", "web_research"):
            if body.get(flag):
                payload[flag] = body[flag]
        if body.get("auto_mode"):
            payload["auto_mode"] = True

        # Воркспейс задачи: агент работает только в выбранной папке.
        # Источник правды — активная сессия: она уже знает свою папку. Явный
        # workspace_id из запроса переключает сессию, иначе интерфейс и очередь
        # разошлись бы: задача в одной папке, а переписка в другой.
        worker = self.api.worker
        requested = body.get("workspace_id")
        if requested and str(requested) != worker.workspaces.active_id:
            moved = worker.switch_session(
                worker.store.ensure_session(str(requested))
            )
            if not moved.get("ok"):
                return {"ok": False, "error": moved.get("error") or "сессия не найдена"}

        session_id = worker.store.active_session_id()
        session = worker.store.get_session(session_id) if session_id else None
        workspace_id = str(session["workspace_id"]) if session else worker.workspaces.active_id
        workspace = worker.workspaces.get(workspace_id)
        if workspace is None:
            return {"ok": False, "error": f"Воркспейс не найден: {workspace_id}"}
        if not workspace.exists():
            return {"ok": False, "error": f"Папка воркспейса недоступна: {workspace.path}"}
        payload["workspace_id"] = workspace.id

        return self.api.worker.enqueue(
            task, priority=int(body.get("priority") or 5), payload=payload,
            session_id=session_id,
        )

    def _region(self, body: dict[str, Any]) -> dict[str, Any]:
        """Замер доступности из России: состояние, старт, отмена.

        mode: direct (VPN выключен) или vpn (VPN включён). Один замер не
        стирает другой — сырые пробы хранятся по режимам.
        """
        worker = self.api.worker
        action = str(body.get("action") or "status")

        if action == "status":
            return worker.region_status()
        if action == "measure":
            return worker.measure_region(str(body.get("mode") or ""))
        if action == "reset":
            # Первый позиционныйный параметр RegionBook — это словарь
            # замеров, а не путь к проекту: передаём именованно, иначе
            # reset падал бы с AttributeError на notes.
            worker.regions = RegionBook({}, root=worker.regions.root)
            if worker.selector is not None:
                worker.selector.vpn_only = set()
            return {"ok": True, "summary": region_summary(worker.regions)}
        return {"ok": False, "error": f"неизвестное действие: {action}"}

    def _sessions(self, body: dict[str, Any]) -> dict[str, Any]:
        """Сессии: список, создание, переключение, переименование, удаление."""
        worker = self.api.worker
        action = str(body.get("action") or "list")

        if action == "list":
            return worker.sessions()

        if action == "history":
            session_id = body.get("session_id") or worker.store.active_session_id()
            if not session_id:
                return {"ok": False, "error": "нет активной сессии"}
            return worker.session_history(str(session_id))

        if action == "new":
            return worker.new_session(
                str(body.get("name") or ""),
                workspace_id=body.get("workspace_id"),
            )

        if action == "switch":
            session_id = body.get("session_id")
            if not session_id:
                return {"ok": False, "error": "нужен session_id"}
            return worker.switch_session(str(session_id))

        if action == "rename":
            session_id = body.get("session_id")
            if not session_id:
                return {"ok": False, "error": "нужен session_id"}
            return worker.rename_session(str(session_id), str(body.get("name") or ""))

        if action == "remove":
            session_id = body.get("session_id")
            if not session_id:
                return {"ok": False, "error": "нужен session_id"}
            return worker.remove_session(str(session_id))

        return {"ok": False, "error": f"неизвестное действие: {action}"}

    def _answer(self, body: dict[str, Any]) -> dict[str, Any]:
        task_id = body.get("task_id")
        if task_id is None:
            return {"ok": False, "error": "нужен task_id"}
        return self.api.worker.answer(
            int(task_id), str(body.get("answer") or ""), approve=bool(body.get("approve"))
        )

    def _cancel(self, body: dict[str, Any]) -> dict[str, Any]:
        task_id = body.get("task_id")
        if task_id is None:
            return {"ok": False, "error": "нужен task_id"}
        return self.api.worker.cancel(int(task_id))

    def _pause(self, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("resume"):
            return self.api.worker.resume()
        return self.api.worker.pause()

    def _shot(self, body: dict[str, Any]) -> dict[str, Any]:
        base = Path(self.api.worker.config.base_dir)
        result = capture_screen(base / "screenshots" / "web.png", base=base)
        if not result.ok:
            return {"ok": False, "error": result.error, "needs_user": result.needs_user}
        encoded = image_to_data_url(str(result.data["path"]))
        if not encoded.ok:
            return {"ok": False, "error": encoded.error}
        return {"ok": True, "path": result.data["path"],
                "width": result.data["width"], "height": result.data["height"],
                "data_url": encoded.data}

    # ------------------------------------------------------ подключение моделей

    def _connect(self, body: dict[str, Any]) -> dict[str, Any]:
        """Готовые инструкции: как использовать модели в другом софте."""
        from hub.connect import build_guide, reveal_key

        worker = self.api.worker
        if worker.registry is None:
            return {"ok": False, "error": "реестр не загружен"}

        # Полный ключ — отдельным действием и только для одного шлюза.
        # В общем ответе ключи замаскированы: они попадают в DOM страницы,
        # а страница тянет шрифты с CDN.
        if body.get("reveal_key"):
            return reveal_key(worker.registry, str(body.get("gateway") or ""))

        guide = build_guide(worker.registry)
        target = body.get("target")
        if target:
            block = guide["targets"].get(target)
            if block is None:
                return {"ok": False, "error": f"неизвестная цель: {target}"}
            # connections едем вместе с блоком цели: интерфейс читает оттуда
            # provider id, base URL и ключ каждого шлюза. Без них тот блок
            # показывал пустые base URL и «ключ не задан» для заданных ключей.
            return {"ok": True, "target": target,
                    "connections": guide["connections"], **block}
        return {"ok": True, **guide}

    # ------------------------------------------------------------ воркспейсы

    def _permissions(self, body: dict[str, Any]) -> dict[str, Any]:
        """Запрос на выход за воркспейс: показать или решить."""
        worker = self.api.worker
        action = str(body.get("action") or "list")

        if action == "list":
            return {"ok": True, "permissions": worker.store.pending_permissions()}

        if action == "answer":
            permission_id = body.get("permission_id")
            if permission_id is None:
                return {"ok": False, "error": "нужен permission_id"}
            scope = str(body.get("scope") or "once")
            if scope not in ("once", "always"):
                scope = "once"
            return worker.answer_permission(
                int(permission_id), bool(body.get("allow")), scope=scope
            )

        return {"ok": False, "error": f"неизвестное действие: {action}"}

    def _workspaces(self, body: dict[str, Any]) -> dict[str, Any]:
        manager = self.api.worker.workspaces
        action = str(body.get("action") or "list")

        try:
            if action == "list":
                return {"ok": True, **manager.describe()}
            if action == "activate":
                workspace = manager.activate(str(body.get("id") or ""))
                self.api.worker.configure(
                    base_dir=str(workspace.resolved()),
                    access=workspace.access,
                    autonomy=workspace.autonomy,
                    escalation=workspace.escalation,
                    max_steps=workspace.max_steps,
                )
                # Сессия принадлежит папке, поэтому вместе с папкой переключаем
                # и её: иначе переписка была бы от другой папки.
                self.api.worker.store.set_active_session(
                    self.api.worker.store.ensure_session(workspace.id)
                )
                return {"ok": True, **manager.describe(),
                        "session": self.api.worker.store.active_session_id()}
            if action == "add":
                manager.add(
                    str(body.get("path") or ""),
                    name=body.get("name"),
                    access=int(body.get("access") or 2),
                    autonomy=str(body.get("autonomy") or "normal"),
                    escalation=str(body.get("escalation") or "auto"),
                )
                return {"ok": True, **manager.describe()}
            if action == "create":
                # То же, что add, но папка создаётся, если её нет: выбрали
                # каталог в диалоге, а его ещё нет — отказ читался как
                # «кнопка не работает».
                manager.add(
                    str(body.get("path") or ""),
                    name=body.get("name"),
                    access=int(body.get("access") or 2),
                    autonomy=str(body.get("autonomy") or "normal"),
                    escalation=str(body.get("escalation") or "auto"),
                    create=True,
                )
                return {"ok": True, **manager.describe()}
            if action == "remove":
                worker = self.api.worker
                removed = str(body.get("id") or "")
                manager.remove(removed)
                # Активная сессия удалённой папки больше не годится: её
                # воркспейса не существует, и задачи из неё некуда выполнять.
                active = worker.store.active_session_id()
                record = worker.store.get_session(active) if active else None
                if record and str(record["workspace_id"]) == removed:
                    worker.store.set_active_session(
                        worker.store.ensure_session(manager.active_id)
                    )
                return {"ok": True, **manager.describe(),
                        "session": worker.store.active_session_id()}
            if action == "update":
                fields = {k: v for k, v in body.items()
                          if k in ("name", "access", "autonomy", "escalation",
                                   "max_steps", "protected")}
                manager.update(str(body.get("id") or ""), **fields)
                return {"ok": True, **manager.describe()}
        except Exception as exc:
            return {"ok": False, "error": " ".join(str(exc).split())[:300]}

        return {"ok": False, "error": f"неизвестное действие: {action}"}

    # ------------------------------------------------------------- файлы

    def _files(self, body: dict[str, Any]) -> dict[str, Any]:
        """Просмотр воркспейса: дерево и содержимое файла."""
        base = Path(self.api.worker.config.base_dir).resolve()
        try:
            base.relative_to(Path(self.api.worker.root).resolve())
        except ValueError:
            # Воркспейс снаружи проекта — читаем, но не выходим за base.
            pass

        def guard_path(raw: str) -> Path | None:
            candidate = (base / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
            try:
                candidate.relative_to(base)
            except ValueError:
                return None
            return candidate

        rel = str(body.get("path") or ".")
        target = guard_path(rel)
        if target is None:
            return {"ok": False, "error": "путь вне воркспейса"}
        if not target.exists():
            return {"ok": False, "error": "не найдено"}

        if target.is_file():
            return self._read_view_file(target, base)

        entries = []
        try:
            for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                name = item.name
                if name.startswith(".") and name not in (".gitignore", ".env.example"):
                    continue
                if name in ("__pycache__", "node_modules", ".venv", "venv", ".git"):
                    continue
                kind = "dir" if item.is_dir() else classify_file(name)
                entries.append({
                    "name": name,
                    "type": item.is_dir() and "dir" or kind,
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                })
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True, "kind": "dir",
            "path": str(target.relative_to(base)).replace("\\", "/"),
            "entries": entries,
            # Отдаём абсолютный путь файловой системы: браузер не умеет
            # показывать //server/share и файлы с русскими именами, а агент
            # работает на той же машине. Путь не показывается пользователю.
            "web_root": _as_uri(base),
        }

    def _read_view_file(self, target: Path, base: Path) -> dict[str, Any]:
        """Отдать файл для просмотра: текст, картинку или отказ с причиной.

        Раньше не-текстовый файл возвращал ошибку, и просмотр картинки в
        интерфейсе был невозможен. Теперь картинка отдаётся как data URL,
        а всё остальное честно помечается как «не показать».
        """
        size = target.stat().st_size
        suffix = target.suffix.lower()
        web_root = _as_uri(base)

        if suffix in IMAGE_SUFFIXES:
            if size > 12 * 1024 * 1024:
                return {"ok": False, "error": "картинка больше 12 МБ"}
            import base64 as _b64
            import mimetypes
            mime = mimetypes.guess_type(target.name)[0] or "image/png"
            try:
                data = _b64.b64encode(target.read_bytes()).decode("ascii")
            except OSError as exc:
                return {"ok": False, "error": str(exc)}
            return {
                "ok": True, "kind": "image",
                "path": str(target.relative_to(base)).replace("\\", "/"),
                "mime": mime,
                "data_url": f"data:{mime};base64,{data}",
                "size": size,
            }

        if size > 2 * 1024 * 1024:
            return {
                "ok": True, "kind": "binary",
                "path": str(target.relative_to(base)).replace("\\", "/"),
                "size": size,
                "note": "файл не текстовый, содержимое не показано",
            }

        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return {
                "ok": True, "kind": "binary",
                "path": str(target.relative_to(base)).replace("\\", "/"),
                "size": size,
                "note": "не удалось прочитать как текст (возможно, другая кодировка)",
            }

        language = LANGUAGE_BY_SUFFIX.get(suffix, "")
        return {
            "ok": True, "kind": "file",
            "path": str(target.relative_to(base)).replace("\\", "/"),
            "content": content[:400_000],
            "truncated": len(content) > 400_000,
            "lines": content.count("\n") + 1,
            "size": size,
            "language": language,
            "web_root": web_root,
            "web_url": _as_uri(target),
        }


#: Расширения картинок: их показываем, а не считаем «не текстовым».

    def do_GET(self) -> None:
        # GET отдаёт состояние, список задач и поток событий — аутентификации
        # нет, поэтому защита та же, что у POST. Раньше проверялся только
        # Origin у POST, и любая чужая страница читала `/api/state` целиком:
        # там ошибки с фингерпринтами ключей, счётчики и имена моделей.
        if not self._own_request():
            self._reject("Запрос с чужого адреса отклонён")
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in ("/", "/index.html"):
                return self._html(INDEX_HTML)
            if parsed.path == "/api/state":
                return self._json(self.api.worker.state())
            if parsed.path == "/api/tasks":
                return self._json({"ok": True, "tasks": self.api.worker.store.list_tasks(
                    limit=int(query.get("limit", ["30"])[0]))})
            # Отдельный GET по id: интерфейс иногда хочет открыть конкретную
            # задачу, а списка может быть мало. Без него возвращается 404, хотя
            # задача существует — живой прогон показал, что это бесполезное
            # ограничение для UI.
            if parsed.path.startswith("/api/tasks/"):
                try:
                    task_id_str = parsed.path.rsplit("/", 1)[-1]
                    task_id = int(task_id_str)
                except ValueError:
                    return self._json({"ok": False, "error": "некорректный id задачи"}, 400)
                task = self.api.worker.store.get_task(task_id)
                if task is None:
                    return self._json({"ok": False, "error": "задача не найдена"}, 404)
                return self._json({"ok": True, "task": task})
            if parsed.path == "/api/permissions":
                # Список неотвеченных запросов на выход за воркспейс.
                # Через GET его удобно опрашивать, пока агент ждёт ответа.
                return self._json(self.api.worker.permissions())
            if parsed.path == "/api/settings":
                # Чтение вкладки «Настройки» — это состояние, а не правка,
                # поэтому GET: интерфейс зовёт его при каждом открытии вкладки.
                return self._json(build_settings(self.api.worker.root))
            if parsed.path == "/api/blackbox":
                # Чёрный ящик задачи: трейс (ходы, модели, ошибки) файлом.
                # Скачивание, поэтому отдельный ответ с Content-Disposition,
                # а не обычный JSON в новой вкладке.
                try:
                    task_id = int(query.get("task", ["0"])[0])
                except (TypeError, ValueError):
                    return self._json({"error": "номер задачи не число"}, 400)
                try:
                    text = blackbox.build(
                        self.api.worker.store, task_id, root=self.api.worker.root
                    )
                except blackbox.BlackboxError as exc:
                    return self._json({"error": str(exc)}, 404)
                return self._download(text, blackbox.filename(task_id))
            if parsed.path == "/api/events":
                return self._stream(query)
        except Exception as exc:
            traceback.print_exc()
            return self._error(exc)
        return self._json({"error": "not found"}, 404)

    def _stream(self, query: dict[str, list[str]]) -> None:
        """SSE-поток событий воркера.

        Соединение держится открытым; события приходят из подписки, минуя
        опрос базы, поэтому журнал появляется в интерфейсе сразу.
        """
        since = int(query.get("since", ["0"])[0])
        task_id = query.get("task", [None])[0]
        task_id_int = int(task_id) if task_id else None
        session_id = (query.get("session") or [None])[0]

        # Без указания момента отдавать всю историю бессмысленно: клиент после
        # перезагрузки присылает since=0 и получает до 200 чужих событий, каждое
        # из которых тянет ещё и GET /api/state. Считаем, что «с начала» —
        # это только последние 50: их достаточно, чтобы показать актуальность,
        # и история подгружается по конкретной сессии.
        if since <= 0:
            since = max(0, self.api.worker.store.last_event_id() - 50)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        inbox: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=SUBSCRIBER_BACKLOG)

        def on_event(event: dict[str, Any]) -> None:
            try:
                inbox.put_nowait(event)
            except queue.Full:
                # Подписчик не успевает: лучше потерять событие, чем уронить поток.
                pass

        unsubscribe = self.api.worker.subscribe(on_event)

        # Догружаем то, что уже накоплено до подписки. Сама подписка включается
        # до чтения, и это осознанно: между чтением backlog и включением
        # подписки событие потерялось бы навсегда, а это тише, чем дубль.
        # Дубль убирает клиент — он помнит последний обработанный id.
        backlog = self.api.worker.store.events_since(since, limit=200, task_id=task_id_int)
        if session_id:
            backlog = [e for e in backlog if _in_session(e, str(session_id))]

        try:
            self.wfile.write(b": stream open\n\n")
            self.wfile.flush()
            for event in backlog:
                self._write_event(event)
            self.wfile.flush()

            last_ping = time.time()
            while True:
                try:
                    event = inbox.get(timeout=1.0)
                except queue.Empty:
                    if time.time() - last_ping >= KEEPALIVE_S:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_ping = time.time()
                    continue

                if task_id_int is not None and event.get("task_id") not in (
                    None, task_id_int
                ):
                    continue
                if session_id and not _in_session(event, str(session_id)):
                    continue
                self._write_event(event)
                self.wfile.flush()
                last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # клиент закрыл вкладку — это нормальный сценарий
        finally:
            unsubscribe()


IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico",
}

#: Подсветка в просмотре: суффикс → класс языка для подсветки.
LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".html": "html", ".htm": "html", ".css": "css", ".json": "json",
    ".md": "markdown", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".sql": "sql", ".bat": "bat",
    ".ps1": "powershell", ".sh": "shell", ".txt": "",
}


def classify_file(name: str) -> str:
    """Что показать для файла: картинка, текст или «не открывается»."""
    suffix = Path(name).suffix.lower()
    if Path(name).is_dir():
        return "dir"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in LANGUAGE_BY_SUFFIX:
        return "text"
    # Без известного расширения пытаемся прочитать: текстовые файлы часто
    # называют без расширения (LICENSE, Makefile, README).
    return "text"


def _as_uri(path: Path) -> str:
    """Путь для браузера: file:///C:/... вместо //?/C:/..."""
    try:
        return path.resolve().as_uri()
    except (ValueError, OSError):
        return ""


#: Открываемые ссылки считает hub.tools: оттуда же их берёт агент, а
#: импортировать сервер из агента нельзя — получился бы круг.


def _run(worker: Any, coro: Any) -> Any:
    """Выполнить корутину в loop воркера из потока HTTP-обработчика.

    Loop берётся из переданного воркера, а не из ``Handler.api``: ``api``
    задаётся динамическому подклассу обработчика, и базовый класс про него
    ничего не знает. Из-за этого ``POST /api/ask`` отдавал 500, и агент в
    интерфейсе выглядел сломанным при воркере работающем.
    """
    loop = getattr(worker, "loop", None)
    if loop is None:
        # Корутина не будет выполнена — её надо закрыть, иначе Python
        # предупредит «coroutine was never awaited», а ошибка уйдёт в лог.
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        raise RuntimeError("Воркер не запущен")
    import asyncio

    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=300)


def serve(host: str = HOST, port: int = PORT, root: Path | None = None) -> None:
    """Поднять сервер вместе с воркером."""
    api = ApiServer(root)
    print("Загружаю реестр и поднимаю воркер…", flush=True)
    api.start()
    worker = api.worker
    if worker.last_error:
        print(f"Реестр не собран: {worker.last_error}", flush=True)
    else:
        print(f"Моделей: {len(worker.selector.states) if worker.selector else 0}", flush=True)
    # Автоматическая проверка моделей: без неё состояние устаревает, а
    # модель, ожившая после сброса лимита, остаётся незамеченной до
    # следующего нажатия «Пинг».
    worker.start_background_ping()
    print(f"Открой http://{host}:{port}", flush=True)

    handler = type("BoundHandler", (Handler,), {"api": api})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")
    finally:
        server.server_close()
        worker.stop()


INDEX_HTML = UI_HTML
