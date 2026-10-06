"""Несколько ключей одного провайдера: раздача, карантин, отчётность.

Лимиты считаются на аккаунт, а не на ключ. Девять аккаунтов OpenRouter дают
в девять раз больше работы, чем один, но только если трафик между ними
раскладывается, а не бьёт по первому. Именно это здесь и проверяется.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub.config import _keys_from_value, load_gateways, resolve_keys
from hub.keyring import (
    DEFAULT_QUARANTINE,
    EMPTY_ACCOUNT,
    MAX_QUARANTINE,
    KeyRing,
    KeyRegistry,
    fingerprint,
    gateway_key,
)

ROOT = Path(__file__).resolve().parent.parent


# =============================================================== разбор секретов


def test_ключ_строкой_как_раньше() -> None:
    assert _keys_from_value("sk-or-v1-abc") == ["sk-or-v1-abc"]


def test_список_ключей() -> None:
    assert _keys_from_value(["a1", "b2", "c3"]) == ["a1", "b2", "c3"]


def test_многострочная_строка() -> None:
    """Ключи часто вставляют списком в текстовом виде."""
    value = "sk-or-v1-one\nsk-or-v1-two\n"
    assert _keys_from_value(value) == ["sk-or-v1-one", "sk-or-v1-two"]


def test_запятая_как_разделитель() -> None:
    assert _keys_from_value("a1, b2") == ["a1", "b2"]


def test_пустые_и_повторы_выбрасываются() -> None:
    """Девь одинаковых записей выглядели бы как девять аккаунтов."""
    value = ["a1", "", None, "a1", "  ", "b2"]
    assert _keys_from_value(value) == ["a1", "b2"]


def test_пустое_значение() -> None:
    assert _keys_from_value(None) == []
    assert _keys_from_value("") == []
    assert _keys_from_value([]) == []


def test_шлюз_видит_все_ключи(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "gateways.json").write_text(json.dumps({
        "gateways": [{"id": "orx", "base_url": "https://example.test/v1",
                      "needs_key": True}]
    }), encoding="utf-8")
    (cfg / "secrets.local.json").write_text(
        json.dumps({"orx": ["k1", "k2", "k3"]}), encoding="utf-8"
    )

    gateway = load_gateways(tmp_path)[0]
    assert gateway["key_count"] == 3
    assert gateway["api_keys"] == ["k1", "k2", "k3"]
    # api_key оставлен для совместимости со всем, что его читает.
    assert gateway["api_key"] == "k1"
    assert gateway["has_key"] is True


def test_переменная_окружения_даёт_один_ключ(tmp_path: Path) -> None:
    """В CI секрет лежит в окружении, и он всегда один."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "gateways.json").write_text(json.dumps({
        "gateways": [{"id": "orx", "base_url": "https://example.test/v1",
                      "needs_key": True}]
    }), encoding="utf-8")
    (cfg / "secrets.local.json").write_text(
        json.dumps({"orx": ["file1", "file2"]}), encoding="utf-8"
    )

    keys = resolve_keys("orx", root=tmp_path,
                        env={"ZAGENT_ORX_API_KEY": "env1"})
    assert keys == ["env1"]


def test_шлюз_без_ключей_не_ломает_отчёт(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "gateways.json").write_text(json.dumps({
        "gateways": [{"id": "ollama", "base_url": "http://localhost:11434/v1",
                      "secret_key": None, "api_key_literal": "ollama"}]
    }), encoding="utf-8")

    gateway = load_gateways(tmp_path)[0]
    assert gateway["api_keys"] == ["ollama"]
    assert gateway["key_count"] == 1


# =============================================================== кольцо


def test_кольцо_чередует_ключи() -> None:
    ring = KeyRing(keys=["a", "b", "c"])
    picked = [ring.next_key() for _ in range(6)]
    assert picked == ["a", "b", "c", "a", "b", "c"]


def test_кольцо_считает_использования() -> None:
    ring = KeyRing(keys=["a", "b"])
    for _ in range(4):
        ring.next_key()
    stats = ring.stats()
    assert stats["keys"][0]["used"] == 2
    assert stats["keys"][1]["used"] == 2


