"""Разбор ответа 429: кончилась квота или аккаунт пуст.

Оба случая приходят кодом 429, и последствия у них противоположны. Первый
отпускает аккаунт через час сам, второй не отпустит никогда, пока не
пополнить. Если перепутать — человек либо зря ждёт лимит там, где нет денег,
либо пустой аккаунт выбивается по часу и занимает место в ротации.
"""

from __future__ import annotations

import pytest

from hub.keyring import EMPTY_ACCOUNT, KeyRing
from providers.openai_compat import _limit_reason


def classify(text: str) -> tuple[str, int]:
    """Разобрать текст и посмотреть, что решило кольцо."""
    ring = KeyRing(keys=["a"])
    ring.note_error("a", _limit_reason(text))
    row = ring.stats()["keys"][0]
    return row["reason"], row["cooldown"]


# =============================================================== пустой аккаунт


def test_zai_без_денег() -> None:
    reason, wait = classify(
        '{"error":{"code":"1113","message":"Insufficient balance or no '
        'resource package. Please recharge."}}'
    )
    assert reason == "нет баланса", reason
    assert wait == pytest.approx(EMPTY_ACCOUNT, abs=5)


def test_openai_кончились_кредиты() -> None:
    reason, _ = classify("You have insufficient credits for this request")
    assert reason == "нет баланса", reason


def test_слова_про_пополнение() -> None:
    assert classify("Please recharge your account")[0] == "нет баланса"


# =============================================================== лимит


def test_mistral_лимит() -> None:
    reason, wait = classify(
        '{"object":"error","message":"Rate limit exceeded",'
        '"type":"rate_limited","code":"1300"}'
    )
    assert reason == "429", reason
    assert 0 < wait < EMPTY_ACCOUNT, "лимит должен отпустить быстро"


def test_openrouter_лимит() -> None:
    reason, _ = classify("Rate limit exceeded")
    assert reason == "429"


def test_openai_квота() -> None:
    assert classify("You exceeded your current quota")[0] == "429"


def test_слишком_много_запросов() -> None:
    assert classify("Too Many Requests")[0] == "429"


# =============================================================== границы


def test_пустой_ответ_всё_равно_лимит() -> None:
    """Тела может не быть вовсе: молчать о причине нельзя, код известен."""
    reason, _ = classify("")
    assert reason == "429", reason


def test_неизвестная_причина_не_пустой_аккаунт() -> None:
    """Незнакомый текст не должен объявлять аккаунт пустым."""
    reason, _ = classify("429 что-то совсем новое")
    assert reason != "нет баланса", reason


def test_текст_не_течёт_в_причину() -> None:
    """Ключ может встретиться в теле ответа — в reason ему не место."""
    ring = KeyRing(keys=["a"])
    secret = "sk-or-v1-udalennye-dlya-istorii-znacheniya"
    ring.note_error("a", f"429 отказ для ключа {secret}")
    assert secret[-6:] not in str(ring.stats())


def test_сообщение_человеческое() -> None:
    """Формулировка идёт в интерфейс: она должна быть понятна человеку."""
    assert "пополните" in _limit_reason("Insufficient balance")
    assert "попробуйте позже" in _limit_reason("Rate limit exceeded")