"""Retry-After: от заголовка ответа до карантина ключа.

Провайдер, отказавший с `429` или `503`, сам говорит, сколько ждать. Раньше
это игнорировалось: ключ уходил на час по умолчанию, и аккаунт с минутной
квотой простаивал в пятьдесят раз дольше, чем просили.

Цепочка, которую проверяют тесты файла:

    заголовок → openai_compat.rate_limits → result["limits"]["retry_after_s"]
    → failover._note_result → keyring.penalize → blocked_until ключа

Каждое звено проверяется и само по себе, и в боевом пути `AutoCaller.ask`:
заголовок, который парсится, но не доходит до ключа, — тот же отказ, что и
заголовок, который не парсится вовсе.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from hub.failover import AutoCaller, FailoverError
from hub.keyring import (
    DEFAULT_QUARANTINE,
    EMPTY_ACCOUNT,
    REGISTRY,
    KeyRing,
    retry_after_of,
)
from hub.selector import Mode, Selector
from providers.openai_compat import OpenAICompatProvider, retry_after_seconds


# ============================================================ заголовок ответа


def _chat(status: int, headers: dict[str, str] | None = None,
          body: str = '{"error": {"message": "rate limit exceeded"}}') -> dict:
    """Ответ провайдера из заготовленного HTTP-ответа. Сеть не нужна."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers or {}, text=body)

    async def run() -> dict:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            provider = OpenAICompatProvider("t", "https://example.test/v1", "k",
                                            client=client)
            return await provider.chat("m", [{"role": "user", "content": "hi"}])
        finally:
            await client.aclose()

    return asyncio.run(run())


def test_429_с_заголовком_кладёт_ожидание_в_лимиты() -> None:
    """Самое главное звено: заголовок обязан стать полем результата."""
    result = _chat(429, {"Retry-After": "42",
                         "x-ratelimit-remaining-requests": "0"})
    assert result["status"] == 429
    assert result["error"], "429 обязан превращаться в текст ошибки"
    assert result["limits"]["retry_after_s"] == 42.0


def test_503_с_заголовком_кладёт_ожидание_в_лимиты() -> None:
    """503 — тоже просьба подождать, и она гнётся тем же путём."""
    result = _chat(503, {"Retry-After": "30"},
                   body='{"error": {"message": "overloaded"}}')
    assert result["status"] == 503
    assert result["limits"]["retry_after_s"] == 30.0


def test_без_заголовка_поля_нет() -> None:
    """Отсутствие заголовка — не ноль ожидания, а именно отсутствие."""
    result = _chat(429)
    assert "retry_after_s" not in result["limits"]


def test_дата_вместо_секунд() -> None:
    """RFC 9110 позволяет отвечать датой, а не числом секунд."""
    moment = datetime.now(timezone.utc) + timedelta(seconds=300)
    result = _chat(429, {"Retry-After": format_datetime(moment)})
    wait = result["limits"].get("retry_after_s")
    assert wait is not None
    assert 200 < wait <= 300, wait


def test_прошедшая_дата_не_превращается_в_минус() -> None:
    """Дата в прошлом дала бы отрицательное ожидание — то есть снятие
    карантина. Пусть сработает час по умолчанию."""
    moment = datetime.now(timezone.utc) - timedelta(seconds=60)
    result = _chat(429, {"Retry-After": format_datetime(moment)})
    assert "retry_after_s" not in result["limits"]


def test_нечисло_не_попадает_в_ожидание() -> None:
    """`nan` проходит проверку `<= 0` молча и пожал бы ключ в карантин со
    значением NaN — то есть не выпустил бы его из ротации вообще."""
    for bad in ("nan", "inf", "-inf"):
        result = _chat(429, {"Retry-After": bad})
        assert "retry_after_s" not in result["limits"], bad
    # Нечисловые значения httpx отвергает ещё на уровне заголовка (они не
    # ложатся в ASCII), поэтому мусор проверяется прямо на разборщике.
    for bad in ("мусор", "", None):
        assert retry_after_seconds({"retry-after": bad}) is None, repr(bad)


