"""Доступность моделей из региона: вердикт собирается только из двух замеров."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub.regions import (
    MODE_DIRECT,
    MODE_VPN,
    RU_BLOCKED,
    RU_LABELS,
    RU_OK,
    RU_UNKNOWN,
    RU_VPN,
    RegionBook,
    RegionNote,
    summarize,
    verdict,
)


# ------------------------------------------------------------------ вердикт


def test_direct_ok_means_ru_ok() -> None:
    assert verdict({"direct": "ok"}) == RU_OK


def test_direct_ok_beats_vpn_failure() -> None:
    """Прямой замер важнее: с VPN может не ответить по другим причинам."""
    assert verdict({"direct": "ok", "vpn": "down"}) == RU_OK


def test_vpn_only_needs_vpn() -> None:
    assert verdict({"direct": "down", "vpn": "ok"}) == RU_VPN


def test_down_in_both_is_blocked() -> None:
    assert verdict({"direct": "down", "vpn": "down"}) == RU_BLOCKED


def test_vpn_only_measurement_does_not_prove_ru_access() -> None:
    """Ключевая честность: с VPN отвечает почти всё.

    Один замер с VPN не должен превращаться в утверждение «работает из
    России» — иначе вся затея обесценивается.
    """
    assert verdict({"vpn": "ok"}) == RU_VPN
    assert verdict({"vpn": "ok"}) != RU_OK


def test_no_measurements_is_unknown() -> None:
    assert verdict({}) == RU_UNKNOWN


def test_empty_status_is_a_response() -> None:
    """Пустой content — модель ответила, значит доступ есть."""
    assert verdict({"direct": "empty"}) == RU_OK


def test_slow_counts_as_alive() -> None:
    assert verdict({"direct": "slow"}) == RU_OK


# -------------------------------------------------------------------- книга


def test_new_note_is_unknown() -> None:
    note = RegionBook().get("gw/model")
    assert note.status == RU_UNKNOWN
    assert note.samples == {}


def test_record_single_direct_measurement() -> None:
    book = RegionBook()
    book.record("gw/m", MODE_DIRECT, "ok")
    assert book.status_of("gw/m") == RU_OK


def test_record_two_measurements() -> None:
    book = RegionBook()
    book.record("gw/m", MODE_VPN, "ok")
    book.record("gw/m", MODE_DIRECT, "down")
    assert book.status_of("gw/m") == RU_VPN


def test_vpn_measurement_does_not_overwrite_direct_ok() -> None:
    """Порядок прогонов не должен ломать уже известный результат."""
    book = RegionBook()
    book.record("gw/m", MODE_DIRECT, "ok")
    book.record("gw/m", MODE_VPN, "down")
    assert book.status_of("gw/m") == RU_OK


def test_direct_measurement_does_not_overwrite_vpn_verdict() -> None:
    book = RegionBook()
    book.record("gw/m", MODE_VPN, "ok")
    book.record("gw/m", MODE_DIRECT, "down")
    assert book.status_of("gw/m") == RU_VPN


def test_record_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        RegionBook().record("gw/m", "через-прокси", "ok")


def test_limited_counts_as_reachable() -> None:
    """429 — это ответ сервера: сеть до шлюза дошла, доступ из РФ есть."""
    assert verdict({"direct": "limited"}) == RU_OK


def test_blocked_status_is_not_a_reachable_response() -> None:
    """403 — провайдер ответил отказом; отдельно от «не достучались»."""
    assert verdict({"direct": "blocked"}) == RU_OK


def test_record_stamps_time() -> None:
    book = RegionBook()
    before = book.record("gw/m", MODE_DIRECT, "ok").checked_at
    assert before > 0


def test_record_keeps_note() -> None:
    book = RegionBook()
    book.record("gw/m", MODE_DIRECT, "down", note="403 от провайдера")
    assert book.get("gw/m").note == "403 от провайдера"


def test_record_second_measurement_keeps_old_note() -> None:
    book = RegionBook()
    book.record("gw/m", MODE_DIRECT, "down", note="таймаут")
    book.record("gw/m", MODE_DIRECT, "ok")
    assert book.get("gw/m").note == "таймаут"


def test_direct_ok_set() -> None:
    book = RegionBook()
    book.record("a", MODE_DIRECT, "ok")
    book.record("b", MODE_VPN, "ok")
    book.record("c", MODE_DIRECT, "down")
    book.record("c", MODE_VPN, "ok")
    assert book.direct_ok() == {"a"}


def test_needs_vpn_set() -> None:
    book = RegionBook()
    book.record("a", MODE_DIRECT, "ok")
    book.record("b", MODE_DIRECT, "down")
    book.record("b", MODE_VPN, "ok")
    assert book.needs_vpn() == {"b"}


def test_measured_set() -> None:
    book = RegionBook()
    book.record("a", MODE_DIRECT, "ok")
    assert book.measured() == {"a"}


# ------------------------------------------------------------- сохранение


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    book = RegionBook(root=tmp_path)
    book.record("gw/m", MODE_DIRECT, "ok")
    book.record("gw/n", MODE_DIRECT, "down")
    book.record("gw/n", MODE_VPN, "ok")
    path = book.save()

    assert path.is_file()
    loaded = RegionBook.load(tmp_path)
    assert loaded.status_of("gw/m") == RU_OK
    assert loaded.status_of("gw/n") == RU_VPN
    assert loaded.get("gw/n").samples == {"direct": "down", "vpn": "ok"}


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    book = RegionBook.load(tmp_path)
    assert book.notes == {}
    assert book.status_of("любая") == RU_UNKNOWN


def test_load_broken_json_is_empty(tmp_path: Path) -> None:
    """Битый regions.json не должен ломать запуск программы."""
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "regions.json").write_text("{ сломано", encoding="utf-8")

    book = RegionBook.load(tmp_path)

    assert book.notes == {}


def test_load_skips_malformed_entries(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "regions.json").write_text(
        json.dumps({"models": {"a": "не словарь", "b": {"status": RU_OK}}}),
        encoding="utf-8")

    book = RegionBook.load(tmp_path)

    assert book.status_of("b") == RU_OK
    assert book.status_of("a") == RU_UNKNOWN


def test_save_creates_config_dir(tmp_path: Path) -> None:
    root = tmp_path / "новый" / "проект"
    book = RegionBook(root=root)
    book.record("gw/m", MODE_DIRECT, "ok")

    path = book.save()

    assert path.is_file()
    assert path.parent.name == "config"


def test_save_omits_unmeasured(tmp_path: Path) -> None:
    book = RegionBook(root=tmp_path)
    book.notes["пустая"] = RegionNote()
    book.record("измеренная", MODE_DIRECT, "ok")

    payload = book.to_payload()

    assert "измеренная" in payload["models"]
    assert "пустая" not in payload["models"]


# ---------------------------------------------------- сервер и воркер


def test_empty_book_with_root_is_valid() -> None:
    """Пустая книга с корнем проекта — валидное состояние.

    Регрессия: reset создавал RegionBook(worker.regions.root), то есть путь
    уходил в первый позиционный параметр (словарь замеров), и summarize()
    падал с AttributeError. Поэтому root передаём только именованно.
    """
    book = RegionBook({}, root="/tmp/proj")

    assert book.notes == {}
    assert book.to_payload()["models"] == {}
    assert summarize(book)["measured"] == 0


def test_root_keyword_does_not_land_in_notes() -> None:
    book = RegionBook(root="/tmp/proj")
    assert book.notes == {}
    assert book.direct_ok() == set()


def test_server_region_routes(tmp_path: Path) -> None:
    """Все ветки /api/region отвечают и не роняют сервер."""
    from hub.server import ApiServer, Handler
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        assert worker.region_status()["ok"] is True
        handler = Handler.__new__(Handler)
        handler.api = ApiServer(tmp_path, worker)

        bad = Handler._region(handler, {"action": "выдумка"})
        assert bad["ok"] is False

        reset = Handler._region(handler, {"action": "reset"})
        assert reset["ok"] is True
        assert reset["summary"]["measured"] == 0

        status = Handler._region(handler, {"action": "status"})
        assert status["ok"] is True
    finally:
        worker.store.close()


def test_worker_measure_rejects_unknown_mode(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        result = worker.measure_region("через-прокси")
        assert result["ok"] is False
        assert "режим" in result["error"]
    finally:
        worker.store.close()


def test_worker_measure_requires_registry(tmp_path: Path) -> None:
    """Без реестра замер запускать нечего — и сказать об этом, а не падать."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        worker.selector = None
        result = worker.measure_region("direct")
        assert result["ok"] is False
        assert "Обновить" in result["error"]
    finally:
        worker.store.close()


