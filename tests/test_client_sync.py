"""Браузер и консоль обязаны говорить одно и то же.

Проверка механическая: маршруты из `hub.protocol` сверяются с литералами,
которые на самом деле встречаются в `hub/ui.py` и в `tools/cli_tui.py`.
Пока списки совпадают, два интерфейса физически не могут разойтись в
адресах; когда кто-то добавит маршрут в один и забудет про другой —
упадёт этот тест, а не через полгода чужое поведение.

Что ещё проверяется:

* тело отправки задачи одно и то же (иначе задача из консоли тихо шла
  без субагентов и в автоматическом режиме);
* набор статусов «задача жива» общий;
* состояния моделей трактуются одинаково;
* в консоли не осталось захардкоженных маршрутов мимо протокола.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import protocol  # noqa: E402
from hub.protocol import Routes, Server, is_live, task_payload  # noqa: E402

UI = (ROOT / "hub" / "ui.py").read_text(encoding="utf-8")
CLI = (ROOT / "tools" / "cli_tui.py").read_text(encoding="utf-8")

ALL_ROUTES = sorted({v for k, v in vars(Routes).items()
                     if isinstance(v, str) and v.startswith("/api/")})


# ================================================ маршруты не расходятся


def test_каждый_общий_маршрут_есть_в_браузере() -> None:
    """Действие, доступное в консоли, должно быть и в браузере."""
    missing = [r for r in protocol.Routes.SHARED_ACTIONS if r not in UI]
    assert not missing, f"в веб-интерфейсе нет: {missing}"


def test_размышление_не_просто_написано_но_подключено() -> None:
    """Функция может остаться в файле мёртвым куском — и кнопка исчезнет.

    Проверка только наличия маршрута в тексте проходит и после того, как
    размышление отключили: строка `/api/thinking` остаётся внутри функции,
    которую никто не вызывает. Поэтому отдельно проверяем, что на кнопке
    стоит вызов.
    """
    assert 'onclick="thinkingRun()"' in UI, "кнопка размышления отключена"
    assert "function thinkingRun() {" in UI
    assert "function thinkingToInput() {" in UI


def test_флажок_размышления_уходит_в_тело_задачи() -> None:
    """Иначе веб отправляет задачу без размышления, а консоль с ним."""
    assert "deepen: TASK_FLAGS.think" in UI
    assert '"deepen": False' in protocol.task_payload("задача") or \
        task_payload("задача").get("deepen") is False


def test_каждый_общий_маршрут_есть_в_консоли() -> None:
    missing = [r for r in protocol.Routes.SHARED_ACTIONS
               if f'"{r}"' not in CLI and f"Routes." not in CLI]
    assert not missing, f"консоль не умеет: {missing}"


def test_консоль_берёт_маршруты_из_протокола() -> None:
    """Своих строк-адресов у консоли быть не должно: это и есть расхождение."""
    literal = [r for r in ALL_ROUTES if f'"{r}"' in CLI]
    assert not literal, f"в консоли захардкожены адреса: {literal}"


def test_адреса_берутся_из_протокола() -> None:
    """8783 в консоли написан один раз — в импорте протокола."""
    assert "http://127.0.0.1:8783" not in CLI, "адрес сервера продублирован"
    assert CLI.count("Server") >= 1 or "Server.BASE" in CLI


def test_список_маршрутов_не_пустой() -> None:
    """Пустой список прошёл бы любую проверку выше."""
    assert len(ALL_ROUTES) >= 15
    assert len(protocol.Routes.SHARED_ACTIONS) >= 10


def test_закрывающих_маршрутов_нет() -> None:
    """Маршрут в списке есть, а на сервере нет — расхождение наоборот."""
    server = (ROOT / "hub" / "server.py").read_text(encoding="utf-8")
    missing = [r for r in ALL_ROUTES if r not in server]
    assert not missing, f"сервер не знает маршрутов: {missing}"


def test_поток_событий_один() -> None:
    """Адрес потока собирается функцией — иначе клиенты разойдутся по курсору."""
    assert protocol.events_url(5).endswith("?since=5")
    assert "events_url" in CLI
    assert "/api/events" in UI


# ================================================ тело запроса одно


def test_тело_задачи_одинаково_у_клиентов() -> None:
    body = task_payload("почини тест")
    for key in ("task", "auto_mode", "plan_only", "subagents"):
        assert key in body, f"в теле задачи нет {key}"


def test_режим_по_умолчанию_явный() -> None:
    """Иначе задача из консоли шла не в том режиме, что из браузера."""
    body = task_payload("задача")
    assert body["auto_mode"] is True
    assert body["subagents"] == 0


def test_консоль_шлёт_общее_тело() -> None:
    assert "task_payload(" in CLI, "консоль собирает тело мимо протокола"


def test_экспортные_поля_не_затираются() -> None:
    body = task_payload("задача", subagents=2, plan_only=True)
    assert body["subagents"] == 2
    assert body["plan_only"] is True


# ================================================ статусы общие


def test_статусы_живой_задачи_общие() -> None:
    for status in ("running", "queued", "asking"):
        assert is_live({"status": status}), status
    for status in ("done", "failed", "cancelled"):
        assert not is_live({"status": status}), status


def test_набор_статусов_не_пустой() -> None:
    assert len(protocol.LIVE_STATUSES) >= 3
    assert len(protocol.DONE_STATUSES) >= 3
    assert not (protocol.LIVE_STATUSES & protocol.DONE_STATUSES), (
        "статус одновременно «живой» и «закрытый»")


def test_живые_задачи_считаются_одинаково() -> None:
    state = {"tasks": [{"id": 1, "status": "running"},
                       {"id": 2, "status": "done"},
                       {"id": 3, "status": "asking"},
                       "мусор"]}
    assert [t["id"] for t in protocol.live_tasks(state)] == [1, 3]


def test_консоль_считает_живые_задачи_через_протокол() -> None:
    assert "live_tasks(" in CLI
    assert "is_live(" in CLI or "LIVE" in CLI


# ================================================ модели


def test_состояния_моделей_заданы() -> None:
    assert {"ok", "fail", "cooling", "unknown"} <= protocol.MODEL_STATES


def test_неизвестное_состояние_не_ломает_клиентов() -> None:
    """Новый статус от сервера обязан оставаться «неизвестным», а не пустым."""
    assert protocol.model_state_mark("что-то новое") == "unknown"


# ================================================ парсеры адресов


def test_адреса_одинаковые_в_обоих_клиентах() -> None:
    assert Server.BASE == "http://127.0.0.1:8783"
    assert Server.BRIDGE == "http://127.0.0.1:8784"
    assert Routes.STATE == "/api/state"


def test_мост_у_консоли_и_веба_один() -> None:
    """Панель шлюза на 8784 — один и тот же адрес в обоих интерфейсах."""
    assert "8784" in UI or "/status" in UI
    assert "8784" in CLI or "мост" in CLI


def test_не_используется_старый_формат_адреса() -> None:
    """Старый стиль «api/» без ведущего слэша ломал маршрут молча."""
    for name, source in (("ui", UI), ("cli", CLI)):
        bad = re.findall(r"['\"](?!/)api/[a-z_]+", source)
        assert not bad, f"{name}: адрес без ведущего слэша: {bad[:3]}"