# ============================================================ поле результата


def test_retry_after_of_читает_только_смысл_числа() -> None:
    """Единственное место, откуда ожидание достаётся из результата."""
    assert retry_after_of(None) is None
    assert retry_after_of({}) is None
    assert retry_after_of({"requests_remaining": 5}) is None
    assert retry_after_of({"retry_after_s": 12.5}) == 12.5
    assert retry_after_of({"retry_after_s": "7"}) == 7.0
    # Ноль — не «повтори сейчас», а отсутствие смысла: по нулю ключ
    # снялся бы с карантина сам, в уже закрытую дверь.
    assert retry_after_of({"retry_after_s": 0}) is None
    assert retry_after_of({"retry_after_s": -3}) is None
    assert retry_after_of({"retry_after_s": float("nan")}) is None
    assert retry_after_of({"retry_after_s": float("inf")}) is None
    assert retry_after_of({"retry_after_s": "мусор"}) is None


# ============================================================ карантин ключа


def test_лимит_с_ожиданием_держит_ключ_ровно_сколько_сказал_провайдер() -> None:
    ring = KeyRing(keys=["a", "b"])
    ring.note_error("a", "429 лимит запросов, попробуйте позже", retry_after=90)
    assert ring.is_blocked("a")
    left = ring.cooldown_left("a")
    assert 84 <= left <= 90, left
    assert ring.stats()["keys"][0]["reason"] == "429"

    # Без заголовка — час, как и раньше: не сообщили, не выдумываем.
    ring.note_error("b", "429 лимит запросов, попробуйте позже")
    assert ring.cooldown_left("b") > DEFAULT_QUARANTINE - 60


def test_ожидание_не_лечит_чужие_ошибки() -> None:
    """401 и «нет баланса» ожиданием не лечатся, каким бы коротким оно ни было."""
    ring = KeyRing(keys=["a", "b"])
    ring.note_error("a", "HTTP 401: invalid api key", retry_after=5)
    assert ring.cooldown_left("a") > DEFAULT_QUARANTINE

    ring.note_error("b", "Insufficient balance. Please recharge.",
                    retry_after=5)
    left = ring.cooldown_left("b")
    assert EMPTY_ACCOUNT - 5 <= left <= EMPTY_ACCOUNT + 5, left


def test_ожидание_обрезается_сверху() -> None:
    """Retry-After в месяц не должен закрыть шлюз навсегда."""
    ring = KeyRing(keys=["a"])
    ring.note_error("a", "429 лимит запросов", retry_after=10 ** 9)
    assert ring.cooldown_left("a") <= 7 * 24 * 3600


# ============================================================ боевой путь


class _Spec:
    tier, vision, tools = 1, False, True


class _Book:
    def get(self, gateway: str, model: str) -> _Spec:
        return _Spec()


class _Model:
    def __init__(self, ref: str, gateway_id: str, model_id: str) -> None:
        self.ref, self.gateway_id, self.model_id = ref, gateway_id, model_id


class _SelectorRegistry:
    """То, что `AutoCaller` ждёт от реестра моделей: модели и шлюзы."""

    def __init__(self, models: list[_Model], gateways: list[dict]) -> None:
        self.chat_models = models
        self.gateways = gateways


def _gateway(gateway_id: str, keys: list[str]) -> dict:
    return {"id": gateway_id, "api_keys": list(keys), "api_key": keys[0],
            "resolved_url": "https://example.test/v1"}


def _selector(gateway_id: str, keys: list[str]) -> Selector:
    """Селектор с одной моделью в ручном режиме: хопы детерминированы."""
    model = _Model(f"{gateway_id}/модель", gateway_id, "модель")
    registry = _SelectorRegistry([model], [_gateway(gateway_id, keys)])
    return Selector(registry, _Book(), mode=Mode.MANUAL,
                    manual_ref=model.ref)