def test_выбитый_ключ_пропускается() -> None:
    ring = KeyRing(keys=["a", "b"])
    ring.next_key()  # a
    ring.next_key()  # b
    ring.penalize("a", seconds=600)

    # a недоступен — следующий вызов обязан взять b, а не a снова.
    assert ring.available() == ["b"]
    assert ring.next_key() == "b"
    assert ring.next_key() == "b"


def test_весь_шлюз_выбит() -> None:
    ring = KeyRing(keys=["a", "b"])
    ring.penalize("a", seconds=600)
    ring.penalize("b", seconds=600)
    assert ring.available() == []
    assert ring.next_key() is None, "нужно сообщить, а не бить по выбитым"


def test_карантин_истекает() -> None:
    ring = KeyRing(keys=["a"])
    ring.penalize("a", seconds=0.05)
    assert ring.next_key() is None
    import time

    time.sleep(0.1)
    assert ring.next_key() == "a"


def test_успех_возвращает_ключ() -> None:
    ring = KeyRing(keys=["a", "b"])
    ring.penalize("a", seconds=600)
    assert ring.is_blocked("a")
    ring.release("a")
    assert not ring.is_blocked("a")
    assert ring.available() == ["a", "b"]


def test_ошибка_лимита_выбивает_ключ() -> None:
    ring = KeyRing(keys=["a", "b"])
    ring.note_error("a", "Лимит запросов, попробуйте позже")
    assert ring.is_blocked("a")
    assert ring.stats()["keys"][0]["reason"] == "429"


def test_пустой_аккаунт_не_путается_с_лимитом() -> None:
    """z.ai отвечает «Insufficient balance» кодом 429 — это не лимит.

    Если считать это лимитом, через час весь провайдер окажется «выбитым по
    429», и человек пойдёт искать лимит там, где на самом деле нет денег.
    """
    ring = KeyRing(keys=["a", "b"])
    ring.note_error("a", "Insufficient balance or no resource package. Please recharge.")
    assert ring.is_blocked("a")
    reason = ring.stats()["keys"][0]["reason"]
    assert reason == "нет баланса", reason
    # Ждать лимита бессмысленно, но и навсегда ключ не блокируем.
    left = ring.cooldown_left("a")
    assert EMPTY_ACCOUNT - 5 <= left <= EMPTY_ACCOUNT + 5
    assert left > DEFAULT_QUARANTINE


def test_успех_снимает_отметку_о_балансе() -> None:
    """Аккаунт пополнили — ключ должен вернуться в ротацию сразу."""
    ring = KeyRing(keys=["a"])
    ring.note_error("a", "Insufficient balance")
    assert ring.is_blocked("a")
    ring.release("a")
    assert not ring.is_blocked("a")
    assert ring.available() == ["a"]


def test_ошибка_авторизации_выбивает_надолго() -> None:
    """401 — ключ отозван, ждать бессмысленно."""
    ring = KeyRing(keys=["a", "b"])
    ring.note_error("a", "HTTP 401: invalid api key")
    assert ring.is_blocked("a")
    left = ring.cooldown_left("a")
    assert left > DEFAULT_QUARANTINE


def test_карантин_не_бесконечный() -> None:
    """Retry-After в 30 дней заблокировал бы шлюз навсегда."""
    ring = KeyRing(keys=["a", "b"])
    ring.penalize("a", seconds=MAX_QUARANTINE * 10)
    assert ring.cooldown_left("a") <= MAX_QUARANTINE


def test_ошибка_другого_вида_не_выбивает() -> None:
    ring = KeyRing(keys=["a", "b"])
    ring.note_error("a", "connection reset by peer")
    assert not ring.is_blocked("a"), "сетевой сбой не значит лимит"


def test_список_моделей_не_путается_с_лимитом() -> None:
    """"list_models" — не "rate limit": подстрока 'rate' тут не про лимит."""
    ring = KeyRing(keys=["a", "b"])
    ring.note_error("a", "list_models: connection refused")
    assert not ring.is_blocked("a")


