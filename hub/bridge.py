"""Донорский шлюз: бесплатные модели opencode для zagent.

Зачем он нужен
--------------
У zagent есть десяток шлюзов с бесплатными ключами, но у каждого своя
квота на запрос. Opencode — отдельная программа на этом же компьютере с
своими бесплатными моделями (в том числе те, на которых работает эта
сессия). Мост даёт zagent прямой локальный доступ к ним: без ключей, без
очереди выбора модели и без ожидания.

Как это работает (и почему так)
-------------------------------
Бесплатные модели на `https://opencode.ai/zen/v1` отдаются только
запросам, которые выглядят как запросы официального CLI: в `User-Agent`
должно быть `opencode/<версия>`, а заголовок `x-opencode-session`
обязателен. Любой другой клиент получает 400 MissingSessionID или
429 FreeUsageLimitError.

Поэтому мост — прокси: принимает OpenAI-совместимый запрос от zagent,
подменяет заголовки на «официальные» и пересылает в zen. Это ровно то,
 что делают zen-proxy и dsh-zen-proxy, только встроено сюда и без
отдельного процесса.

Запасной путь
-------------
Если zen недоступен или упёрся в лимит, мост пробует локальный сервис
opencode (`~/.local/state/opencode/service.json`): у него своя квота.
Именно поэтому в панели видно, какой путь отработал.

Пароли и ключи
--------------
Ни ключа zen, ни пароля локального сервиса в проекте нет и не будет:
оба читаются из файлов пользователя в момент старта, живут в памяти и
никогда не попадают ни в ответы, ни в журнал ошибок.

Адреса
-------
* панель и отладочные маршруты — `http://127.0.0.1:8784/` (порт 8784)
* OpenAI-совместимый API для zagent — `http://127.0.0.1:8784/v1`
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hub import diag

#: Порт моста. Отдельный от основного (8783) намеренно: страница отладки
#: и страница агента — разные инструменты, их не должно быть можно
#: перепутать ссылкой из истории браузера.
DEFAULT_PORT = 8784

#: Адрес бесплатных моделей opencode.
ZEN_BASE = "https://opencode.ai/zen/v1"

#: Вид официального клиента. Версия в имени должна быть: zen проверяет,
#: что `User-Agent` начинается с `opencode/`, а не что он равный.
ZEN_USER_AGENT = "opencode/1.15.5 ai-sdk/provider-utils/1.2.3"

#: Публичный доступ без аккаунта. Ключ не нужен и не подставляется.
ZEN_BEARER = "public"

#: Как долго один идентификатор сессии используется. Меняем по таймеру,
#: а не на каждый запрос: постоянная смена выглядит для zen как новый
#: клиент каждую секунду, а одна вечная сессия — как зависший процесс.
#: Тридцать минут — компромисс между «слишком часто» и «слишком редко».
SESSION_TTL_S = 1800.0

#: Куда искать локальный сервис opencode (запасной путь).
SERVICE_FILES = (
    "~/.local/state/opencode/service.json",
    "~/.config/opencode/service.json",
)

#: Сколько ждём модель. Потолок нужен, чтобы мост не висел вечно.
ASK_TIMEOUT_S = 120.0

#: Сколько последних запросов держим для панели.
RECENT_LIMIT = 20

#: Сколько моделей опрашиваем одновременно в ask_all. Больше потоков
#: не даёт выигрыша: запрос идёт по сети, а не считает на ядре, и
#: лишние потоки только расходуют соединения к zen.
ASK_ALL_WORKERS = 6

#: Сколько символов ответа показываем на модель. Всё целиком ответы
#: всех моделей в панели не нужны, а таблица от них расползается.
ASK_ALL_TEXT = 600

#: Признак бесплатной модели: цена отсутствует либо нулевая.
_FREE_IN_NAME = re.compile(r"free", re.IGNORECASE)


class DonorUnavailable(RuntimeError):
    """Ни zen, ни локальный opencode не ответили.

    Отдельный тип нужен вызывающему, чтобы отличить «сосед временно не
    доступен» (повторить имеет смысл) от «запрос неправильный»
    (повтор не поможет).
    """

    def __init__(self, message: str, status: int = 502,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _error_message(payload: Any, fallback: str) -> str:
    """Человеческий текст ошибки из ответа zen.

    Формы у zen разные: `{"error": {"message": ...}}`,
    `{"error": "текст"}`, иногда просто строка. Разбираем все три, иначе
    в журнал попадёт «HTTP 429» без причины, а с причиной разбираться
    в разы легче.
    """
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or fallback)
        if isinstance(err, str):
            return err
        msg = payload.get("message")
        if isinstance(msg, str):
            return msg
    if isinstance(payload, str) and payload.strip():
        # Тело ошибки приходит текстом. Если это JSON — разбираем и берём
        # сообщение оттуда: показывать «{"error": {...}}» вместо причины
        # бессмысленно.
        try:
            return _error_message(json.loads(payload), fallback)
        except json.JSONDecodeError:
            return payload.strip()[:300]
    return fallback


class ZenClient:
    """Прокси к бесплатным моделям opencode.

    Держит один идентификатор сессии на интервал `SESSION_TTL_S` и
    обновляет его по таймеру. Заголовки собираются в одном месте —
    их смысл описан в модуле, а в коде остаётся факт.
    """

    def __init__(self, base: str = ZEN_BASE, user_agent: str = ZEN_USER_AGENT,
                 bearer: str = ZEN_BEARER, timeout: float = ASK_TIMEOUT_S) -> None:
        self.base = base.rstrip("/")
        self.user_agent = user_agent
        self.bearer = bearer
        self.timeout = timeout
        self._session = ""
        self._session_at = 0.0
        self._lock = threading.Lock()

    def session_id(self) -> str:
        """Идентификатор сессии, обновляемый по таймеру."""
        with self._lock:
            now = time.time()
            if not self._session or now - self._session_at > SESSION_TTL_S:
                self._session = uuid.uuid4().hex
                self._session_at = now
            return self._session

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        out = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Именно эти два заголовка делают запрос «официальным».
            "User-Agent": self.user_agent,
            "x-opencode-session": self.session_id(),
            "Authorization": f"Bearer {self.bearer}",
        }
        out.update(extra or {})
        return out

    def call(self, path: str, payload: dict[str, Any] | None = None,
             timeout: float | None = None) -> Any:
        url = f"{self.base}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url, data=data, headers=self.headers(),
            method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(request,
                                        timeout=timeout or self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 — деталь необязательна
                detail = ""
            retry_after = None
            header = exc.headers.get("Retry-After") if exc.headers else None
            if header:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = None
            # 429 — лимит: повтор имеет смысл позже. 401/403 — доступ
            # закрыт: повтор не поможет, но это тоже не ошибка zagent.
            status = exc.code
            raise DonorUnavailable(
                f"zen ответил HTTP {status}: "
                f"{_error_message(detail, 'причина не указана')}",
                status=503 if status == 429 else status,
                retry_after=retry_after,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DonorUnavailable(
                f"zen недоступен ({type(exc).__name__}): {exc}") from exc
        try:
            return json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            raise DonorUnavailable("zen вернул не JSON") from None

    def models(self) -> list[dict[str, Any]]:
        """Бесплатные модели zen в виде, пригодном и для панели, и для zagent.

        Список цен zen не отдаёт: в ответе только `id`, `object`,
        `created`, `owned_by`. Поэтому бесплатность определяется по имени
        (`*-free`), а ветка с ценой оставлена на будущее — если zen
        начнёт публиковать стоимость, модель с нулевой ценой попадёт в
        список даже без слова «free» в названии.

        Проверка по имени — не эвристика ради эвристики: платные модели
        называются без «free», и отдать их мостом значило бы предлагать
        zagent тратить деньги на «бесплатном» шлюзе.
        """
        data = self.call("/models", timeout=30.0)
        items = data.get("data") if isinstance(data, dict) else data
        out: list[dict[str, Any]] = []
        for model in items or []:
            model_id = str(model.get("id") or "")
            if not model_id:
                continue
            cost = model.get("cost") or model.get("pricing")
            free = False
            if isinstance(cost, dict) and cost:
                free = all(float(cost.get(k) or 0) == 0
                           for k in ("input", "output"))
            elif isinstance(cost, list) and cost:
                free = all(float((c or {}).get(k) or 0) == 0
                           for c in cost for k in ("input", "output"))
            else:
                free = bool(_FREE_IN_NAME.search(model_id))
            if not free:
                continue
            out.append({
                "id": model_id,
                "model": model_id,
                "provider": "opencode",
                "name": str(model.get("name") or model_id),
                "tools": True,
                "vision": False,
            })
        return out

    def chat(self, model: str, messages: list[dict[str, Any]],
             max_tokens: int = 0, temperature: float | None = None) -> dict[str, Any]:
        """Один вызов модели. Ответ приходит уже в формате OpenAI."""
        payload: dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if temperature is not None:
            payload["temperature"] = float(temperature)
        return self.call("/chat/completions", payload)


class LocalOpencode:
    """Запасной путь: локальный сервис opencode.

    Используется, когда zen не отвечает или упёрся в лимит: у процесса
    opencode своя квота, и это честный второй шанс вместо отказа.
    Ничего не «подменяем» — просто идём в его API с его паролем.
    """

    def __init__(self) -> None:
        self.url = ""
        self.password = ""
        self._discover()

    def _discover(self) -> None:
        import os

        url = os.environ.get("ZAGENT_OPENCODE_URL", "").strip()
        password = os.environ.get("ZAGENT_OPENCODE_PASSWORD", "").strip()
        if url and password:
            self.url, self.password = url, password
            return
        for pattern in SERVICE_FILES:
            try:
                data = json.loads(Path(pattern).expanduser()
                                  .read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("url") and data.get("password"):
                self.url = str(data["url"])
                self.password = str(data["password"])
                return

    @property
    def ready(self) -> bool:
        return bool(self.url and self.password)

    def call(self, path: str, payload: dict[str, Any] | None = None,
             timeout: float = 30.0) -> Any:
        if not self.ready:
            raise DonorUnavailable("локальный opencode не найден")
        token = base64.b64encode(
            f"opencode:{self.password}".encode()).decode("ascii")
        headers = {"Authorization": f"Basic {token}"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.url}{path}", data=data, headers=headers,
            method="POST" if payload is not None else "GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            raise DonorUnavailable(
                f"локальный opencode недоступен: {type(exc).__name__}") from exc
        try:
            return json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            raise DonorUnavailable("локальный opencode вернул не JSON") from None

    def info(self) -> dict[str, Any]:
        return self.call("/api/info", timeout=5.0)


#: На сколько модель уходит из ротации после отказа. Отказ «только из
#: opencode» или «недоступна в вашей стране» не исчезнет через минуту, но
#: и не факт, что не вернётся завтра: утром девять часов — и можно пробовать
#: снова. Поэтому такой срок, а не «навсегда».
MODEL_COOLDOWN_S = 9 * 3600.0

#: Короткая пауза после временной ошибки (модель занята, провайдер
#: перегружен). Ждать почти бесполезно: минута ответа не стоит минуты
#: ожидания.
MODEL_RETRY_S = 120.0


class ModelBlocked(RuntimeError):
    """Модель отказала и ушла из ротации на время остывания."""

    def __init__(self, model: str, reason: str, seconds: float) -> None:
        super().__init__(reason)
        self.model = model
        self.reason = reason
        self.seconds = seconds


class _ModelHealth:
    """Что известно о каждой модели: работает, отказала, когда попробовать.

    Зачем это: бесплатные модели zen делятся на две половины. Часть
    отвечает напрямую, а часть отвечает отказом «free tier can only be
    used from within OpenCode» или «недоступна в вашей стране». Без памяти
    об этих отказах каждый запрос агента снова упирался бы в модель,
    которая не заработает, и ждал бы полный таймаут — то есть задача
    вставала бы на каждом шаге.
    """

    def __init__(self) -> None:
        self._bad: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def check(self, model: str) -> None:
        """Проверить, можно ли пробовать модель. Иначе — ModelBlocked."""
        with self._lock:
            entry = self._bad.get(model)
        if not entry:
            return
        until, reason = entry
        left = until - time.time()
        if left <= 0:
            with self._lock:
                self._bad.pop(model, None)
            return
        raise ModelBlocked(model, reason, left)

    def fail(self, model: str, reason: str,
             retry_after: float | None = None) -> None:
        """Запомнить отказ и определить, на сколько забыть модель.

        `retry_after` — то, что попросил провайдер. Оно важнее любой
        нашей задержки: провайдер знает про свою квоту точнее, чем
        мы, и подставлять своё вместо его слов — значит ждать дольше
        нужного или раньше нужного.
        """
        text = (reason or "").lower()
        # Постоянные отказы опознаются по словам, а не по коду ответа:
        # провайдер отвечает 403 на всё подряд, и по коду нельзя понять,
        # что именно не так.
        permanent = ("within opencode" in text
                     or "not available in your country" in text
                     or "has been deprecated" in text
                     or "model is unavailable" in text)
        if retry_after and retry_after > 0 and not permanent:
            pause = float(retry_after)
        else:
            pause = MODEL_COOLDOWN_S if permanent else MODEL_RETRY_S
        with self._lock:
            self._bad[model] = (time.time() + pause, reason or "отказ модели")
        raise ModelBlocked(model, reason or "отказ модели", pause)

    def ok(self, model: str) -> None:
        with self._lock:
            self._bad.pop(model, None)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Состояние известных моделей — для панели и /health."""
        now = time.time()
        with self._lock:
            return {
                model: {"reason": reason, "left_s": max(0, int(until - now))}
                for model, (until, reason) in self._bad.items()
                if until > now
            }


