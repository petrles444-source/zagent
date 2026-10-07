"""Отладчик: статус всех моделей и разговор со всеми разом.

Что здесь проверяется и почему именно так:

* **строка на каждую модель, а не «шлюз отвечает».** Прежде человек
  должен был кликнуть по моделям по очереди и ждать таймаут на каждой,
  чтобы понять, кто вообще живой. Теперь состояние собирается из
  остывания и последних запросов;
* **остывание видно раньше успеха.** Если модель последний раз ответила,
  но сейчас на остывании, в таблице должно быть «на остывании»: иначе
  строка «отвечает» противоречит тому, что задача её не выбирает;
* **отказ одной модели не уносит остальные.** Ровно этот случай и
  открывают в отладчике — когда сломалось;
* **модель на остывании не занимает очередь на таймаут**, но остаётся
  в таблице со своей причиной, а не исчезает;
* **мост может быть не поднят.** Тогда ответ — 200 с честным описанием
  состояния: пустая таблица в панели читалась бы как «моделей нет»;
* **сервер сводит донорские модели и Ollama в один ответ**, потому что
  браузер о порте 8784 ничего не знает.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from hub.bridge import ASK_ALL_TEXT, Bridge, DonorUnavailable, ModelBlocked  # noqa: E402
from hub.ui import UI_HTML  # noqa: E402


# ------------------------------------------------------------------ заготовки


def make_bridge(models: list[dict[str, Any]]) -> Bridge:
    """Мост без сети: список моделей подставлен, обращения к zen запрещены."""
    bridge = Bridge()
    bridge.zen.models = lambda: list(models)  # type: ignore[method-assign]
    return bridge


def models(*ids: str) -> list[dict[str, Any]]:
    return [{"id": m, "provider": "opencode"} for m in ids]


def script() -> str:
    src = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
    _, _, rest = src.partition("</style>")
    return rest.partition("<script>")[2].partition("</script>")[0]


# ==================================================================== статус


def test_у_каждой_модели_есть_строка() -> None:
    """Главное обещание панели: видно каждую модель, а не «шлюз отвечает»."""
    data = make_bridge(models("space-bunny-free", "mimo-v2.5-free")).status()
    assert [row["id"] for row in data["models"]] == ["space-bunny-free", "mimo-v2.5-free"]


def test_непроверенная_модель_помечена_не_проверенной() -> None:
    """Молчаливая строка без состояния выглядит как «работает»."""
    rows = make_bridge(models("a")).status()["models"]
    assert rows[0]["state"] == "unknown"


def test_остывание_видно_и_несёт_причину() -> None:
    bridge = make_bridge(models("a"))
    with pytest.raises(ModelBlocked):
        # fail() сам выводит модель из ротации и сообщает об этом.
        bridge.health.fail("a", "free tier can only be used from within OpenCode")
    bridge.record("a", 1.0, True, via="zen")
    row = bridge.status()["models"][0]
    assert row["state"] == "cooling", "последний успех не должен прятать остывание"
    assert "within OpenCode" in row["reason"]
    assert row["cooldown_left_s"] > 0


def test_последний_успех_даёт_отвечает_и_время() -> None:
    bridge = make_bridge(models("a"))
    bridge.record("a", 1.5, True, via="zen")
    row = bridge.status()["models"][0]
    assert row["state"] == "ok"
    assert row["last_ms"] == 1500
    assert row["last_via"] == "zen"


def test_последний_отказ_даёт_отказала() -> None:
    bridge = make_bridge(models("a"))
    bridge.record("a", 2.0, False, "HTTP 503: модель недоступна")
    row = bridge.status()["models"][0]
    assert row["state"] == "fail"
    assert "503" in row["reason"]


def test_последний_из_нескольких_выигрывает() -> None:
    """recent[0] — самый свежий, иначе панель показывала бы старый отказ."""
    bridge = make_bridge(models("a"))
    bridge.record("a", 1.0, False, "первый отказ")
    bridge.record("a", 2.0, True, via="zen")
    assert bridge.status()["models"][0]["state"] == "ok"


def test_статус_не_падает_на_модели_без_идентификатора() -> None:
    """Мусорный каталог не должен ронять всю таблицу."""
    data = make_bridge([{"id": ""}, {"provider": "x"}]).status()
    assert data["models"] == []


def test_пустой_каталог_даёт_пустую_таблицу_и_не_ошибку() -> None:
    """Мост без моделей — состояние, а не сбой."""
    data = make_bridge([]).status()
    assert data["ok"] is True
    assert data["models"] == []


# ============================================================== разговор со всеми


def test_вопрос_уходит_всем_моделям() -> None:
    bridge = make_bridge(models("a", "b", "c"))
    seen: list[str] = []
    lock = threading.Lock()

    def fake_ask(model, messages, max_tokens=0, temperature=None,
                 timeout=120.0):
        with lock:
            seen.append(model)
        assert messages[0]["content"] == "привет"
        return "ок", 0.2, "zen"

    bridge.ask = fake_ask  # type: ignore[method-assign]
    data = bridge.ask_all("привет")
    assert sorted(seen) == ["a", "b", "c"]
    assert data["asked"] == 3
    assert data["answered"] == 3


def test_одна_модель_на_остывании_не_портит_остальные() -> None:
    """Остывшая модель отвечает мгновенно и остаётся в таблице."""
    bridge = make_bridge(models("good", "cold"))

    def fake_ask(model, messages, max_tokens=0, temperature=None,
                 timeout=120.0):
        if model == "cold":
            # Так мост сообщает о models на остывании: мгновенно и без сети.
            raise ModelBlocked("cold", "not available in your country", 300.0)
        return "ок", 0.1, "zen"

    bridge.ask = fake_ask  # type: ignore[method-assign]
    rows = {r["id"]: r for r in bridge.ask_all("привет")["results"]}
    assert rows["good"]["ok"] is True
    assert rows["cold"]["ok"] is False
    assert rows["cold"]["state"] == "cooling"
    assert "country" in rows["cold"]["error"]


def test_отказ_одной_модели_не_уносит_весь_опрос() -> None:
    """Ровно этот случай и открывают в отладчике: что-то сломалось."""
    bridge = make_bridge(models("ok-one", "bad-one"))

    def fake_ask(model, messages, max_tokens=0, temperature=None,
                 timeout=120.0):
        if model == "bad-one":
            raise DonorUnavailable("zen недоступен", status=503)
        return "ок", 0.1, "zen"

    bridge.ask = fake_ask  # type: ignore[method-assign]
    rows = {r["id"]: r for r in bridge.ask_all("привет")["results"]}
    assert rows["ok-one"]["ok"] is True
    assert rows["bad-one"]["ok"] is False
    assert "zen недоступен" in rows["bad-one"]["error"]


def test_неизвестная_ошибка_тоже_даёт_строку_а_не_исключение() -> None:
    """Внутренний баг одной модели не должен ронять панель целиком."""
    bridge = make_bridge(models("boom", "fine"))

    def fake_ask(model, messages, max_tokens=0, temperature=None,
                 timeout=120.0):
        if model == "boom":
            raise RuntimeError("AttributeError: NoneType")
        return "ок", 0.1, "zen"

    bridge.ask = fake_ask  # type: ignore[method-assign]
    rows = {r["id"]: r for r in bridge.ask_all("привет")["results"]}
    assert rows["boom"]["ok"] is False
    assert "AttributeError" in rows["boom"]["error"]
    assert rows["fine"]["ok"] is True


def test_вопрос_идёт_параллельно_а_не_по_очереди() -> None:
    """Очередь дала бы сумму таймаутов — на бесплатных моделях это минуты."""
    bridge = make_bridge(models(*[f"m{i}" for i in range(4)]))
    started = time.perf_counter()

    def fake_ask(model, messages, max_tokens=0, temperature=None,
                 timeout=120.0):
        time.sleep(0.3)
        return "ок", 0.3, "zen"

    bridge.ask = fake_ask  # type: ignore[method-assign]
    bridge.ask_all("привет")
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"опрос шёл по очереди: {elapsed:.2f} с на 4 модели по 0.3 с"


def test_пустой_вопрос_отвергается() -> None:
    bridge = make_bridge(models("a"))
    try:
        bridge.ask_all("   ")
    except ValueError as exc:
        assert "пустой вопрос" in str(exc)
    else:
        raise AssertionError("пустой вопрос должен отвергаться, а не уходить в сеть")


def test_список_моделей_можно_задать_руками() -> None:
    bridge = make_bridge(models("a", "b", "c"))
    seen: list[str] = []
    bridge.ask = lambda m, msg, **kw: (seen.append(m), ("ок", 0.1, "zen"))[1]  # type: ignore[method-assign]
    bridge.ask_all("привет", models=["b"])
    assert seen == ["b"]


def test_список_из_пустых_строк_даёт_нулевой_опрос() -> None:
    bridge = make_bridge(models("a"))
    data = bridge.ask_all("привет", models=["", "  "])
    assert data["asked"] == 0
    assert data["results"] == []


def test_результаты_отсортированы_ответами_вперёд() -> None:
    """Отвечающие должны быть сверху: их ищут глазами первыми."""
    bridge = make_bridge(models("bad", "good"))
    bridge.ask = lambda m, msg, **kw: (  # type: ignore[method-assign]
        ("ок", 0.1, "zen") if m == "good"
        else (_ for _ in ()).throw(DonorUnavailable("нет", status=503)))
    rows = bridge.ask_all("привет")["results"]
    assert rows[0]["id"] == "good"


def test_длинный_ответ_обрезается() -> None:
    """Вся таблица ответов не должна расползаться на экраны."""
    bridge = make_bridge(models("a"))
    bridge.ask = lambda m, msg, **kw: ("я" * (ASK_ALL_TEXT * 3), 0.1, "zen")  # type: ignore[method-assign]
    assert len(bridge.ask_all("привет")["results"][0]["answer"]) == ASK_ALL_TEXT


def test_модель_бросившая_modelblocked_даёт_остывание_не_падение() -> None:
    bridge = make_bridge(models("a"))

    def fake_ask(model, messages, max_tokens=0, temperature=None,
                 timeout=120.0):
        raise ModelBlocked("a", "на остывании", 300.0)

    bridge.ask = fake_ask  # type: ignore[method-assign]
    row = bridge.ask_all("привет")["results"][0]
    assert row["state"] == "cooling"
    assert row["cooldown_left_s"] == 300


# ==================================================================== сервер


def test_сервер_сводит_мост_и_ollama_в_один_ответ() -> None:
    """Браузер о порте 8784 не знает: сводит сервер."""
    from hub.server import Handler

    handler = object.__new__(Handler)
    handler._bridge_call = lambda path, payload=None, timeout=None: {  # type: ignore[method-assign]
        "ok": True, "port": 8784, "uptime_s": 10, "requests": 3, "failures": 1,
        "local_opencode": {"ready": True},
        "models": [{"id": "space-bunny-free", "state": "ok", "provider": "opencode"}],
    }
    handler._local_models = lambda body: {  # type: ignore[method-assign]
        "ok": True, "running": True,
        "models": [{"name": "qwen2.5:7b"}, {"name": "phi3:mini"}],
    }
    data = handler._bridge_status()
    ids = [row["id"] for row in data["models"]]
    assert ids == ["space-bunny-free", "qwen2.5:7b", "phi3:mini"]
    sources = {row["id"]: row["source"] for row in data["models"]}
    assert sources["space-bunny-free"] == "bridge"
    assert sources["phi3:mini"] == "ollama", "у всех строк должен быть source"
    assert data["bridge"]["ok"] is True
    assert data["local_llm"]["running"] is True


def test_локальные_модели_помечены_как_локальные() -> None:
    from hub.server import Handler

    handler = object.__new__(Handler)
    handler._bridge_call = lambda path, payload=None, timeout=None: {  # type: ignore[method-assign]
        "ok": True, "models": []}
    handler._local_models = lambda body: {  # type: ignore[method-assign]
        "ok": True, "running": True, "models": [{"name": "qwen2.5:7b"}]}
    rows = handler._bridge_status()["models"]
    assert rows[0]["provider"] == "ollama"
    assert rows[0]["state"] == "local"
    assert rows[0]["source"] == "ollama"


def test_выключенный_мост_даёт_200_и_честное_состояние() -> None:
    """Пустая таблица без причины читалась бы как «моделей нет»."""
    from hub.server import Handler

    handler = object.__new__(Handler)
    handler._bridge_call = lambda path, payload=None, timeout=None: {  # type: ignore[method-assign]
        "ok": False, "error": "мост не отвечает: ConnectError"}
    handler._local_models = lambda body: {  # type: ignore[method-assign]
        "ok": True, "running": False, "models": [], "error": "Ollama не запущен"}
    data = handler._bridge_status()
    assert data["ok"] is True
    assert data["bridge"]["ok"] is False
    assert "не отвечает" in data["bridge"]["error"]
    assert data["local_llm"]["running"] is False


def test_ollama_выключен_молча_не_ломает_таблицу() -> None:
    from hub.server import Handler

    handler = object.__new__(Handler)
    handler._bridge_call = lambda path, payload=None, timeout=None: {  # type: ignore[method-assign]
        "ok": True, "models": [{"id": "a", "state": "ok"}]}
    handler._local_models = lambda body: {  # type: ignore[method-assign]
        "ok": True, "running": False, "models": [], "error": "Ollama не запущен"}
    rows = handler._bridge_status()["models"]
    assert [row["id"] for row in rows] == ["a"]


def test_пустой_вопрос_к_мосту_не_уходит() -> None:
    from hub.server import Handler

    handler = object.__new__(Handler)
    called: list[str] = []
    handler._bridge_call = lambda path, payload=None, timeout=None: (  # type: ignore[method-assign]
        called.append(path), {"ok": True})[1]
    assert handler._models_ask_all({"text": "  "})["ok"] is False
    assert not called, "пустой вопрос не должен долетать до моста"


def test_вопрос_передаётся_мосту_текстом() -> None:
    from hub.server import Handler

    handler = object.__new__(Handler)
    got: list[tuple] = []

    def fake(path, payload=None, timeout=None):
        got.append((path, payload, timeout))
        return {"ok": True, "asked": 2, "answered": 2, "results": []}

    handler._bridge_call = fake  # type: ignore[method-assign]
    handler._models_ask_all({"text": "привет", "models": ["a", "", "b"]})
    path, payload, timeout = got[0]
    assert path == "/ask_all"
    assert payload["text"] == "привет"
    assert payload["models"] == ["a", "b"]
    assert timeout > 180, "таймаут запроса должен быть больше таймаута моделей"


def test_кривой_таймаут_не_ломает_запрос() -> None:
    """Не число в таймауте не должно ронять кнопку в отладчике."""
    from hub.server import Handler

    handler = object.__new__(Handler)
    seen: list[float] = []
    handler._bridge_call = lambda path, payload=None, timeout=None: (  # type: ignore[method-assign]
        seen.append(payload["timeout"]), {"ok": True})[1]
    handler._models_ask_all({"text": "привет", "timeout": "быстро"})
    assert seen == [180.0]


def test_маршруты_зарегистрированы() -> None:
    """Кнопки без маршрута показывали бы вечное «плохой ответ сервера»."""
    src = (ROOT / "hub" / "server.py").read_text(encoding="utf-8")
    assert '"/api/models/status"' in src
    assert '"/api/models/ask_all"' in src
    assert 'parsed.path == "/api/models/status"' in src


# ================================================================ интерфейс


def test_в_отладчике_есть_кнопки_и_поле_вопроса() -> None:
    assert 'id="modelsBox"' in UI_HTML
    assert 'onclick="modelsStatus()"' in UI_HTML
    assert 'onclick="modelsAskAll()"' in UI_HTML
    assert 'id="modelsAsk"' in UI_HTML


def test_панель_моделей_в_режиме_разработчика() -> None:
    """Иначе это отдельная страница, а человек ищет в отладчике."""
    body = UI_HTML
    dev = body.index('id="devBox"')
    assert body.index('id="modelsBox"') > dev, "панель моделей должна быть рядом с отладчиком"


def test_кнопка_спрашивает_мост_через_сервер() -> None:
    body = script()
    assert "/api/models/ask_all" in body
    assert "/api/models/status" in body


def test_пустой_вопрос_не_отправляется() -> None:
    body = script()
    assert "вопрос пустой" in body


def test_выключенный_мост_показывается_словами() -> None:
    """Пустой список без слов — это «ничего не работает» без причины."""
    body = script()
    assert "Моделей в таблице нет" in body
    assert "Мост поднимается вместе с основным сервером" in body


def test_результат_показывает_сколько_ответили() -> None:
    body = script()
    assert "Ответили" in body and "из" in body


def test_стили_таблицы_моделей_есть() -> None:
    """Без стилей таблица рисуется как лестница блоков без рамок."""
    css = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8").partition("</style>")[0]
    for name in (".modelsTable", ".modelsRow", ".modelsName"):
        assert name in css, f"нет стиля {name}"


def test_цвета_таблицы_из_токенов_темы() -> None:
    """Свои цвета в блоке — то же самое, что мы уже чинили в localBubble."""
    css = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8").partition("</style>")[0]
    start = css.index(".modelsTable")
    chunk = css[start:start + 700]
    assert "#" not in chunk.replace("srgb", ""), "в стилях таблицы не должно быть своих цветов"