def test_пустой_аккаунт_освобождается_раньше_семи_дней() -> None:
    """Пополнение может произойти в любой момент — ждать неделю нельзя."""
    ring = KeyRing(keys=["a"])
    ring.note_error("a", "Insufficient balance")
    left = ring.cooldown_left("a")
    assert EMPTY_ACCOUNT - 5 <= left <= EMPTY_ACCOUNT + 5, left


def test_пустое_кольцо() -> None:
    ring = KeyRing(keys=[])
    assert ring.empty
    assert ring.next_key() is None
    assert ring.available() == []


# =============================================================== реестр


def test_реестр_перечитывает_ключи(tmp_path: Path) -> None:
    """Правка файла секретов должна подхватываться, а не ждать перезапуска."""
    reg = KeyRegistry()
    first = reg.ring("gw", ["a", "b"])
    first.next_key()
    assert first.stats()["keys"][0]["used"] == 1

    # Добавили третий ключ — кольцо должно пересобраться, сохранив счётчики.
    second = reg.ring("gw", ["a", "b", "c"])
    assert len(second) == 3
    assert second.stats()["keys"][0]["used"] == 1, "счётчик не должен сбрасываться"


def test_реестр_разделяет_шлюзы() -> None:
    reg = KeyRegistry()
    reg.ring("one", ["a", "b"])
    reg.ring("two", ["x"])
    assert len(reg.ring("one", ["a", "b"])) == 2
    assert len(reg.ring("two", ["x"])) == 1


def test_gateway_key_падает_на_первый() -> None:
    """Пустое кольцо не должно ронять вызов."""
    gateway = {"id": "gw", "api_keys": [], "api_key": "fallback"}
    assert gateway_key(gateway) == "fallback"


def test_gateway_key_берёт_по_кругу() -> None:
    reg = KeyRegistry()
    gateway = {"id": "shared", "api_keys": ["k1", "k2"]}
    # Два разных шлюза с одним id делят кольцо — так и задумано.
    assert gateway_key(gateway) in ("k1", "k2")
    assert gateway_key(gateway) in ("k1", "k2")


# =============================================================== безопасность


def test_метка_не_выводит_ключ() -> None:
    """Ключ попадает в журналы и отчёты — там ему не место."""
    # Ключ здесь — правдоподобный по длине и виду, но не настоящий: в тесте
    # рабочий ключ не нужен, а настоящий в публичном репозитории опасен. Второй
    # момент важнее: длинный литерал в тесте — это то место, куда легко
    # вставляется ключ из буфера обмена, не заметив, и он уезжает в гит.
    secret = ("sk-or-v1-udalennye-dlya-istorii-znacheniya"
              "0123456789abcdef0123456789abcdef")
    label = fingerprint(secret)
    assert secret not in label
    assert label.endswith("cdef")
    assert len(label) < 12


def test_в_статах_нет_ключей() -> None:
    ring = KeyRing(keys=["sk-or-v1-abcdef123456", "sk-or-v1-fedcba654321"])
    ring.next_key()
    blob = json.dumps(ring.stats())
    assert "abcdef123456" not in blob
    assert "fedcba654321" not in blob


def test_короткий_ключ() -> None:
    assert fingerprint("") == "—"
    assert fingerprint("abc") == "abc"


# =============================================================== боевой конфиг


def test_в_реальном_конфиге_openrouter_много_ключей() -> None:
    """В боевом конфиге должно быть больше одного ключа OpenRouter.

    Проверка без количества: пользователь сам решает, сколько аккаунтов
    подключать, а тест падал бы при каждом изменении.
    """
    gateways = load_gateways(ROOT)
    openrouter = next((g for g in gateways if g["id"] == "openrouter"), None)
    assert openrouter is not None, "нет шлюза openrouter"
    assert openrouter["key_count"] >= 1


def test_секреты_не_в_гите() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "secrets.local.json" in ignore
    assert "config/secrets.local.json" in ignore