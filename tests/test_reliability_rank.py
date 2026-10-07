"""Надёжность модели участвует в выборе, а не только пишется в базу.

Аудит 07.10.2026: `ok_count` накапливался в `store.py`, но читал никто —
ранг задавался приоритетом провайдера и задержкой. Модель, у которой лимит
кончается через раз, стояла наравне со стабильной, и каждый хоп начинался
с её пробного запроса.

Проверяется, что:
* история отказов понижает модель в списке, а история успехов поднимает;
* отказ по причине аккаунта (429 при свободных ключах) репутацию не портит —
  вина не в модели;
* модель без данных не штрафуется: ни разу не звали — судить не о чем;
* оценка переживает перезапуск процесса.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.registry import FreeModel, Registry  # noqa: E402
from hub.selector import Selector  # noqa: E402
from hub.tiers import ModelSpec, TierBook, rank_models  # noqa: E402

GATEWAY = {
    "id": "a", "label": "A", "base_url": "https://a.test/v1",
    "resolved_url": "https://a.test/v1", "api_key": "", "needs_key": True,
    "has_key": False, "free_models": [], "catalog": [], "supports_responses": False,
}


def build() -> Selector:
    """Две модели одного тира: отличаются только историей."""
    registry = Registry(
        gateways=[dict(GATEWAY)],
        models=[FreeModel("a", "m1", "static"), FreeModel("a", "m2", "static")],
    )
    book = TierBook({
        ("a", "m1"): ModelSpec(gateway="a", model="m1", tier=2),
        ("a", "m2"): ModelSpec(gateway="a", model="m2", tier=2),
    })
    return Selector(registry, book)


# ================================================ ранг: доля отказов входит


def test_ненадёжная_модель_опускается_в_ранге() -> None:
    from hub.registry import FreeModel

    book = TierBook({
        ("a", "m1"): ModelSpec(gateway="a", model="m1", tier=2),
        ("a", "m2"): ModelSpec(gateway="a", model="m2", tier=2),
    })
    models = [FreeModel("a", "m1", "static"), FreeModel("a", "m2", "static")]

    ranked = rank_models(models, book, unreliable={"a/m1": 0.5})

    assert ranked[0].ref == "a/m2", "модель с половиной отказов впереди"


def test_без_данных_штрафа_нет() -> None:
    from hub.registry import FreeModel

    book = TierBook({
        ("a", "m1"): ModelSpec(gateway="a", model="m1", tier=2),
        ("a", "m2"): ModelSpec(gateway="a", model="m2", tier=2),
    })
    models = [FreeModel("a", "m1", "static"), FreeModel("a", "m2", "static")]

    ranked = rank_models(models, book, unreliable={})

    assert [m.ref for m in ranked] == ["a/m1", "a/m2"], (
        "порядок по умолчанию обязан сохраниться"
    )


# =========================================== селектор: история формирует выбор


def test_отказ_портит_репутацию() -> None:
    selector = build()
    ref = "a/m1"

    selector.record(ref, "ok", duration_ms=100)
    healthy = selector.states[ref].success_rate
    selector.record(ref, "limited", error="429")

    assert healthy > 0.5, f"успешный ответ оценён слишком строго: {healthy}"
    assert selector.states[ref].success_rate < healthy, (
        "модель, вернувшая 429, осталась на прежней оценке"
    )


def test_успех_поднимает_репутацию() -> None:
    selector = build()
    ref = "a/m1"

    selector.record(ref, "limited", error="429")
    low = selector.states[ref].success_rate
    selector.record(ref, "ok", duration_ms=100)
    raised = selector.states[ref].success_rate

    assert raised > low, f"успех не поднял оценку: {low} -> {raised}"

    # Правило, ради которого среднее, а не последний факт: серия успехов
    # полностью отмывает единичный провал.
    for _ in range(12):
        selector.record(ref, "ok", duration_ms=10)
    assert selector.states[ref].success_rate > 0.95, (
        f"после серии успехов оценка всё ещё низкая: "
        f"{selector.states[ref].success_rate}"
    )


def test_отказ_по_ключу_не_портит_репутацию() -> None:
    """429 при свободных аккаунтах — дело аккаунта, а не модели."""
    selector = build()
    ref = "a/m1"
    selector.record(ref, "ok", duration_ms=100)
    healthy = selector.states[ref].success_rate

    selector.record(ref, "limited", error="429", penalize=False)

    assert selector.states[ref].success_rate == healthy, (
        "модель понижена за чужой лимит"
    )
    assert selector.unreliable().get(ref, 0.0) == 1.0 - healthy


def test_модель_без_данных_не_попадает_в_штраф() -> None:
    selector = build()
    assert selector.unreliable() == {}, "неопытная модель оштрафована"


def test_оценка_помнит_недавнее_а_не_всю_историю() -> None:
    """Среднее, а не полная доля: одна серия не вешает ярлык навсегда."""
    selector = build()
    ref = "a/m1"

    selector.record(ref, "ok", duration_ms=10)
    selector.record(ref, "down", error="сеть")
    after_one_fail = selector.states[ref].success_rate

    assert 0.0 < after_one_fail < 1.0, after_one_fail

    for _ in range(10):
        selector.record(ref, "ok", duration_ms=10)
    assert selector.states[ref].success_rate > 0.95, (
        "после десятков успехов модель всё ещё в позоре"
    )


def test_порядок_выбора_меняется_на_самом_деле() -> None:
    """Конечная проверка: не функция ранжирования, а выбор агента."""
    selector = build()
    assert selector.ordered()[0] == "a/m1"

    for _ in range(4):
        selector.record("a/m1", "limited", error="429")
    selector.record("a/m2", "ok", duration_ms=100)

    assert selector.ordered()[0] == "a/m2", (
        f"порядок не изменился: {selector.ordered()}"
    )


# ================================================== перезапуск


def test_оценка_переживает_перезапуск(tmp_path: Path) -> None:
    from hub.store import Store

    selector = build()
    selector.record("a/m1", "ok", duration_ms=100)
    selector.record("a/m1", "down", error="сеть")
    before = selector.states["a/m1"].success_rate

    store = Store(tmp_path)
    try:
        store.save_models(selector.states)
        restored = store.load_models()["a/m1"]["success_rate"]
    finally:
        store.close()

    assert restored == before, f"{restored} != {before}"


def test_старая_база_получает_колонку_миграцией(tmp_path: Path) -> None:
    """Старая база получает колонку миграцией, а не падением на старте."""
    import sqlite3

    from hub.store import Store

    state = tmp_path / "web-state"
    state.mkdir(parents=True)
    conn = sqlite3.connect(str(state / "zagent.db"))
    conn.executescript("""
        CREATE TABLE models (
            ref TEXT PRIMARY KEY, gateway TEXT NOT NULL, model TEXT NOT NULL,
            tier INTEGER NOT NULL DEFAULT 5, status TEXT NOT NULL DEFAULT 'unknown',
            error TEXT, cooldown_until REAL NOT NULL DEFAULT 0,
            fails INTEGER NOT NULL DEFAULT 0, ok_count INTEGER NOT NULL DEFAULT 0,
            avg_ms REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0
        );
    """)
    conn.execute(
        "INSERT INTO models (ref, gateway, model) VALUES ('a/m1', 'a', 'm1')")
    conn.commit()
    conn.close()

    store = Store(tmp_path)
    try:
        assert store.load_models()["a/m1"]["success_rate"] == -1
    finally:
        store.close()
