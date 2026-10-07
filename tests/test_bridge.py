"""Донорский шлюз: прокси к бесплатным моделям opencode.

Проверяется то, без чего шлюз не работает вовсе, и то, что он может
испортить:

* **подмена заголовков.** Без `User-Agent: opencode/<версия>` и
  `x-opencode-session` zen отвечает 400 MissingSessionID — то есть весь
  смысл моста в двух заголовках, и они проверяются напрямую;
* **идентификатор сессии** не должен меняться на каждый запрос (это выглядит
  для zen как новый клиент каждую секунду) и должен обновляться по таймеру;
* **только бесплатные модели.** Платные в списке означали бы, что агент
  пробует тратить деньги на «бесплатном» шлюзе;
* **формат ответа** OpenAI: от него зависит, поймёт ли ответ zagent;
* **пустой content при непустом reasoning_content** — реальный случай
  reasoning-моделей: отдать «модель не ответила» при наличии ответа хуже,
  чем отдать рассуждение;
* **лимит 429 превращается в 503 с Retry-After**, а не в 500: повтор имеет
  смысл, и zagent это понимает;
* **защита по Host**: localhost не должен тратить модели человека по
  запросу чужой страницы из браузера.

Сеть в тестах не используется: клиент подменяется заглушкой, которая
возвращает заранее заданный ответ или исключение.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from hub.bridge import (
    ZEN_BASE,
    Bridge,
    DonorUnavailable,
    ZenClient,
    _error_message,
)


# ------------------------------------------------------------- заголовки


def test_user_agent_выглядит_как_официальный_клиент() -> None:
    """zen проверяет, что запрос от CLI: без `opencode/<версия>` — 400."""
    headers = ZenClient().headers()
    assert headers["User-Agent"].startswith("opencode/"), headers["User-Agent"]
    assert headers["Authorization"] == "Bearer public"


def test_идентификатор_сессии_присутствует() -> None:
    """Без x-opencode-session zen отвечает MissingSessionID."""
    assert ZenClient().headers()["x-opencode-session"]


def test_сессия_стабильна_между_запросами() -> None:
    """Новая сессия на каждый запрос — это новый клиент каждую секунду."""
    client = ZenClient()
    assert client.session_id() == client.session_id()


def test_сессия_обновляется_по_таймеру(monkeypatch: Any) -> None:
    """Полчаса, потом меняем: иначе zen считает нас одним зависшим процессом."""
    client = ZenClient()
    first = client.session_id()
    # Смещение считаем ДО подмены: иначе подмена сама вызовет time.time()
    # и уйдёт в бесконечную рекурсию.
    now = time.time()
    monkeypatch.setattr("hub.bridge.time.time", lambda: now + 4000)
    assert client.session_id() != first


def test_пароль_никогда_не_попадает_в_заголовки_наружу() -> None:
    """Пароль живёт только в Basic-заголовке локального клиента."""
    client = ZenClient()
    dumped = json.dumps(client.headers())
    assert "Bearer" in dumped  # это публичный токен zen, не секрет
    assert client.bearer == "public"


# ---------------------------------------------------------------- модели


MODELS_ANSWER = {
    "object": "list",
    "data": [
        {"id": "space-bunny-free"},
        {"id": "deepseek-v4-flash-free"},
        {"id": "claude-opus-5"},
        {"id": "gpt-oss-120b"},
        {"id": "cheap-model", "cost": {"input": 0, "output": 0}},
        {"id": "paid-model", "cost": {"input": 3, "output": 15}},
    ],
}


def _client_with(answer: Any, error: Exception | None = None) -> ZenClient:
    client = ZenClient()
    client.call = lambda *a, **kw: (_ for _ in ()).throw(error) if error else answer
    return client


def test_в_списке_только_бесплатные() -> None:
    """Платные модели в списке — это предложение тратить деньги."""
    models = _client_with(MODELS_ANSWER).models()
    ids = {m["id"] for m in models}
    assert ids == {"space-bunny-free", "deepseek-v4-flash-free", "cheap-model"}
    assert "claude-opus-5" not in ids
    assert "paid-model" not in ids


def test_модели_несут_провайдера() -> None:
    """zagent показывает провайдера в списке — отдаём честное имя."""
    models = _client_with(MODELS_ANSWER).models()
    assert all(m["provider"] == "opencode" for m in models)


# ------------------------------------------------------------- разбор ответа


def test_текст_берётся_из_content() -> None:
    answer = Bridge._text_of({"choices": [{"message": {"content": "Да."}}]})
    assert answer == "Да."


def test_пустой_content_берётся_из_размышления() -> None:
    """Так отвечают reasoning-модели: content пуст, а ответ есть."""
    answer = Bridge._text_of({"choices": [{"message": {
        "content": "", "reasoning_content": "Подумал и ответил: Да."}}]})
    assert answer == "Подумал и ответил: Да."


def test_совсем_пустой_ответ_считается_ошибкой() -> None:
    """Иначе агент получит «ответ модели» без единого слова."""
    with pytest.raises(DonorUnavailable):
        Bridge._text_of({"choices": [{"message": {"content": "   "}}]})


def test_текст_ошибки_читается_из_всех_форм() -> None:
    """У zen три разные формы ошибки; молчаливый «HTTP 429» бесполезен."""
    assert _error_message({"error": {"message": "лимит"}}, "x") == "лимит"
    assert _error_message({"error": "строка"}, "x") == "строка"
    assert _error_message({"message": "поле"}, "x") == "поле"
    # Тело приходит текстом: JSON внутри разбирается, а не JSON — берётся
    # как есть.
    assert _error_message('{"error": {"message": "из текста"}}', "x") == "из текста"
    assert _error_message("не json", "x") == "не json"
    assert _error_message("{}", "заглушка") == "заглушка"


# ----------------------------------------------------------------- сервер


@pytest.fixture()
def bridge_server(tmp_path: Path):
    """Мост на случайном порту с заглушкой вместо zen."""
    bridge = Bridge(root=tmp_path, port=_free_port())
    answer = {"choices": [{"message": {"content": "Привет из моста"}}]}

    def fake_chat(model: str, messages: list, max_tokens: int = 0,
                  temperature: float | None = None) -> dict:
        bridge.seen = {"model": model, "messages": messages,
                       "max_tokens": max_tokens}
        return answer

    bridge.zen.chat = fake_chat  # type: ignore[assignment]
    # Запасной путь к локальному opencode в тестах выключен: на этой
    # машине он существует, и проверка ошибки уходила бы в его опрос на
    # две минуты вместо того, чтобы проверять наш код.
    bridge.local.url = ""
    bridge.local.password = ""
    bridge.models = lambda: [{"id": "space-bunny-free", "provider": "opencode",
                              "model": "space-bunny-free", "name": "bunny",
                              "tools": True, "vision": False}]
    assert bridge.start()
    yield bridge
    bridge.stop()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _post(port: int, path: str, payload: dict, headers: dict | None = None,
          timeout: float = 30) -> tuple[int, dict[str, str], dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (resp.status,
                    {k.lower(): v for k, v in resp.headers.items()},
                    json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        return (exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()},
                json.loads(exc.read().decode("utf-8") or "{}"))


def _get(port: int, path: str, timeout: float = 30) -> tuple[int, dict, Any]:
    """GET c разбором JSON там, где ответ заведомо JSON.

    Байты разбираем по месту: страницу (HTML) читать как JSON нельзя, а
    /health и /v1/models обязаны быть объектами — иначе проверка формы
    ответа подменялась бы проверкой «а не вернулось ли что-нибудь».
    """
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                timeout=timeout) as resp:
        raw = resp.read()
        headers = {k.lower(): v for k, v in resp.headers.items()}
    if "json" in headers.get("content-type", ""):
        return resp.status, headers, json.loads(raw.decode("utf-8"))
    return resp.status, headers, raw


def test_chat_отвечает_в_формате_openai(bridge_server: Bridge) -> None:
    """От этого зависит, поймёт ли ответ zagent вообще."""
    status, _h, body = _post(bridge_server.port, "/v1/chat/completions", {
        "model": "space-bunny-free",
        "messages": [{"role": "user", "content": "привет"}],
    })
    assert status == 200
    assert body["object"] == "chat.completion"
    assert body["model"] == "space-bunny-free"
    message = body["choices"][0]["message"]
    assert message["role"] == "assistant"
    assert message["content"] == "Привет из моста"
    # Модель и сообщения дошли до клиента без искажений.
    assert bridge_server.seen["model"] == "space-bunny-free"
    assert bridge_server.seen["messages"][0]["content"] == "привет"


def test_chat_без_сообщений_отвергается(bridge_server: Bridge) -> None:
    """Пустой запрос — ошибка клиента (400), а не падение моста (500)."""
    status, _h, body = _post(bridge_server.port, "/v1/chat/completions",
                             {"model": "space-bunny-free", "messages": []})
    assert status == 400
    assert body["error"]["type"] == "invalid_request_error"


def test_лимит_превращается_в_503_с_retry_after(bridge_server: Bridge) -> None:
    """429 от zen — это «позже», а не «сломано»: код 503 и пауза в ответе."""
    def limited(model: str, messages: list, **kw) -> dict:
        raise DonorUnavailable("zen ответил HTTP 429: лимит",
                               status=503, retry_after=42)

    bridge_server.zen.chat = limited  # type: ignore[assignment]
    status, headers, body = _post(bridge_server.port, "/v1/chat/completions", {
        "model": "space-bunny-free",
        "messages": [{"role": "user", "content": "привет"}],
    })
    assert status == 503
    assert headers["retry-after"] == "42"
    assert "429" in body["error"]["message"]


def test_ошибка_попаадает_в_счётчики(bridge_server: Bridge) -> None:
    """Панель без счётчиков превратилась бы в пустую заглушку."""
    def broken(model: str, messages: list, **kw) -> dict:
        raise DonorUnavailable("zen недоступен")

    bridge_server.zen.chat = broken  # type: ignore[assignment]
    _post(bridge_server.port, "/v1/chat/completions", {
        "model": "space-bunny-free",
        "messages": [{"role": "user", "content": "привет"}],
    })
    snap = bridge_server.snapshot()
    assert snap["requests"] == 1
    assert snap["failures"] == 1
    assert snap["recent"][0]["ok"] is False


def test_модели_отдаются_в_формате_openai(bridge_server: Bridge) -> None:
    status, _h, body = _get(bridge_server.port, "/v1/models")
    assert status == 200
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "space-bunny-free"
    assert body["data"][0]["owned_by"] == "opencode"


def test_панель_открывается_и_содержит_форму(bridge_server: Bridge) -> None:
    status, headers, html = _get(bridge_server.port, "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    page = html.decode("utf-8")
    assert "Донорский шлюз" in page
    assert "/ask" in page


def test_панель_не_показывает_секретов(bridge_server: Bridge) -> None:
    """Даже если пароль подставлен в клиента — наружу он не уходит."""
    from hub.bridge import LocalOpencode

    local = LocalOpencode()
    local.url = "http://127.0.0.1:9"
    local.password = "СЕКРЕТНЫЙПАРОЛЬ"
    bridge_server.local = local
    _status, _h, html = _get(bridge_server.port, "/")
    assert "СЕКРЕТНЫЙПАРОЛЬ" not in html.decode("utf-8")


# ---------------------------------------------------------------- защита


def test_чужая_страница_не_достаёт_до_моста(bridge_server: Bridge) -> None:
    """localhost не спрашивает подтверждения у браузера — закрываем сами."""
    status, _h, _body = _post(
        bridge_server.port, "/v1/chat/completions",
        {"model": "space-bunny-free", "messages": [{"role": "user", "content": "x"}]},
        headers={"Host": "evil.example"},
    )
    assert status == 403
    assert bridge_server.snapshot()["requests"] == 0, \
        "запрос всё-таки ушёл к модели"


def test_свой_host_проходит(bridge_server: Bridge) -> None:
    status, _h, body = _post(
        bridge_server.port, "/v1/chat/completions",
        {"model": "space-bunny-free", "messages": [{"role": "user", "content": "x"}]},
        headers={"Host": f"127.0.0.1:{bridge_server.port}"},
    )
    assert status == 200
    assert body["choices"][0]["message"]["content"]


def test_health_рассказывает_о_состоянии(bridge_server: Bridge) -> None:
    status, _h, body = _get(bridge_server.port, "/health")
    assert status == 200
    assert body["ok"] is True
    assert body["zen"]["base"] == ZEN_BASE
    assert body["zen"]["free_models"] == 1
    assert "errors" in body, "панель без журнала ошибок бесполезна"


# ------------------------------------------------------------- автозапуск


def test_мост_поднимается_и_останавливается(tmp_path: Path) -> None:
    port = _free_port()
    bridge = Bridge(root=tmp_path, port=port)
    assert bridge.start() is True
    try:
        status, _h, _body = _get(port, "/health")
        assert status == 200
    finally:
        bridge.stop()
    # После остановки порт свободен — иначе повторный запуск невозможен.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_занятый_порт_не_поднимает_мост(tmp_path: Path) -> None:
    """Мост — вспомогательный инструмент: занятый порт не должен ломать
    запуск основной программы."""
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        assert Bridge(root=tmp_path, port=port).start() is False
    finally:
        holder.close()


def test_панель_и_шлюз_на_разных_портах() -> None:
    """Порт моста не должен совпадать с основным: это разные инструменты."""
    from hub.bridge import DEFAULT_PORT
    assert DEFAULT_PORT != 8783