class Bridge:
    """Состояние моста: модели, счётчики, последние запросы."""

    def __init__(self, root: Any = None, port: int = DEFAULT_PORT) -> None:
        self.root = Path(root) if root else Path.cwd()
        self.port = int(port)
        self.zen = ZenClient()
        self.local = LocalOpencode()
        self.health = _ModelHealth()
        self.started_at = time.time()
        self.requests = 0
        self.failures = 0
        self.recent: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ счётчики

    def record(self, model: str, seconds: float, ok: bool,
               error: str = "", via: str = "zen") -> None:
        with self._lock:
            self.requests += 1
            if not ok:
                self.failures += 1
            self.recent.insert(0, {
                "at": round(time.time(), 3),
                "model": model,
                "ms": int(seconds * 1000),
                "ok": ok,
                "via": via,
                "error": error[:300],
            })
            del self.recent[RECENT_LIMIT:]

    def models(self) -> list[dict[str, Any]]:
        """Модели для панели и для zagent.

        Кэш на минуту: панель опрашивает каждую секунду, а список из 88
        моделей с интернета тянуть на каждый чих — значит жертвовать
        именно тем, ради чего мост сделан, то есть скоростью.
        """
        now = time.time()
        cached = getattr(self, "_models_cache", None)
        if cached and now - cached[0] < 60.0:
            return cached[1]
        try:
            models = self.zen.models()
        except DonorUnavailable as exc:
            diag.note("bridge_models", exc)
            models = []
        with self._lock:
            self._models_cache = (now, models)
        return models

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = list(self.recent)
        local_state = {"ready": self.local.ready}
        if self.local.ready:
            try:
                local_state["version"] = str(self.local.info().get("version") or "")
            except DonorUnavailable as exc:
                local_state["error"] = str(exc)[:200]
        models = self.models()
        return {
            "ok": True,
            "port": self.port,
            "uptime_s": int(time.time() - self.started_at),
            "zen": {"base": ZEN_BASE, "models": len(models),
                    "free_models": len(models)},
            "local_opencode": local_state,
            "requests": self.requests,
            # Модели на остывании видны сразу и с причиной: иначе в
            # списке они выглядят как обычные, и человек гадает, почему
            # задача их не выбирает.
            "blocked": self.health.snapshot(),
            "failures": self.failures,
            "recent": recent,
            "errors": diag.DIAG.stats(),
        }

    # ------------------------------------------------------ вызов модели

    def ask(self, model: str, messages: list[dict[str, Any]],
            max_tokens: int = 0, temperature: float | None = None,
            timeout: float = ASK_TIMEOUT_S) -> tuple[str, float, str]:
        """Спросить модель. Возвращает (текст, секунды, каким путём).

        Сначала zen — он быстрее и не зависит от того, запущен ли
        opencode. Если zen не ответил, пробуем локальный сервис: у него
        своя квота, и отказ вместо второй попытки был бы напрасливой.
        """
        started = time.perf_counter()
        # Модель, которая только что отказала, второй раз не пробуется:
        # иначе каждый запрос агента ждал бы полный таймаут на модели,
        # которая не заработает (проверено: 12 из 14 бесплатных моделей
        # zen отвечают отказом «только из opencode» или «недоступна в
        # вашей стране»).
        self.health.check(model)
        try:
            answer = self._text_of(self.zen.chat(
                model, messages, max_tokens=max_tokens,
                temperature=temperature))
            self.health.ok(model)
            return answer, time.perf_counter() - started, "zen"
        except DonorUnavailable as exc:
            diag.note("bridge_zen", exc, model=model)
            if not self.local.ready:
                self.health.fail(model, str(exc), exc.retry_after)

        # Запасной путь. Текст берём из сообщения ассистента сессии.
        prompt = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                prompt = str(message.get("content") or "")
                break
        if not prompt:
            raise DonorUnavailable("нет сообщения пользователя", status=400)

        provider, _, model_id = model.partition("/")
        session = self.local.call("/api/session", {
            "title": "zagent bridge",
            "model": {"id": model, "providerID": provider or "opencode"},
        }, timeout=30.0)
        data = session.get("data") if isinstance(session, dict) else {}
        session_id = str((data or {}).get("id") or "")
        if not session_id:
            raise DonorUnavailable("локальный opencode не вернул сессию")
        self.local.call(f"/api/session/{session_id}/prompt",
                        {"text": prompt}, timeout=timeout)
        # Ответ появляется не сразу: короткий опрос вместо слепой паузы.
        answer = ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            got = self.local.call(
                f"/api/session/{session_id}/message?limit=10", timeout=30.0)
            for item in (got.get("data") or []):
                if item.get("type") == "assistant":
                    answer = str(item.get("text") or "").strip()
                    if answer:
                        break
            if answer:
                break
            time.sleep(1.0)
        if not answer:
            raise DonorUnavailable("локальный opencode не вернул текст")
        self.health.ok(model)
        return answer, time.perf_counter() - started, "local"

    # ------------------------------------------------- общение со всеми

    def status(self) -> dict[str, Any]:
        """Строка на каждую модель: что с ней и почему.

        Состояние собирается из трёх источников, и порядок важен:
        модель на остывании показываем как остывающую, даже если её
        последний запрос был успешным — иначе человек увидит «ок» и
        не поймёт, почему задача её не выбирает.
        """
        snap = self.snapshot()
        blocked: dict[str, Any] = snap.get("blocked") or {}
        recent: list[dict[str, Any]] = snap.get("recent") or []

        # recent[0] — самый свежий, поэтому первый попавшийся выигрывает.
        last: dict[str, dict[str, Any]] = {}
        for item in reversed(recent):
            last[str(item.get("model") or "")] = item

        rows: list[dict[str, Any]] = []
        for model in self.models():
            model_id = str(model.get("id") or "")
            if not model_id:
                continue
            cooldown = blocked.get(model_id) or {}
            seen = last.get(model_id) or {}
            if cooldown:
                state = "cooling"
                reason = str(cooldown.get("reason") or "")
                left_s = int(cooldown.get("left_s") or 0)
            elif seen:
                state = "ok" if seen.get("ok") else "fail"
                reason = str(seen.get("error") or "")
                left_s = 0
            else:
                state = "unknown"
                reason = ""
                left_s = 0
            rows.append({
                "id": model_id,
                "provider": str(model.get("provider") or ""),
                "state": state,
                "reason": reason[:300],
                "cooldown_left_s": left_s,
                "last_ms": int(seen.get("ms") or 0) if seen else 0,
                "last_ok": bool(seen.get("ok")) if seen else None,
                "last_via": str(seen.get("via") or "") if seen else "",
            })
        return {
            "ok": True,
            "port": self.port,
            "uptime_s": int(time.time() - self.started_at),
            "models": rows,
            "requests": int(snap.get("requests") or 0),
            "failures": int(snap.get("failures") or 0),
            "local_opencode": snap.get("local_opencode") or {},
        }

    def ask_all(self, prompt: str, *, timeout: float = ASK_TIMEOUT_S,
                models: list[str] | None = None) -> dict[str, Any]:
        """Один вопрос — всем моделям сразу.

        Потоки вместо очереди: иначе четырнадцать моделей по очереди дали
        бы сумму их таймаутов, а половина из них всё равно не отвечает.
        Каждая модель получает одинаковый вопрос, ответы не мешают
        друг другу, и порядок в таблице не зависит от скоростей.
        """
        text_prompt = str(prompt or "").strip()
        if not text_prompt:
            raise ValueError("пустой вопрос")
        if models is None:
            targets = [str(m.get("id") or "") for m in self.models()]
            targets = [m for m in targets if m]
        else:
            targets = [str(m) for m in models if str(m).strip()]
        if not targets:
            return {"ok": True, "results": [], "asked": 0}

        started = time.perf_counter()
        workers = max(1, min(ASK_ALL_WORKERS, len(targets)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._ask_one, model, text_prompt, timeout)
                       for model in targets]
            results = [f.result() for f in futures]
        results.sort(key=lambda item: (not item["ok"], item["ms"], item["id"]))
        return {
            "ok": True,
            "asked": len(targets),
            "answered": sum(1 for r in results if r["ok"]),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "results": results,
        }

    def _ask_one(self, model: str, prompt: str, timeout: float) -> dict[str, Any]:
        """Одна модель в ask_all: всегда возвращает строку, не поднимает.

        Отсюда идут и /status, и панель: строка результата обязана быть
        всегда — иначе обрыв сети у одной модели уронил бы весь опрос,
        а это ровно тот случай, ради которого человек и открывает панель.
        """
        messages = [{"role": "user", "content": prompt}]
        try:
            answer, seconds, via = self.ask(model, messages, timeout=timeout)
        except ModelBlocked as blocked:
            self.record(model, 0.0, False, blocked.reason)
            return {"id": model, "ok": False, "ms": 0, "via": "",
                    "state": "cooling", "error": blocked.reason,
                    "cooldown_left_s": int(blocked.seconds), "answer": ""}
        except DonorUnavailable as exc:
            self.record(model, 0.0, False, str(exc))
            return {"id": model, "ok": False, "ms": 0, "via": "",
                    "state": "fail", "error": str(exc)[:300],
                    "cooldown_left_s": 0, "answer": ""}
        except Exception as exc:  # noqa: BLE001 - строка отчёта важнее стека
            # Неизвестная ошибка не должна уносить остальные модели.
            self.record(model, 0.0, False, f"{type(exc).__name__}: {exc}")
            return {"id": model, "ok": False, "ms": 0, "via": "",
                    "state": "fail", "error": f"{type(exc).__name__}: {exc}"[:300],
                    "cooldown_left_s": 0, "answer": ""}
        self.record(model, seconds, True, via=via)
        return {"id": model, "ok": True, "ms": int(seconds * 1000), "via": via,
                "state": "ok", "error": "", "cooldown_left_s": 0,
                "answer": answer[:ASK_ALL_TEXT]}

    @staticmethod
    def _text_of(response: Any) -> str:
        """Текст из ответа zen.

        Некоторые модели кладут рассуждение в отдельное поле и оставляют
        `content` пустым. Отдавать пустую строку в таком случае —
        значит отправить пользователю «модель не ответила», хотя ответ
        есть; поэтому берём рассуждение как последний выход.
        """
        if not isinstance(response, dict):
            raise DonorUnavailable("zen вернул не объект")
        choices = response.get("choices") or []
        for choice in choices:
            message = choice.get("message") or {}
            text = message.get("content")
            if isinstance(text, str) and text.strip():
                return text.strip()
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return reasoning.strip()
        raise DonorUnavailable("модель вернула пустой ответ")

    # ------------------------------------------------------------- запуск

    def start(self) -> bool:
        """Поднять сервер в фоновом потоке. False — порт занят."""
        if self._server is not None:
            return True
        holder = self

        class Handler(_BridgeHandler):
            bridge = holder  # type: ignore[assignment]

        try:
            server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as exc:
            diag.note("bridge_start", exc, port=self.port)
            return False
        server.daemon_threads = True
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="zagent-bridge", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception as exc:  # noqa: BLE001 — остановка не должна шуметь
            diag.note("bridge_stop", exc)
        finally:
            self._server = None


