"""Регрессии стенда: веса сходства и учёт квоты при сканировании.

Обе ошибки меняли вердикт, не меняя код: первая — что считать использованным
эталон, вторая — сколько квоты осталось у аккаунта.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ==================================================== веса сходства


def _book(tmp: Path) -> "object":
    from bench.refbook import RefBook

    return RefBook(tmp)


def test_пустой_файл_эталона_не_съезжает_веса(tmp_path: Path) -> None:
    """Сходство и вес собирались в разных циклах.

    Пустой файл эталона пропускался в списке сходства, но не в списке весов,
    и при пустом **первом** файле все веса съезжали на одну позицию: большой
    исходник получал вес короткого файла, и вердикт «использовал ли эталон»
    менялся не из-за кода, а из-за пустого файла в начале списка.
    """
    ref = tmp_path / "ref"
    ref.mkdir()
    art = tmp_path / "art"
    art.mkdir()

    body = "hello\n" * 100
    (art / "out.py").write_text(body, encoding="utf-8")
    (ref / "empty.txt").write_text("", encoding="utf-8")
    (ref / "small.py").write_text("zzz\n", encoding="utf-8")
    (ref / "big.py").write_text(body, encoding="utf-8")

    got = _book(tmp_path).similarity(ref, {"out.py": art / "out.py"})
    # Пустой файл не участвует: сходство 0.0 с весом 4 и 1.0 с весом 600.
    want = (0.0 * 4 + 1.0 * 600) / (4 + 600)
    assert abs(got - want) < 0.01, (got, want)


def test_пустой_файл_в_конце_не_меняет_результат(tmp_path: Path) -> None:
    ref = tmp_path / "ref"
    ref.mkdir()
    art = tmp_path / "art"
    art.mkdir()

    body = "hello\n" * 100
    (art / "out.py").write_text(body, encoding="utf-8")
    (ref / "small.py").write_text("zzz\n", encoding="utf-8")
    (ref / "big.py").write_text(body, encoding="utf-8")

    book = _book(tmp_path)
    before = book.similarity(ref, {"out.py": art / "out.py"})
    (ref / "empty.txt").write_text("", encoding="utf-8")
    after = book.similarity(ref, {"out.py": art / "out.py"})
    assert before == after, (before, after)


def test_все_файлы_пустые_дают_ноль(tmp_path: Path) -> None:
    ref = tmp_path / "ref"
    ref.mkdir()
    art = tmp_path / "art"
    art.mkdir()
    (art / "out.py").write_text("hello\n", encoding="utf-8")
    (ref / "a.txt").write_text("", encoding="utf-8")
    (ref / "b.txt").write_text("   \n", encoding="utf-8")
    assert _book(tmp_path).similarity(ref, {"out.py": art / "out.py"}) == 0.0


# ==================================================== квота проб


def test_проба_сообщает_остаток_в_кольцо() -> None:
    """Сканирование каталога шло мимо `failover`, где учёт и происходит.

    Полное сканирование — десятки запросов по каждому аккаунту. Без учёта
    кольцо считало по старому остатку, агент получал 429 на середине задачи,
    а причина была в сканировании час назад.

    Проверяется то, что важно: остаток из ответа попадает в строку результата
    (его забирает `probe_models`) и доходит до кольца.
    """
    import asyncio

    from hub.keyring import REGISTRY
    from hub.registry import one_probe

    class _Provider:
        async def chat(self, model_id, messages, **kwargs):
            return {"text": "ok", "limits": {"requests_remaining": 7}}

    async def сценарий() -> dict:
        return await one_probe(_Provider(), _model(), "ok", 16, _sem())

    row = asyncio.run(сценарий())
    assert row.get("limits") == {"requests_remaining": 7}, row


def test_probe_models_учитывает_квоту() -> None:
    """`probe_models` обязан передавать остаток и расход в кольцо.

    Проверяется подменой кольца: иначе пришлось бы гонять настоящее
    сканирование по всем моделям.
    """
    import asyncio
    import inspect

    from hub import registry as registry_mod

    seen: list[tuple[str, dict]] = []

    class _Ring:
        def note_quota(self, key, limits):
            seen.append(("quota", limits))

        def note_spent(self, key, rpm=None):
            seen.append(("spent", {}))

    class _Registry:
        def ring(self, gateway_id, keys):
            return _Ring()

    original = registry_mod.REGISTRY
    registry_mod.REGISTRY = _Registry()
    try:
        source = inspect.getsource(registry_mod.probe_models)
    finally:
        registry_mod.REGISTRY = original

    # Учёт обязан быть в обоих местах: основная пачка и повторы по 429.
    assert source.count("REGISTRY.note_quota") >= 2, source
    assert source.count("REGISTRY.note_spent") >= 2, source


def _model():
    from hub.registry import FreeModel

    return FreeModel(gateway_id="gw", model_id="m", source="static")


def _sem():
    import asyncio

    return asyncio.Semaphore(1)
