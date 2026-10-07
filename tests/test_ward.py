"""Лазарет моделей: палаты вместо сухой таблицы карантина.

Идея из `update/creativeupdate-07-10-26.txt` («карантин как лазарет»).
Проверяется деление по палатам — это логика, а не украшение: палата,
ошибающаяся на одну модель, врала бы человеку в момент, когда он
выбирает, кого брать в работу.
"""

from __future__ import annotations

from pathlib import Path

from hub.select import WARD_GROUPS, ward

UI = (Path(__file__).resolve().parent.parent / "hub" / "ui.py").read_text(
    encoding="utf-8"
)

ROW = {
    "ref": "gw/model",
    "gateway": "gw",
    "model": "model",
    "cooldown_left": 0,
    "fails": 0,
    "error": None,
}


def rows(*statuses: str) -> list[dict]:
    return [{**ROW, "ref": f"gw/{s}", "model": s, "status": s} for s in statuses]


def group(result: list[dict], key: str) -> dict:
    return next(g for g in result if g["key"] == key)


def test_палаты_делятся_по_последнему_статусу() -> None:
    got = ward(rows("limited", "empty", "down", "blocked", "ok", "slow", "unknown"))

    assert [g["key"] for g in got] == [k for k, _, _ in WARD_GROUPS]
    assert group(got, "ward")["count"] == 2          # 429 и пустой ответ
    assert group(got, "critical")["count"] == 2      # 5xx и блок провайдера
    assert group(got, "discharged")["count"] == 2    # отвечают нормально
    assert group(got, "unseen")["count"] == 1        # ещё не вызывались
    assert sum(g["count"] for g in got) == 7, "модель потерялась при делении"

    titles = {g["key"]: g["title"] for g in got}
    assert titles["critical"] == "в реанимации"
    assert titles["ward"] == "на лечении"
    assert titles["discharged"] == "выписаны"


def test_кончившийся_бэкофф_не_делает_модель_выписанной() -> None:
    """Карантин кончился, но последний статус — 429: палата всё ещё «на
    лечении», просто отсчёт уже на нуле (ждём перепроверки)."""
    cooling = {**ROW, "status": "limited", "cooldown_left": 42}
    finished = {**ROW, "status": "limited", "cooldown_left": 0}

    got = ward([cooling, finished])
    ward_group = group(got, "ward")
    assert ward_group["count"] == 2
    assert group(got, "discharged")["count"] == 0
    # Часы идут вниз: тот, кого дольше держат, стоит выше.
    assert [it["cooldown_left"] for it in ward_group["items"]] == [42, 0]


def test_палата_несёт_отсчёт_и_причину() -> None:
    row = {
        **ROW,
        "status": "down",
        "cooldown_left": 90,
        "fails": 3,
        "error": "HTTP 502",
    }
    item = group(ward([row]), "critical")["items"][0]
    assert item["cooldown_left"] == 90
    assert item["error"] == "HTTP 502"
    assert item["fails"] == 3
    assert item["ref"] == "gw/model" and item["gateway"] == "gw"


def test_незнакомый_статус_не_выбрасывается_молча() -> None:
    got = ward([{**ROW, "status": "что-то новое"}])
    assert sum(g["count"] for g in got) == 1
    assert group(got, "unseen")["count"] == 1


def test_пустой_лазарет_всё_равно_отдаёт_все_палаты() -> None:
    got = ward([])
    assert [g["count"] for g in got] == [0, 0, 0, 0]
    assert all(g["items"] == [] for g in got)


def test_состояние_несёт_палату(tmp_path) -> None:
    """Воркер отдаёт палату одним ключом — интерфейсу не с чем её считать."""
    from hub.worker import Worker

    worker = Worker(tmp_path)
    state = worker.state()
    assert [g["key"] for g in state["ward"]] == [k for k, _, _ in WARD_GROUPS]
    assert len(state["ward"]) == len(WARD_GROUPS)


def test_палата_есть_во_вкладке_статуса() -> None:
    assert 'id="wardBox"' in UI
    assert "function renderWard" in UI
    assert "S.ward" in UI
    # Отсчёт берётся из общей функции, а не пилится заново с ошибками округления.
    assert "fmtLeft(it.cooldown_left)" in UI
    assert "renderWard();" in UI, "палата не вызывается при обновлении"