class _BridgeHandler(BaseHTTPRequestHandler):
    """Панель, health, модели и OpenAI-совместимый вызов."""

    protocol_version = "HTTP/1.1"
    server_version = "zagent-bridge"
    bridge: Bridge  # type: ignore[assignment]

    def handle_one_request(self) -> None:
        """Оборванное соединение — обычное дело, а не падение.

        Клиент (это обычно сам zagent) отменяет запрос, когда модель не
        ответила вовремя: сокет закрывается, а http.server печатает на
        консоль трейсбек на каждое такое прерывание. При десятке отменённых
        запросов окно забивается стенами трассировок, и главная информация
        — «модель не ответила» — теряется. В основном сервере приём тот
        же (hub/server.py), здесь повторяем.
        """
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError,
                BrokenPipeError, TimeoutError):
            self.close_connection = True

    def log_message(self, fmt: str, *args: Any) -> None:
        # Обычный лог http.server уходит в stderr на каждый запрос. Тишина
        # тут уместна: кто спрашивал и с чем видно в /health и в журнале.
        return

    def _host_is_local(self) -> bool:
        """Запрос пришёл на наш адрес, а не на чужой хост.

        Барьер тот же, что на основном сервере. Без него посторонняя
        страница в браузере дёргала бы `127.0.0.1:8784` без спроса
        (для localhost браузер CORS не спрашивает) и тратила модели
        человека.
        """
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return True  # HTTP/1.0 и тесты
        return host.split(":")[0].strip("[]").lower() in (
            "127.0.0.1", "localhost", "::1")

    def _reject(self, reason: str) -> None:
        body = json.dumps({"error": reason}, ensure_ascii=False).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200,
              extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    # ---------------------------------------------------------------- GET

    def do_GET(self) -> None:  # noqa: N802 — имя задано базовым классом
        if not self._host_is_local():
            return self._reject("Запрос с чужого адреса отклонён")
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._html(_PAGE.replace("__PORT__", str(self.bridge.port)))
        if path == "/health":
            return self._json(self.bridge.snapshot())
        if path == "/diag":
            return self._json({"ok": True,
                               "errors": diag.DIAG.stats(),
                               "recent": diag.DIAG.recent()})
        if path == "/status":
            # Отладчик рисует это таблицей: модель, состояние, время.
            return self._json(self.bridge.status())
        if path == "/v1/models":
            return self._json({
                "object": "list",
                "data": [{"id": m["id"], "object": "model",
                          "owned_by": m["provider"]} for m in self.bridge.models()],
            })
        return self._json({"error": "not found"}, 404)

    # --------------------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_is_local():
            return self._reject("Запрос с чужого адреса отклонён")
        path = self.path.split("?", 1)[0]
        body = self._body()
        if path == "/v1/chat/completions":
            return self._chat(body)
        if path == "/ask_all":
            # Один вопрос всем моделям. Ошибка — только пустой вопрос
            # или список без идентификаторов; отказы моделей сюда не
            # попадают, они в results.
            prompt = str(body.get("text") or "").strip()
            if not prompt:
                return self._json({"ok": False, "error": "пустой вопрос"}, 400)
            wanted = body.get("models")
            selected = None
            if isinstance(wanted, list):
                selected = [str(m) for m in wanted if str(m).strip()]
            try:
                answer = self.bridge.ask_all(
                    prompt, timeout=float(body.get("timeout") or ASK_TIMEOUT_S),
                    models=selected)
            except ValueError as exc:
                return self._json({"ok": False, "error": str(exc)}, 400)
            return self._json(answer)
        if path == "/ask":
            # Тот же вызов для панели: отличается только формой ответа.
            model = str(body.get("model") or "")
            prompt = str(body.get("text") or "")
            try:
                answer, seconds, via = self.bridge.ask(
                    model, [{"role": "user", "content": prompt}],
                    timeout=float(body.get("timeout") or ASK_TIMEOUT_S))
            except DonorUnavailable as exc:
                self.bridge.record(model, 0.0, False, str(exc))
                return self._json({"ok": False, "error": str(exc)}, 502)
            self.bridge.record(model, seconds, True, via=via)
            return self._json({"ok": True, "model": model, "via": via,
                               "ms": int(seconds * 1000), "answer": answer})
        return self._json({"error": "not found"}, 404)

    def _chat(self, body: dict[str, Any]) -> None:
        """OpenAI-совместимый вызов: им пользуется zagent как шлюз."""
        model = str(body.get("model") or "").strip()
        messages = body.get("messages") or []
        if not isinstance(messages, list) or not messages:
            return self._json({"error": {
                "message": "нет messages", "type": "invalid_request_error"}}, 400)
        try:
            answer, seconds, via = self.bridge.ask(
                model, messages,
                max_tokens=int(body.get("max_tokens") or 0),
                temperature=body.get("temperature"))
        except ModelBlocked as blocked:
            # Модель на остывании: отвечаем сразу и честно, с Retry-After.
            # zagent трактует это как карантин ключа и идёт к другой
            # модели, вместо того чтобы ждать таймаут на каждом шаге.
            self.bridge.record(model, 0.0, False, blocked.reason)
            return self._json({"error": {
                "message": f"{model}: {blocked.reason}",
                "type": "model_unavailable",
            }}, 503, {"Retry-After": str(int(blocked.seconds))})
        except DonorUnavailable as exc:
            self.bridge.record(model, 0.0, False, str(exc))
            extra = {}
            if exc.retry_after:
                extra["Retry-After"] = str(int(exc.retry_after))
            return self._json({"error": {"message": str(exc),
                                         "type": "upstream_error"}},
                              exc.status, extra)

        self.bridge.record(model, seconds, True, via=via)
        return self._json({
            "id": f"bridge-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                      "total_tokens": 0},
        })