def test_worker_region_status_shape(tmp_path: Path) -> None:
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        status = worker.region_status()
        for key in ("running", "mode", "progress", "log", "summary",
                    "direct_measured"):
            assert key in status, key
    finally:
        worker.store.close()


def test_measure_serialises_while_running(tmp_path: Path) -> None:
    """Второй замер не должен запускаться поверх первого: они бы делили квоту."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        worker.geo_running = True
        result = worker.measure_region("direct")
        assert result["ok"] is False
        assert "уже идёт" in result["error"]
    finally:
        worker.store.close()


def test_state_exposes_region_block(tmp_path: Path) -> None:
    """Интерфейс читает S.region — без него кнопки остались бы заблокированы."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    try:
        state = worker.state()
        assert "region" in state
        assert "regions" in state
    finally:
        worker.store.close()


# ---------------------------------------------------------------- сводка


def test_summarize_counts() -> None:
    book = RegionBook()
    book.record("a", MODE_DIRECT, "ok")
    book.record("b", MODE_DIRECT, "down")
    book.record("b", MODE_VPN, "ok")
    book.record("c", MODE_DIRECT, "down")
    book.record("c", MODE_VPN, "down")

    stats = summarize(book)

    assert stats["counts"][RU_OK] == 1
    assert stats["counts"][RU_VPN] == 1
    assert stats["counts"][RU_BLOCKED] == 1
    assert stats["measured"] == 3


