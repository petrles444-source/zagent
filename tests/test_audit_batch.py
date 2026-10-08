"""Четыре правки из последнего аудита — проверки, которые кусаются.

1. **local_llm.py: словарь замера носил имя `diag`, а потом импортировался
   модуль `diag`.** `**diag` распаковывал модуль - `TypeError`, который
   глотал `except Exception`. Запись о времени уходила в никуда.
2. **failover.py: при `limited` и наличии свободного ключа `record()`
   вызывался дважды** - первый раз со штрафом. Карантин от первого вызова
   второй не отменял, то есть модель уходила в остывание ровно там, где
   должна была остаться в ротации.
3. **health.py: 429 означал «модель мёртвая».** Живая модель с исчерпанным
   лимитом выпадала из ротации и портила статистику.
4. **registry.py: успешный сбор локального рантайма возвращался как
   ошибка** - исправная Ollama показывалась сломанной.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import failover, health, local_llm  # noqa: E402
from hub.health import STATUS_DOWN, STATUS_LIMITED, _classify  # noqa: E402


# ===================================================== local_llm: имя не спорит


def test_в_local_llm_нет_имени_которое_перетирается_импортом() -> None:
    """`diag = {...}` плюс `from hub import diag` убивал запись о времени."""
    src = (ROOT / "hub" / "local_llm.py").read_text(encoding="utf-8")
    assert 'payload = {"model": model,' in src, "словарь не переименован"
    assert 'diag.note("local_chat_done", **payload)' in src
    assert "**diag)" not in src, "в модуль снова распаковывается модуль"
    assert '"scope":' not in src.split("local_chat_done")[0][-400:], (
        "ключ scope конфликтует с позиционным аргументом note()")


def test_распаковка_словаря_не_падает() -> None:
    """Тот самый вызов, который раньше ронял TypeError.

    Повторяем настоящую сигнатуру `note(scope, exc=None, **fields)`: если в
    payload остался ключ `scope`, вызов падает с «multiple values».
    """
    payload = {"model": "qwen2.5:3b", "ms": 12}
    received: dict[str, object] = {}

    def note(scope: str, exc: BaseException | None = None,
             **fields: object) -> None:
        received["scope"] = scope
        received.update(fields)

    note("local_chat_done", **payload)
    assert received["model"] == "qwen2.5:3b"
    assert received["ms"] == 12
    assert received["scope"] == "local_chat_done"


# ==================================================== failover: один record


class _Selector:
    """Селектор-заглушка: считает вызовы record и помнит штраф."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.mode = None
        self.manual_only = False

    def record(self, ref: str, status: str, *, error: object = None,
               duration_ms: int = 0, penalize: bool = True) -> None:
        self.calls.append((status, penalize))


def test_при_limited_с_свободным_ключом_запись_одна() -> None:
    """Главное: карантин не должен вставать там, где есть свободный ключ."""
    src = (ROOT / "hub" / "failover.py").read_text(encoding="utf-8")
    limited = src.index('if status == "limited" and self._has_free_key(gateway):')
    penalize_false = src.index("penalize=False", limited)
    plain = src.index("duration_ms=duration_ms)", limited)
    assert penalize_false < plain, "штрафная запись снова после бесплатной"
    # Ветка limited обязана заканчиваться continue до общей записи.
    assert "                continue\n" in src[limited:plain]


def test_две_записи_подряд_не_остались() -> None:
    """Модуль не должен звать record() дважды на один исход."""
    src = (ROOT / "hub" / "failover.py").read_text(encoding="utf-8")
    assert src.count("self.selector.record(ref, status") == 2, (
        "ожидались две записи: бесплатная на ветке limited и общая")


# ============================================== health: 429 это не «мёртвая»


def test_429_не_считается_мёртвой_моделью() -> None:
    assert _classify({"status": 429, "error": "limit"}, 5.0) == STATUS_LIMITED


def test_529_тоже_лимит() -> None:
    """Сверхлимит провайдеров — тот же смысл."""
    assert _classify({"status": 529}, 5.0) == STATUS_LIMITED


def test_настоящая_ошибка_остаётся_down() -> None:
    """Иначе мы бы прятали настоящие поломки."""
    assert _classify({"error": "boom", "text": "x"}, 5.0) == STATUS_DOWN


def test_пустой_ответ_остаётся_down() -> None:
    assert _classify({"text": ""}, 5.0) == STATUS_DOWN


def test_нормальный_ответ_ok() -> None:
    assert _classify({"text": "да", "duration_ms": 100}, 5.0) == "ok"


def test_лимит_не_считается_годным_для_работы() -> None:
    """`limited` — это «сейчас не выбирать», а не «работает»."""
    report = health.HealthReport(model_id="a", label="a",
                                 status=STATUS_LIMITED, duration_ms=10,
                                 tokens_in=0, tokens_out=0)
    assert report.alive is False, "исчерпанный лимит — не «жива», но и не down"


def test_статус_limited_объявлен() -> None:
    assert health.STATUS_LIMITED == "limited"


# ================================================== registry: успех не ошибка


def test_локальный_рантайм_не_попадает_в_поле_ошибки() -> None:
    src = (ROOT / "hub" / "registry.py").read_text(encoding="utf-8")
    assert 'results[f"{gateway_id}/*"] = {"status": "note", "error": note}' not in src, (
        "успешный сбор рантайма записывается в поле error")
    assert '"status": "note", "message": note' in src


def test_ошибка_шлюза_по_прежнему_попадает_в_error() -> None:
    """Ошибку терять нельзя: это и есть диагностика."""
    src = (ROOT / "hub" / "registry.py").read_text(encoding="utf-8")
    assert '"error":' in src, "ошибки перестали фиксироваться"
    # И потребитель умеет читать примечание из нового поля.
    assert '"status": "note"' in src