def _fake(monkeypatch: pytest.MonkeyPatch, answers: list[dict],
          calls: list[str],
          on_call: Any = None) -> None:
    """Подменить клиента шлюза: он записывает ключи и отдаёт заготовки.

    `on_call` вызывается перед ответом с номером попытки — чтобы проверить
    состояние системы *в момент* вызова, а не после всего сценария.
    """

    class _Provider:
        def __init__(self, gateway_id: str, base_url: str, api_key: str = "",
                     **kw: Any) -> None:
            self.api_key = api_key

        async def chat(self, model_id: str, messages: Any,
                       **kw: Any) -> dict:
            calls.append(self.api_key)
            index = min(len(calls) - 1, len(answers) - 1)
            if on_call is not None:
                on_call(index)
            return dict(answers[index])

    monkeypatch.setattr("hub.failover.OpenAICompatProvider", _Provider)


def _ask(selector: Selector) -> None:
    """Вызов, который обязан закончиться FailoverError: ответы отказные."""
    caller = AutoCaller(selector)
    with pytest.raises(FailoverError):
        asyncio.run(caller.ask([{"role": "user", "content": "привет"}]))


LIMITED = {
    "error": "429 лимит запросов, попробуйте позже",
    "status": 429,
    "limits": {"retry_after_s": 40.0, "requests_remaining": 0},
    "text": "",
    "duration_ms": 5,
}


