#!/usr/bin/env python3
r"""Прокси для помощника сайта: держит ключи у себя, наружу — один маршрут.

Зачем он нужен
--------------
Сайт живёт в интернете, а ключи к моделям лежат на этом компьютере.
Если отдать ключ странице, его заберёт любой, кто нажмёт F12 в своём
браузере, и потратит деньги. Поэтому ключ не уезжает никогда: наружу
смотрит только этот прокси, а внутри он обращается к локальному агенту
на 127.0.0.1, где ключи и живут.

Что он НЕ делает
----------------
Прокси не проксирует агента. Локальный сервер умеет читать файлы,
запускать задачи и менять настройки — выставлять его в интернет нельзя
даже «только на чтение». Здесь ровно один метод `POST /chat`, и всё.

Ограничения, без которых такой прокси — дыра
-------------------------------------------
* Origin: разрешён только сайт. Проверка не защита отcurl (тот подставляет
  заголовок), поэтому настоящая защита — лимиты ниже.
* Лимит запросов: на каждый адрес — ведро токенов. Без него любой, кто
  нашёл адрес туннеля, выжигает квоту.
* Длина сообщения и размер истории ограничены: иначе в модель уходит
  мегабайт текста за один вызов.
* Ответ модели не пересылается «как есть» без проверки: он попадает в
  HTML сайта, а значит должен быть экранирован на стороне страницы.

Запуск:
    .venv\Scripts\python.exe tools\bot_proxy.py
    .venv\Scripts\python.exe tools\bot_proxy.py --port 8790
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

#: Локальный агент. Слушает только 127.0.0.1 — это и есть граница, за
#: которую прокси не выпускает никого.
AGENT_URL = "http://127.0.0.1:8783/api/ask"

#: Кого пускаем. Сайт живёт на своём домене; localhost нужен для проверки
#: с этой машины, но не для бота — оставлен, чтобы видеть бота вживую.
ALLOWED_ORIGINS = {
    "https://zagent.do.am",
    "http://zagent.do.am",
    "http://127.0.0.1:8901",
    "http://localhost:8901",
}

#: Сколько вопросов в минуту с одного адреса. Человек в диалоге задаёт
#: меньше десятка; запас даёт прокрутку и перезапуск плеера.
RATE_LIMIT = 12
RATE_WINDOW_S = 60.0

#: Границы запроса. История держим короткой: каждый ход уходит в модель
#: целиком, и длинная переписка дорожает быстрее, чем кажется.
MAX_MESSAGE_CHARS = 2000
MAX_HISTORY = 12

#: Потолок тела запроса. Вопрос на 2000 символов — это около 6 КБ в
#: UTF-8; запас нужен на историю, но не на «загрузил в поле ромбейн».
MAX_BODY_BYTES = 64 * 1024

#: Сколько ждать агента. Модель думает секундами; минута — потолок,
#: после которого ответ уже никому не нужен.
UPSTREAM_TIMEOUT_S = 75.0

#: Где лежит каталог. Состав берём из того же файла, что читает сайт:
#: иначе помощник отвечает «назову три работы» по памяти и выдумывает
#: названия, а список на странице другой.
def find_site_dir() -> Path:
    """Папка с сайтами, где бы проект ни лежал.

    Каталог сайтов вынесен из агента в соседний проект, и путь к нему
    больше нельзя писать жёстко: было `корень агента / site`.

    Проверяются места по порядку — своё рядом с агентом, потом
    соседний проект. Первое найденное и есть ответ; если ничего не
    нашлось, возвращается ожидаемое путь: файл просто не найдётся,
    и код это переживёт, а не упадёт.

    Раньше путь был один и жёсткий, а `catalog_line()` при
    отсутствии файла отдавал пустую строку. Бот переставал знать
    состав каталога, и ничего об этом не сообщал.
    """
    candidates = (
        Path(__file__).resolve().parent.parent / "site",
        Path(__file__).resolve().parent.parent.parent
        / "portfolio" / "site",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]

CATALOG_FILE = find_site_dir() / "assets" \
    / "catalog.json"

#: Постоянная часть подсказки: устройство сайта. Ключей здесь нет и
#: быть не должно — только описание того, что умеет страница.
SITE_CONTEXT = (
    "Ты — помощник сайта «Neural Archive»: архив флеш-работ 1999–2010, "
    "которые воспроизводятся прямо в браузере через Ruffle (WebAssembly), "
    "без плагинов и без загрузки на сервер.\n"
    "Что умеет сайт: каталог работ с фильтрами и избранным, загрузка .swf "
    "перетаскиванием в окно, загрузка по прямой ссылке, пауза, полный "
    "экран, скачивание файла. Файл читается в браузере и никуда не уходит.\n"
    "Отвечай по-русски, коротко, по делу. Если вопрос не про сайт и не про "
    "Flash, скажи прямо, что это вне темы. Не выдумывай работы: приведённый "
    "ниже список полный, других нет."
)

_catalog_cache: dict[str, Any] = {"mtime": None, "text": ""}


def catalog_line() -> str:
    """Состав каталога одной строкой, с перечитыванием при изменении.

    Файл читается заново только если изменилось время модификации: иначе
    каждый вопрос платил бы за чтение с диска, а состав при этом не
    меняется.
    """
    try:
        mtime = CATALOG_FILE.stat().st_mtime
    except OSError:
        return "Состав каталога сейчас неизвестен."
    if _catalog_cache["mtime"] != mtime:
        try:
            items = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
            lines = [f"- {i.get('title')}: {i.get('note', '')}"
                     for i in items if isinstance(i, dict)]
            _catalog_cache["text"] = ("В каталоге ровно эти работы:\n"
                                      + "\n".join(lines))
        except (OSError, ValueError):
            _catalog_cache["text"] = "Состав каталога прочитать не удалось."
        _catalog_cache["mtime"] = mtime
    return _catalog_cache["text"]


def system_prompt(persona: str = "") -> str:
    """Подсказка целиком: голос агента, устройство сайта, состав каталога.

    Голос подставляется первым, чтобы он не забивался контекстом: модель
    читает начало подсказки как главное. Ключ проверяется по белому
    списку ещё в обработчике, здесь он уже свой.
    """
    voice = VOICES.get(persona)
    parts = [part for part in (voice, SITE_CONTEXT, catalog_line()) if part]
    return "\n\n".join(parts)


#: Голоса, которые можно запросить. Ключ приходит из браузера, поэтому
#: это белый список: иначе страница могла бы подсунуть любой текст и
#: назвать его системной подсказкой.
#:
#: Голос описан здесь, а не берётся из persona.py намеренно: прокси
#: должен работать, даже если модули бота на этой машине не установлены,
#: иначе пришлось бы ставить их ради одной строки текста.
VOICES: dict[str, str] = {
    "anatoly": (
        "Ты — Анатолий, программист из службы поддержки. Говори о себе "
        "в мужском роде: «я сделал», «я проверил», «я решил». Отвечай "
        "по-русски, обращаясь к человеку как к коллеге.\n"
        "Ты объясняешь Python и вообще программирование. Сначала ответ, "
        "потом «почему так», потом «как проверить». Код даёшь целиком, "
        "чтобы его можно было вставить и запустить без правок. "
        "Ошибки разбираешь по месту: почему она вылезла и что её вызвало.\n"
        "Не выдумывай: несуществующие функции, параметры и версии "
        "называть нельзя. Если точно не знаешь — скажи прямо и покажи, "
        "как это проверить."
    ),
    "guide": (
        "Ты — проводник по сайту. Отвечай коротко: что это за страница, "
        "где что лежит, куда можно перейти. О проекте говори только то, "
        "что есть на самой странице, и не выдумывай разделов."
    ),
    "archivist": (
        "Ты — хранитель архива Neural Archive. Ты знаешь про флеш-работы "
        "и про то, как они воспроизводятся в браузере. Отвечай по-русски "
        "спокойно и по делу, без превосходных степеней."
    ),
}


class TokenBucket:
    """Ведро токенов на адрес. Простое и предсказуемое — этого достаточно.

    Обход возможен (сменить адрес), поэтому лимит — не стена, а дорога.
    Ставится он, чтобы один человек не выжег квоту за ночь.
    """

    def __init__(self, limit: int, window: float) -> None:
        self._limit = limit
        self._window = window
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def take(self, key: str) -> bool:
        """Списать один запрос. False — лимит исчерпан."""
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits[key] if now - t < self._window]
            if len(hits) >= self._limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            # Подчищаем пустые записи: иначе словарь растёт по числу
            # запрошенных адресов и не уменьшается никогда.
            if len(self._hits) > 512:
                for addr in [a for a, v in self._hits.items() if not v]:
                    del self._hits[addr]
            return True


BUCKET = TokenBucket(RATE_LIMIT, RATE_WINDOW_S)


def clean_history(raw: Any) -> list[dict[str, str]]:
    """Оставить из истории только роли и короткие тексты.

    Всё, что пришло от страницы, считается чужим: роль проверяется по
    белому списку, текст обрезается. Иначе в модель можно подсунуть
    что угодно, назвав это «системным сообщением».
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[-MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        text = str(item.get("text") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        out.append({"role": role, "text": text[:MAX_MESSAGE_CHARS]})
    return out


def ask_agent(message: str, history: list[dict[str, str]],
              persona: str = "") -> dict[str, Any]:
    """Спросить локального агента. Возвращает разобранный ответ.

    Ошибки не поднимаются наружу: наружу уходит понятный текст и код.
    Тексты исключений здесь содержат адреса провайдеров и иногда куски
    ответа модели — их нельзя показывать посетителю сайта.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt(persona)}]
    for turn in history:
        messages.append(turn)
    messages.append({"role": "user", "content": message})

    body = json.dumps({
        "messages": messages,
        "max_tokens": 800,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        AGENT_URL, data=body,
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT_S) as resp:
            payload = json.loads(resp.read())
    except urllib.error.URLError as exc:
        return {"ok": False, "error": "агент недоступен — он выключен?"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "агент ответил неразборчиво"}
    except TimeoutError:
        return {"ok": False, "error": "модель не ответила вовремя"}
    except Exception as exc:
        return {"ok": False, "error": f"сбой связи с агентом ({type(exc).__name__})"}

    if not payload.get("ok"):
        return {"ok": False, "error": str(payload.get("error") or "агент отказал")}
    answer = str(payload.get("answer") or "").strip()
    if not answer:
        return {"ok": False, "error": "модель вернула пустой ответ"}
    return {
        "ok": True,
        "answer": answer,
        "model": str(payload.get("model") or ""),
        "duration_ms": payload.get("duration_ms"),
    }


class BotHandler(BaseHTTPRequestHandler):
    """Наружу: один маршрут для вопроса и один для проверки живости."""

    server_version = "zagent-bot"
    sys_version = ""

    # ---------------------------------------------------------- ответы

    def _send(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Ответ бота показывается на странице: браузер не должен ни
        # кэшировать его, ни вставлять в iframe чужого сайта.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = (self.headers.get("Origin") or "").strip()
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        # В лог не пишем: сообщения пользователей не должны оседать в
        # консоли целиком, а IP здесь и так видны.
        pass

    # ---------------------------------------------------------- маршруты

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = (self.headers.get("Origin") or "").strip()
        if origin not in ALLOWED_ORIGINS:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] == "/health":
            self._send({"ok": True, "service": "zagent-bot"})
            return
        self._send({"error": "not found"}, 404)

    def _read_body(self) -> bytes:
        """Прочитать тело запроса целиком.

        Тело читается ДО любой проверки, и это не аккуратность, а
        необходимость: если ответить, не вычитав запрос, клиент
        получит не ответ, а разрыв соединения. Он ещё пишет тело в
        сокет, а сервер закрывает канал — и браузер показывает
        «ошибка сети» вместо внятного «слишком много вопросов».

        Большой тело дочитывается и выбрасывается, чтобы соединение
        осталось в порядке; выше потолка — обрываем, такой размер всё
        равно не нужен.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        if length <= 0:
            return b""
        if length > MAX_BODY_BYTES:
            return b"\x00" * (MAX_BODY_BYTES + 1)   # признак «слишком много»
        return self.rfile.read(length)

    def do_POST(self) -> None:  # noqa: N802
        raw = self._read_body()
        if self.path.split("?")[0] != "/chat":
            self._send({"error": "not found"}, 404)
            return

        origin = (self.headers.get("Origin") or "").strip()
        # Пустой Origin — это curl и подобные. Такой запрос браузером
        # с чужой страницы не приходит, поэтому запрещаем: иначе лимиты
        # обходятся простым скриптом.
        if origin not in ALLOWED_ORIGINS:
            self._send({"error": "источник не разрешён"}, 403)
            return

        address = self.client_address[0] if self.client_address else "?"
        if not BUCKET.take(address):
            self._send({"error": "слишком много вопросов, подождите минуту"}, 429)
            return

        if len(raw) == 0 or len(raw) > MAX_BODY_BYTES:
            self._send({"error": "пустой или слишком большой запрос"}, 400)
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send({"error": "неразборный запрос"}, 400)
            return
        if not isinstance(payload, dict):
            self._send({"error": "ожидался объект"}, 400)
            return

        message = str(payload.get("message") or "").strip()
        if not message:
            self._send({"error": "пустой вопрос"}, 400)
            return
        if len(message) > MAX_MESSAGE_CHARS:
            message = message[:MAX_MESSAGE_CHARS]

        # Голос приходит из браузера, поэтому проверяется по списку.
        # Неизвестное имя — не ошибка: подставляется базовый голос, иначе
        # страница с чужим значением просто перестала бы отвечать.
        persona = str(payload.get("persona") or "")
        if persona not in VOICES:
            persona = "guide"

        result = ask_agent(message, clean_history(payload.get("history")),
                           persona)
        if not result.get("ok"):
            # Текст сбоя наружу не отдаётся: в нём встречаются адреса
            # провайдеров, идентификаторы ключей и куски ответа модели.
            # Посетителю достаточно знать «не получилось», а что именно
            # сломалось — в лог на этой машине.
            self._send({"error": "помощник сейчас не отвечает, попробуйте позже"},
                       502)
            return
        self._send(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="прокси помощника сайта")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--host", default="127.0.0.1",
                        help="0.0.0.0 — только если проксит туннель на этой же машине")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), BotHandler)
    print(f"бот на http://{args.host}:{args.port}  (POST /chat, GET /health)")
    print(f"агент: {AGENT_URL}")
    print(f"разрешённые источники: {', '.join(sorted(ALLOWED_ORIGINS))}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
