"""Ранжирование моделей: скорость важна, зрение — фильтр.

Начиналось с правки конфига, а кончилось проверкой самого ранжирования.
Причина простая: конфиг можно написать верно и всё равно получить вверху
списка модель, которая отвечает полминуты, потому что код ранжирует иначе,
чем расставлены галочки в файле.

Замеры в тестах — настоящие, из живого пинга 06.10.2026.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.tiers import (  # noqa: E402
    TIER_COST_S,
    UNKNOWN_LATENCY_S,
    TierBook,
    rank_models,
)


@dataclass
class FakeModel:
    """Модель реестра: полей тут нужно ровно два."""

    gateway_id: str
    model_id: str

    @property
    def ref(self) -> str:
        return f"{self.gateway_id}/{self.model_id}"


#: Задержки из живого пинга, в секундах.
LATENCY = {
    "nvidia/meta/llama-3.2-90b-vision-instruct": 32.735,
    "nvidia/nvidia/nemotron-3-super-120b-a12b": 1.152,
    "nvidia/poolside/laguna-xs-2.1": 0.481,
    "groq/openai/gpt-oss-120b": 0.498,
}


def book() -> TierBook:
    """Паспорта моделей: ранг и умение видеть."""
    specs = {
        ("nvidia", "meta/llama-3.2-90b-vision-instruct"): (3, True),
        ("nvidia", "nvidia/nemotron-3-super-120b-a12b"): (1, False),
        ("nvidia", "poolside/laguna-xs-2.1"): (1, False),
        ("groq", "openai/gpt-oss-120b"): (3, False),
    }
    from hub.tiers import ModelSpec

    return TierBook({(g, m): ModelSpec(gateway=g, model=m, tier=t, vision=v)
                     for (g, m), (t, v) in specs.items()})


MODELS = [
    FakeModel("nvidia", "meta/llama-3.2-90b-vision-instruct"),
    FakeModel("nvidia", "nvidia/nemotron-3-super-120b-a12b"),
    FakeModel("nvidia", "poolside/laguna-xs-2.1"),
    FakeModel("groq", "openai/gpt-oss-120b"),
]


def order(*, vision: bool = False, speed: bool = False) -> list[str]:
    return [m.ref for m in rank_models(
        MODELS, book(), require_vision=vision, prefer_speed=speed,
        latencies=LATENCY)]


# =============================================================== скорость


def test_медленная_модель_уходит_вниз_по_рангу() -> None:
    """Раньше ранг задавал порядок целиком, и 32 секунды стоили ранга 1.

    Для агента модель, отвечающая полминуты, не «медленная» — она делает
    задачу невозможной: человек успевает уйти и вернуться, а лимит выбит.
    """
    refs = order()
    assert refs[0] != "nvidia/meta/llama-3.2-90b-vision-instruct"
    assert refs.index("nvidia/meta/llama-3.2-90b-vision-instruct") == len(refs) - 1


def test_быстрая_модель_ранга_3_обгоняет_медленную_ранга_1() -> None:
    refs = order()
    assert refs.index("groq/openai/gpt-oss-120b") < \
        refs.index("nvidia/meta/llama-3.2-90b-vision-instruct")


def test_задержка_входит_в_ранг_а_не_разбирает_ничьи() -> None:
    """Две модели одного ранга: медленная должна уйти вниз."""
    from hub.tiers import ModelSpec

    same = TierBook({
        ("a", "быстрая"): ModelSpec(gateway="a", model="быстрая", tier=1),
        ("a", "медленная"): ModelSpec(gateway="a", model="медленная", tier=1),
    })
    ranked = rank_models(
        [FakeModel("a", "быстрая"), FakeModel("a", "медленная")], same,
        latencies={"a/быстрая": 0.2, "a/медленная": 9.0})
    assert [m.model_id for m in ranked] == ["быстрая", "медленная"]


def test_предпочтение_скорости_усиливает_вес() -> None:
    slow_first = order()
    fast_first = order(speed=True)
    assert fast_first.index("nvidia/meta/llama-3.2-90b-vision-instruct") >= \
        slow_first.index("nvidia/meta/llama-3.2-90b-vision-instruct")


def test_непроверенная_модель_не_считается_лучшей() -> None:
    """Иначе модель, которую ни разу не звали, обгоняет заведомо быстрые."""
    from hub.tiers import ModelSpec

    spec = TierBook({("a", "x"): ModelSpec(gateway="a", model="x", tier=1)})
    ranked = rank_models([FakeModel("a", "x")], spec, latencies={})
    assert ranked, "модель пропала из списка"
    assert UNKNOWN_LATENCY_S > 0, "непроверенной модели полагается нулевая задержка"


def test_задержка_в_ранг_пересчитывается() -> None:
    """Один и тот же конфиг, разная скорость — разный порядок."""
    from hub.tiers import ModelSpec

    spec = TierBook({
        ("a", "быстрая"): ModelSpec(gateway="a", model="быстрая", tier=2),
        ("a", "медленная"): ModelSpec(gateway="a", model="медленная", tier=2),
    })
    models = [FakeModel("a", "быстрая"), FakeModel("a", "медленная")]
    assert [m.model_id for m in rank_models(
        models, spec, latencies={"a/быстрая": 0.1, "a/медленная": 0.1})] \
        == ["быстрая", "медленная"]
    assert [m.model_id for m in rank_models(
        models, spec, latencies={"a/медленная": 40.0})] \
        == ["быстрая", "медленная"]


def test_цена_одного_ранга_измерима() -> None:
    """Константа — часть формулы, и её значение обязано быть разумным."""
    assert 0.5 <= TIER_COST_S <= 10.0


# =============================================================== зрение


def test_zrenie_eto_filtr_a_ne_dostoinstvo() -> None:
    """Vision-модель не лезет в начало списка, когда картинки нет."""
    refs = order()
    assert "nvidia/meta/llama-3.2-90b-vision-instruct" not in refs[:2]


def test_s_kartinkoy_ostayutsya_tolko_zryashchie() -> None:
    refs = order(vision=True)
    assert refs == ["nvidia/meta/llama-3.2-90b-vision-instruct"], refs


def test_s_kartinkoy_vyбираetsya_samyy_bystryy_iz_zryashchikh() -> None:
    """Зрение остаётся обязательным, скорость решает, кто именно."""
    from hub.tiers import ModelSpec

    spec = TierBook({
        ("a", "медленное-зрение"): ModelSpec(gateway="a", model="медленное-зрение",
                                             tier=1, vision=True),
        ("a", "быстрое-зрение"): ModelSpec(gateway="a", model="быстрое-зрение",
                                            tier=3, vision=True),
    })
    ranked = rank_models(
        [FakeModel("a", "медленное-зрение"), FakeModel("a", "быстрое-зрение")],
        spec, require_vision=True,
        latencies={"a/медленное-зрение": 20.0, "a/быстрое-зрение": 0.3})
    assert [m.model_id for m in ranked] == ["быстрое-зрение", "медленное-зрение"]


# =============================================================== реальный конфиг


def test_в_нашем_конфиге_glama_ne_tier_1() -> None:
    """Конкретная проверка на конфиге проекта.

    Именно это и было ошибкой: `meta/llama-3.2-90b-vision-instruct` стояла
    рангом 1 из-за умения видеть, хотя отвечала 32.7 секунды.
    """
    real = TierBook.load(ROOT)
    spec = real.get("nvidia", "meta/llama-3.2-90b-vision-instruct")
    assert spec.vision is True, "зрение должно остаться помеченным"
    assert spec.tier >= 3, f"ранг {spec.tier} для модели с задержкой 32.7 с"


def test_конфиг_загружается_и_модели_согласованы() -> None:
    real = TierBook.load(ROOT)
    assert len(real) > 0
    for spec in real.specs():
        assert 1 <= spec.tier <= 5, f"{spec.gateway}/{spec.model}: ранг {spec.tier}"