def test_429_с_ожиданием_уводит_ключ_и_останавливает_повторы(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Ключ получает бэкофф до указанного времени и не крутится вхолостую."""
    gateway_id, keys = "ra-429-single", ["ra-s1"]
    calls: list[str] = []
    _fake(monkeypatch, [LIMITED], calls)
    selector = _selector(gateway_id, keys)

    _ask(selector)

    ring = REGISTRY.ring(gateway_id, keys)
    assert ring.is_blocked("ra-s1"), "ключ не уведён в карантин"
    left = ring.cooldown_left("ra-s1")
    assert 34 <= left <= 40, f"взято {left} с вместо 40 от провайдера"
    assert ring.stats()["keys"][0]["reason"] == "429"
    assert calls == ["ra-s1"]

    # Повторный вызов не должен даже доставать провайдера: ключей нет.
    _ask(selector)
    assert calls == ["ra-s1"], "выбитый ключ повторно использован"


def test_вместо_выбитого_ключа_берётся_соседний(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Два аккаунта: первый выбит по 429 — второй обязан принять запрос.

    И модель при этом не должна стоять в карантине *в момент* второго
    запроса: виноват ключ, не модель, и пауза за чужую квоту убила бы
    живую модель ровно на время, когда она одна и нужна.
    """
    gateway_id, keys = "ra-429-double", ["ra-d1", "ra-d2"]
    selector = _selector(gateway_id, keys)
    ref = f"{gateway_id}/модель"
    cooldown_on_call: list[float] = []

    def probe(index: int) -> None:
        cooldown_on_call.append(selector.states[ref].cooldown_until)

    calls: list[str] = []
    _fake(monkeypatch, [LIMITED], calls, on_call=probe)

    _ask(selector)

    assert calls == ["ra-d1", "ra-d2"], "взяты не разные ключи"
    ring = REGISTRY.ring(gateway_id, keys)
    assert ring.is_blocked("ra-d1") and ring.is_blocked("ra-d2")
    assert 34 <= ring.cooldown_left("ra-d1") <= 40
    # Второй запрос ушёл, значит модель к тому моменту была доступна.
    assert cooldown_on_call[1] == 0.0, "модель ушла в карантин из-за ключа"


def test_429_без_заголовка_держит_ключ_час(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Не сообщили — ждём как раньше, а не ноль секунд."""
    gateway_id, keys = "ra-429-noheader", ["ra-n1"]
    answer = dict(LIMITED)
    answer["limits"] = {"requests_remaining": 0}
    calls: list[str] = []
    _fake(monkeypatch, [answer], calls)
    selector = _selector(gateway_id, keys)

    _ask(selector)

    ring = REGISTRY.ring(gateway_id, keys)
    assert ring.cooldown_left("ra-n1") > DEFAULT_QUARANTINE - 60


def test_503_с_ожиданием_уводит_ключ(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """503 с Retry-After: ключ тоже обязан получить бэкофф — иначе следующий
    хоп берёт тот же ключ и получает тот же 503."""
    gateway_id, keys = "ra-503", ["ra-w1"]
    answer = {"error": "Модель модель временно недоступна", "status": 503,
              "limits": {"retry_after_s": 30.0}, "text": "", "duration_ms": 5}
    calls: list[str] = []
    _fake(monkeypatch, [answer], calls)
    selector = _selector(gateway_id, keys)

    _ask(selector)

    ring = REGISTRY.ring(gateway_id, keys)
    assert ring.is_blocked("ra-w1"), "503 с ожиданием не увёл ключ"
    left = ring.cooldown_left("ra-w1")
    assert 24 <= left <= 30, left
    assert ring.stats()["keys"][0]["reason"] == "503", (
        "причина должна быть «503», а не «429»: ищут не квоту, а шлюз")
    assert calls == ["ra-w1"]


def test_503_без_заголовка_ключ_не_каранится(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Провайдер не просил ждать — распоряжаться ключом нечем."""
    gateway_id, keys = "ra-503-quiet", ["ra-q1"]
    answer = {"error": "Модель модель временно недоступна", "status": 503,
              "limits": {}, "text": "", "duration_ms": 5}
    calls: list[str] = []
    _fake(monkeypatch, [answer], calls)
    selector = _selector(gateway_id, keys)

    _ask(selector)

    ring = REGISTRY.ring(gateway_id, keys)
    assert not ring.is_blocked("ra-q1"), "ключ уведён без просьбы провайдера"
    # А вот модель селектор карантинит сам — это его зона ответственности.
    state = selector.states[f"{gateway_id}/модель"]
    assert state.cooldown_until > 0.0


def test_повтор_после_пустого_ответа_тоже_уважает_ожидание(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Вторая копия учёта в failover: повтор с увеличенным бюджетом мог
    пометить ключ по часу, хотя провайдер просил полминуты."""
    gateway_id, keys = "ra-empty-retry", ["ra-e1"]
    empty = {"error": None, "status": 200, "text": "", "limits": {},
             "duration_ms": 3}
    limited = dict(LIMITED)
    limited["limits"] = {"retry_after_s": 33.0}
    calls: list[str] = []
    _fake(monkeypatch, [empty, limited], calls)
    selector = _selector(gateway_id, keys)

    _ask(selector)

    assert len(calls) == 2, "повтор после пустого ответа не состоялся"
    ring = REGISTRY.ring(gateway_id, keys)
    left = ring.cooldown_left("ra-e1")
    assert ring.is_blocked("ra-e1")
    assert 27 <= left <= 33, f"повтор взял {left} с вместо 33 от провайдера"


# ============================================================ умный выбор ключа


def test_failover_берёт_аккаунт_с_большим_остатком(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Аккаунт с двумя оставшимися запросами не должен получать работу
    наравне с аккаунтом, где их пятьсот."""
    gateway_id, keys = "ra-best", ["ra-b1", "ra-b2"]
    ring = REGISTRY.ring(gateway_id, keys)
    ring.note_quota("ra-b1", {"requests_remaining": 2})
    ring.note_quota("ra-b2", {"requests_remaining": 500})

    calls: list[str] = []
    _fake(monkeypatch, [{
        "text": "готово", "error": None, "status": 200, "duration_ms": 7,
        "limits": {"requests_remaining": 499},
    }], calls)
    selector = _selector(gateway_id, keys)

    answer = asyncio.run(AutoCaller(selector).ask(
        [{"role": "user", "content": "привет"}]))

    assert answer["status"] in ("ok", "slow")
    assert calls == ["ra-b2"], "работу получил не самый полный аккаунт"
    stats = ring.stats()["keys"]
    assert stats[0]["used"] == 0 and stats[1]["used"] == 1, (
        "выдача ключа обязана попадать в счётчик расхода")


def test_ноль_остатка_не_получает_работу(
        monkeypatch: pytest.MonkeyPatch) -> None:
    gateway_id, keys = "ra-zero", ["ra-z1", "ra-z2"]
    ring = REGISTRY.ring(gateway_id, keys)
    ring.note_quota("ra-z1", {"requests_remaining": 0})
    ring.note_quota("ra-z2", {"requests_remaining": 9})

    calls: list[str] = []
    _fake(monkeypatch, [{
        "text": "готово", "error": None, "status": 200, "duration_ms": 7,
        "limits": {},
    }], calls)
    selector = _selector(gateway_id, keys)

    asyncio.run(AutoCaller(selector).ask([{"role": "user", "content": "hi"}]))

    assert calls == ["ra-z2"], "пустой аккаунт получил запрос при полном соседе"


def test_без_остатка_круг_остаётся_кругом(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Провайдер остаток не сообщает — выбор обязан чередоваться, а не
    липнуть к одному ключу. Здесь и проверяется направление сравнения:
    обратное («наиболее использованный») собрало бы весь трафик на одном
    аккаунте, а остальные простаивали бы."""
    gateway_id, keys = "ra-round", ["ra-r1", "ra-r2", "ra-r3"]
    answer = {"text": "готово", "error": None, "status": 200,
              "duration_ms": 7, "limits": {}}
    calls: list[str] = []
    _fake(monkeypatch, [answer], calls)
    selector = _selector(gateway_id, keys)
    for _ in range(3):
        asyncio.run(AutoCaller(selector).ask(
            [{"role": "user", "content": "hi"}]))

    assert calls == ["ra-r1", "ra-r2", "ra-r3"], calls
    ring = REGISTRY.ring(gateway_id, keys)
    used = [row["used"] for row in ring.stats()["keys"]]
    assert used == [1, 1, 1], used


def test_best_key_возвращает_none_когда_всё_в_карантине() -> None:
    gateway = {"id": "ra-all-blocked", "api_keys": ["ra-a1", "ra-a2"]}
    ring = REGISTRY.ring("ra-all-blocked", gateway["api_keys"])
    ring.penalize("ra-a1", seconds=60, why="429")
    ring.penalize("ra-a2", seconds=60, why="429")
    assert REGISTRY.best_key(gateway) is None
    assert REGISTRY.next_key(gateway) is None


def test_best_key_берёт_наименее_использованный_без_остатка() -> None:
    """Направление выбора при неизвестном остатке.

    Счётчик `used` растёт у выданного ключа, поэтому выбор по «наиболее
    использованному» — это замкнутый круг на одном аккаунте.
    """
    ring = KeyRing(keys=["k1", "k2", "k3"])
    ring.used.update({"k1": 5, "k2": 2})
    key, _note = ring.best_key()
    assert key == "k3", key


def test_best_key_не_выдаёт_ключ_из_карантина() -> None:
    ring = KeyRing(keys=["k1", "k2"])
    ring.penalize("k1", seconds=60, why="429")
    assert ring.take_best() == "k2"
    assert ring.available() == ["k2"]


def test_penalize_через_реестр_ставит_причину() -> None:
    gateway = {"id": "ra-penalize", "api_keys": ["ra-p1"]}
    REGISTRY.penalize(gateway, "ra-p1", 25, why="503")
    ring = REGISTRY.ring("ra-penalize", ["ra-p1"])
    assert ring.is_blocked("ra-p1")
    assert 20 <= ring.cooldown_left("ra-p1") <= 25
    assert ring.stats()["keys"][0]["reason"] == "503"
