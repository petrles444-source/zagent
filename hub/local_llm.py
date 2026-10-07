"""Локальные модели (Ollama) прямо в интерфейсе zagent.

Зачем
-----
Ollama — это модели, которые живут на этом компьютере: они не съедают
квоту, работают без интернета и не отдают ни текст запроса, ни ответ
никуда наружу. Для агента с задачами это может быть единственный
вариант, когда внешние шлюзы упёрлись в лимиты.

Что умеет модуль
----------------
* список установленных моделей ( Ollama `/api/tags`) — с размером на диске
  и параметром контекста, чтобы человек видел, во что он вкладывается;
* потоковый ответ по словам (`/api/chat`, stream=true, NDJSON построчно) —
  так же, как в привычных чатах, а не «молчание 12 секунд, потом текст»;
* разговор с историей: сообщения передаются в Ollama целиком, поэтому
  модель помнит предыдущие реплики.

Почему не Flask
--------------
У zagent уже есть свой сервер (`hub/server.py`), свой интерфейс и своя
база. Второй веб-сервер с Flask означал бы: второй порт, вторую копию
интерфейса, второе место, где живёт история чатов, и лишнюю зависимость.
Всё это уже есть, поэтому чат добавляется как вкладка существующего
интерфейса и два маршрута.

Защита
------
Только 127.0.0.1 и проверка Host — как на всех остальных маршрутах:
посторонняя страница в браузере иначе дёргала бы локальную модель
без спроса.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

#: Адрес локального рантайма. Ollama по умолчанию слушает только петлю,
#: поэтому и мы ходим на петлю: иначе запрос ушёл бы в сеть.
DEFAULT_BASE = "http://127.0.0.1:11434"

#: Сколько ждём модель. Локальная модель думает секундами, и это нормально;
#: потолок нужен, чтобы зависший рантайм не держал соединение вечно.
CHAT_TIMEOUT_S = 600.0

#: Сколько ждём список моделей. Он короткий, но если рантайм не запущен,
#: пользователь должен получить ответ «не запущен», а не зависание.
TAGS_TIMEOUT_S = 10.0


class LocalLLMError(RuntimeError):
    """Локальный рантайм не ответил или ответил непонятно."""


def _request(url: str, payload: dict[str, Any] | None = None,
             timeout: float = TAGS_TIMEOUT_S) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(
        url, data=data, headers=headers,
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001 — деталь необязательна
            detail = ""
        raise LocalLLMError(f"Ollama ответил HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalLLMError(
            f"Ollama недоступен ({type(exc).__name__}). "
            f"Запущен ли он: ollama serve") from exc
    try:
        return json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        raise LocalLLMError("Ollama вернул не JSON") from None


def models(base: str = DEFAULT_BASE) -> list[dict[str, Any]]:
    """Установленные модели с размером на диске и контекстом.

    Размер и контекст берём из ответа, потому что человек их не знает, а
    именно по ним понятно, стоит ли переключаться на 7B вместо 1.5B.
    """
    data = _request(f"{base.rstrip('/')}/api/tags")
    out: list[dict[str, Any]] = []
    for item in data.get("models") or []:
        details = item.get("details") or {}
        size = int(item.get("size") or 0)
        out.append({
            "id": str(item.get("name") or ""),
            "size_gb": round(size / (1024 ** 3), 1),
            "family": str(details.get("family") or ""),
            "parameters": str(details.get("parameter_size") or ""),
            "quantization": str(details.get("quantization_level") or ""),
            "context": int((item.get("model_info") or {})
                           .get(f"{details.get('family', '')}.context_length", 0) or 0),
        })
    return [m for m in out if m["id"]]


def available(base: str = DEFAULT_BASE) -> bool:
    """Запущен ли рантайм. Молчание на месте «нет моделей» непонятно."""
    try:
        return bool(models(base))
    except LocalLLMError:
        return False


def stream_chat(model: str, messages: list[dict[str, Any]],
                base: str = DEFAULT_BASE,
                timeout: float = CHAT_TIMEOUT_S) -> Iterator[str]:
    """Ответ модели по словам.

    Ollama в потоковом режиме отдаёт NDJSON: одна строка — один кусок
    текста. Строки собирать в один ответ нельзя — человек ждал бы минуту
    и получил бы всё разом, а главное свойство локальной модели в том,
    что она видна «в процессе».

    Битые строки пропускаются, а не роняют поток: одна испорченная строка
    не должна отнимать у человека уже полученный текст.
    """
    url = f"{base.rstrip('/')}/api/chat"
    payload = {"model": model, "messages": messages, "stream": True}
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
        method="POST")
    try:
        resp = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise LocalLLMError(f"Ollama ответил HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalLLMError(
            f"Ollama недоступен ({type(exc).__name__})") from exc

    started = time.perf_counter()
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if chunk.get("done"):
                break
            piece = ((chunk.get("message") or {}).get("content")
                     or chunk.get("response") or "")
            if piece:
                yield piece
    # Хвост в лог: сколько на деле заняло — человек спрашивает «почему так
    # долго», и ответ обязан быть где-то виден.
    diag = {"scope": "local_chat", "model": model,
            "ms": int((time.perf_counter() - started) * 1000)}
    try:
        from hub import diag

        diag.note("local_chat_done", **diag)
    except Exception:  # noqa: BLE001 — журнал не должен мешать чату
        pass