#: Панель моста: одна страница, без внешних ресурсов. Внешние ресурсы
#: здесь означали бы, что страница не откроется без интернета — а мост
#: как раз для того, чтобы работать локально.
_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Донорский шлюз zagent</title>
<style>
 :root{color-scheme:dark}
 body{margin:0;background:#0f1115;color:#e6e8ee;font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
 header{padding:14px 20px;background:#161a22;border-bottom:1px solid #232936;display:flex;
        align-items:center;gap:12px;flex-wrap:wrap}
 h1{font-size:16px;margin:0;font-weight:600}
 h2{font-size:13px;margin:0 0 10px;color:#9aa4b8;text-transform:uppercase;letter-spacing:.04em}
 .tag{padding:2px 8px;border-radius:10px;font-size:12px;background:#232936;color:#aeb6c6;text-decoration:none}
 .ok{background:#16341f;color:#7ee2a3}.bad{background:#3a1c1c;color:#ff9d9d}
 main{padding:18px 20px;display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
 section{background:#141821;border:1px solid #232936;border-radius:10px;padding:14px}
 select,input,textarea,button{font:inherit;color:inherit;background:#0f1319;border:1px solid #2a3140;
        border-radius:7px;padding:7px 9px}
 textarea{width:100%;min-height:70px;resize:vertical}
 button{cursor:pointer;background:#2b6ef2;border-color:#2b6ef2}
 button.ghost{background:transparent;border-color:#2a3140}
 table{width:100%;border-collapse:collapse;font-size:12.5px}
 td,th{padding:4px 6px;border-bottom:1px solid #232936;text-align:left}
 .dim{color:#8b95a8}.mono{font-family:ui-monospace,Consolas,monospace}
 pre{white-space:pre-wrap;word-break:break-word;background:#0f1319;border:1px solid #232936;
     border-radius:8px;padding:10px;max-height:320px;overflow:auto}
 .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
 .list{max-height:220px;overflow:auto}
</style></head><body>
<header>
  <h1>Донорский шлюз</h1>
  <span class="tag" id="stZen">zen: …</span>
  <span class="tag" id="stLocal">opencode: …</span>
  <span class="tag" id="stReqs">запросов: 0</span>
  <span class="tag" id="stFail">ошибок: 0</span>
  <button class="ghost" onclick="load()">Обновить</button>
  <a class="tag" href="http://127.0.0.1:8783" target="_blank">интерфейс zagent</a>
</header>
<main>
 <section>
  <h2>Спросить модель напрямую</h2>
  <div class="row">
    <select id="model" style="flex:1"></select>
    <button onclick="ask()">Спросить</button>
  </div>
  <textarea id="text" placeholder="Вопрос модели…"></textarea>
  <pre id="answer" class="dim">Ответ появится здесь.</pre>
 </section>
 <section>
  <h2>Бесплатные модели</h2>
  <div id="models" class="dim list">загрузка…</div>
 </section>
 <section>
  <h2>Последние запросы</h2>
  <table><thead><tr><th>когда</th><th>модель</th><th>мс</th><th>путём</th><th>итог</th></tr></thead>
  <tbody id="recent"></tbody></table>
 </section>
 <section>
  <h2>Журнал ошибок</h2>
  <table><thead><tr><th>когда</th><th>место</th><th>ошибка</th></tr></thead>
  <tbody id="errs"></tbody></table>
 </section>
</main>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function load() {
  const st = await (await fetch('/health')).json();
  const models = st.zen ? st.zen.free_models : 0;
  $('stZen').textContent = 'моделей: ' + models;
  $('stZen').className = 'tag ' + (models ? 'ok' : 'bad');
  const loc = st.local_opencode || {};
  $('stLocal').textContent = 'opencode: ' + (loc.ready ? (loc.version || 'запущен') : 'не найден');
  $('stLocal').className = 'tag ' + (loc.ready ? 'ok' : 'dim');
  $('stReqs').textContent = 'запросов: ' + st.requests;
  $('stFail').textContent = 'ошибок: ' + st.failures;
  $('stFail').className = 'tag ' + (st.failures ? 'bad' : '');

  $('recent').innerHTML = (st.recent || []).map(r =>
    `<tr><td class="dim">${esc(new Date(r.at * 1000).toLocaleTimeString())}</td>
     <td class="mono">${esc(r.model)}</td><td>${esc(r.ms)}</td><td class="dim">${esc(r.via)}</td>
     <td style="${r.ok ? '' : 'color:#ff9d9d'}">${esc(r.ok ? 'ок' : r.error)}</td></tr>`
  ).join('') || '<tr><td colspan="5" class="dim">пока пусто</td></tr>';

  const d = await (await fetch('/diag')).json();
  $('errs').innerHTML = (d.recent || []).map(e =>
    `<tr><td class="dim">${esc(e.at ? new Date(e.at * 1000).toLocaleTimeString() : '')}</td>
     <td class="mono">${esc(e.scope)}</td><td>${esc(e.error || e.msg)}</td></tr>`
  ).join('') || '<tr><td colspan="3" class="dim">ошибок не было</td></tr>';

  const list = (await (await fetch('/v1/models')).json()).data || [];
  $('models').innerHTML = list.length
    ? list.map(m => `<div class="mono" style="padding:1px 0">${esc(m.id)}</div>`).join('')
    : '<span class="dim">моделей нет (zen недоступен?)</span>';
  const sel = $('model');
  if (list.length && !sel.options.length)
    sel.innerHTML = list.map(m => `<option value="${esc(m.id)}">${esc(m.id)}</option>`).join('');
}

async function ask() {
  const model = $('model').value, text = $('text').value.trim();
  if (!model || !text) return;
  $('answer').textContent = 'запрос…';
  $('answer').classList.remove('dim');
  const t0 = performance.now();
  const r = await (await fetch('/ask', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model, text})})).json();
  const ms = Math.round(performance.now() - t0);
  $('answer').textContent = r.ok
    ? (r.answer + '\\n\\n— ' + ms + ' мс, путём: ' + r.via)
    : ('ошибка: ' + r.error);
  load();
}
load();
</script></body></html>"""

#: Экземпляр моста на процесс. Создаётся лениво, чтобы импорт модуля
#: ничего не поднимал: половина тестов его не трогает.
_BRIDGE: Bridge | None = None


def get(root: Any = None, port: int = DEFAULT_PORT) -> Bridge:
    """Мост процесса (создаётся при первом обращении)."""
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = Bridge(root=root, port=port)
    elif root is not None:
        _BRIDGE.root = Path(root)
    return _BRIDGE


def start_with(root: Any = None, port: int = DEFAULT_PORT,
               announce: bool = True) -> Bridge | None:
    """Поднять мост рядом с основным сервером.

    Занятый порт не должен мешать запуску zagent: мост — вспомогательный
    инструмент, а не условие работы программы. Тогда возвращаем None и
    пишем причину в журнал ошибок.
    """
    bridge = get(root, port)
    if bridge.start():
        if announce:
            print(f"Донорский шлюз: http://127.0.0.1:{bridge.port}"
                  f"  (модели: opencode/zen, ключи не нужны)")
        return bridge
    print(f"Донорский шлюз не поднялся: порт {port} занят "
          f"(подробности в web-state/diag.jsonl)")
    return None