def test_labels_cover_all_verdicts() -> None:
    for status in (RU_OK, RU_VPN, RU_BLOCKED, RU_UNKNOWN):
        assert RU_LABELS[status]


# --------------------------------------------------------- приоритет выбора


def _selector_with_regions(tmp_path: Path, **kwargs):
    from hub.registry import FreeModel, Registry
    from hub.select import Selector
    from hub.tiers import TierBook

    models = [
        FreeModel("gw", "vpn-only", "static"),
        FreeModel("gw", "direct-ok", "static"),
    ]
    registry = Registry(
        gateways=[{"id": "gw", "label": "G", "base_url": "u", "resolved_url": "u",
                   "api_key": "", "needs_key": False, "has_key": True,
                   "free_models": [], "catalog": []}],
        models=models,
    )
    selector = Selector(registry, TierBook({}), **kwargs)
    return selector


def test_vpn_models_go_last_when_avoided(tmp_path: Path) -> None:
    selector = _selector_with_regions(
        tmp_path, avoid_vpn=True, vpn_only={"gw/vpn-only"})

    ordered = selector.ordered()

    assert ordered.index("gw/vpn-only") > ordered.index("gw/direct-ok")


def test_vpn_models_are_kept_not_dropped(tmp_path: Path) -> None:
    """Понизить приоритет, а не убрать: вдруг VPN включат."""
    selector = _selector_with_regions(
        tmp_path, avoid_vpn=True, vpn_only={"gw/vpn-only"})

    assert len(selector.ordered()) == 2


def test_order_unchanged_when_avoid_disabled(tmp_path: Path) -> None:
    selector = _selector_with_regions(tmp_path, avoid_vpn=False,
                                      vpn_only={"gw/vpn-only"})

    assert selector.ordered() == selector.ordered()


def test_manual_mode_ignores_vpn_preference(tmp_path: Path) -> None:
    """В ручном режиме пользователь сам выбрал модель — не переставляем."""
    selector = _selector_with_regions(
        tmp_path, avoid_vpn=True, vpn_only={"gw/vpn-only"})
    selector.set_mode("manual", manual_ref="gw/vpn-only")

    assert selector.ordered() == ["gw/vpn-only"]


def test_chain_mode_ignores_vpn_preference(tmp_path: Path) -> None:
    selector = _selector_with_regions(
        tmp_path, avoid_vpn=True, vpn_only={"gw/direct-ok"})
    selector.set_mode("chain", chain=["gw/vpn-only", "gw/direct-ok"])

    assert selector.ordered() == ["gw/vpn-only", "gw/direct-ok"]
