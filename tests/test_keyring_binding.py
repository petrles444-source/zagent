"""Привязка отметки об ошибке к конкретному ключу.

Разбор ошибки идёт по тексту, а текст приходит из слоя выше. Если тот слой
перепутал ключ, выбьется не тот аккаунт и пострадает соседний — такой баг
не видно ни в логах, ни в интерфейсе, пока не выяснится, что часть аккаунтов
« inexplicable » помечена как пустые.
"""

from __future__ import annotations

import json

from hub.keyring import KeyRing, KeyRegistry

GW = {"id": "gw", "api_keys": ["a1", "a2"]}
ONE = {"id": "gw1", "api_keys": ["a1"]}

EMPTY = "Insufficient balance or no resource package."
LIMIT = "429 Rate limit exceeded"


def test_чужой_ключ_не_выбивает_наш() -> None:
    reg = KeyRegistry()
    reg.ring("gw", ["a1", "a2"])
    reg.note_error(GW, "чужой-ключ", LIMIT)
    assert reg.stats("gw")["blocked"] == 0


def test_свой_ключ_выбивается() -> None:
    reg = KeyRegistry()
    reg.ring("gw", ["a1", "a2"])
    reg.note_error(GW, "a2", LIMIT)
    st = reg.stats("gw")
    assert st["blocked"] == 1
    row = next(r for r in st["keys"] if r["label"].endswith("a2"))
    assert row["blocked"]


def test_пустой_аккаунт_отличим_от_лимита() -> None:
    reg = KeyRegistry()
    reg.ring("gw", ["a1", "a2"])
    reg.note_error(GW, "a1", EMPTY)
    reasons = {r["label"]: r["reason"] for r in reg.stats("gw")["keys"]}
    assert "нет баланса" in reasons.values()
    assert "429" not in reasons.values()


def test_чужой_ключ_не_попадает_в_статистику() -> None:
    reg = KeyRegistry()
    reg.ring("gw1", ["a1"])
    reg.note_error(ONE, "выдуманный", LIMIT)
    assert len(reg.stats("gw1")["keys"]) == 1


def test_пустая_ошибка_ничего_не_выбивает() -> None:
    reg = KeyRegistry()
    reg.ring("gw", ["a1", "a2"])
    reg.note_error(GW, "a1", "")
    assert reg.stats("gw")["blocked"] == 0


def test_лимит_без_кода_распознан() -> None:
    reg = KeyRegistry()
    reg.ring("gw", ["a1", "a2"])
    reg.note_error(GW, "a1", "You have exceeded your rate limit")
    assert reg.stats("gw")["blocked"] == 1


def test_ключ_не_попадает_в_причину() -> None:
    """Текст ошибки может содержать сам ключ — в reason его быть не должно."""
    ring = KeyRing(keys=["a1"])
    ring.note_error("a1", "429 по ключу sk-or-v1-abcdef123456")
    assert "abcdef" not in json.dumps(ring.stats())


def test_ошибка_от_другого_шлюза_не_влияет() -> None:
    """Кольца разные: ошибка у одного шлюза не должна трогать другой."""
    reg = KeyRegistry()
    reg.ring("one", ["a1", "a2"])
    reg.ring("two", ["b1", "b2"])
    reg.note_error({"id": "one", "api_keys": ["a1", "a2"]}, "a1", LIMIT)
    assert reg.stats("one")["blocked"] == 1
    assert reg.stats("two")["blocked"] == 0