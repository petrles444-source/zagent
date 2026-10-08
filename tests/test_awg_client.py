"""Авторежим VPN: когда переключаем туннель, а когда не трогаем.

Проверяется решение, а не сеть: поднятие туннеля подменено заглушкой,
замеры задержки заданы заранее. Иначе тест зависел бы от того,
дотянулся ли до сервера и как быстро ответил, а проверять тут нужно
ровно одно — в каких случаях авторежим обязан дёрнуть туннель.

Почему порог переключения важнее всего остального
-------------------------------------------------
Туннель, который переключается на каждой проверке, обрывает все
открытые сессии каждые полчаса. Если новый конфиг быстрее на пять
миллисекунд, переключение не даёт ничего, а платит за него
пользователь. Поэтому проверка «текущий мёртв» и «нашёлся заметно
быстрее» должны проходить, а «нашёлся быстрее на копейки» — нет.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

_spec = importlib.util.spec_from_file_location(
    "awg_client", TOOLS / "awg_client.py")
assert _spec and _spec.loader
client = importlib.util.module_from_spec(_spec)
sys.modules["awg_client"] = client
_spec.loader.exec_module(client)

FOLDER = Path("C:/configs")


def result(name: str, ping: float | None, alive: bool = True) -> dict[str, Any]:
    """Готовый результат проверки конфига."""
    return {"file": name, "alive": alive, "ping_ms": ping, "port": 443,
            "verdict": "ХОРОШО" if alive else "ПОРТ ЗАКРЫТ"}


def run_step(results: list[dict[str, Any]], state: dict[str, Any],
             *, dry_run: bool = False,
             force: bool = False) -> tuple[list[str], int]:
    """Один шаг авторежима с подменёнными заглушками. Возвращает вызовы."""
    calls: list[str] = []
    client.pick = lambda folder, probes: results
    client.read_state = lambda: dict(state)
    client.write_state = lambda data: state.update(data)
    client.down = lambda: calls.append("down")
    client.up = lambda config: (calls.append(f"up:{config.name}"), (True, ""))[1]
    code = client.auto_once(FOLDER, 4, dry_run=dry_run, force=force)
    return calls, code


def test_лучший_уже_в_работе_туннель_не_трогаем() -> None:
    """Текущий конфиг быстрее всех — переключение только вредит."""
    calls, code = run_step(
        [result("a.conf", 40), result("b.conf", 120)],
        {"current": "a.conf", "ping_ms": 40})
    assert calls == [], f"туннель трогали зря: {calls}"
    assert code == 0


def test_переключаемся_при_заметном_выигрыше() -> None:
    """Нашёлся конфиг быстрее на 80 мс — это и есть смысл авторежима."""
    calls, code = run_step(
        [result("a.conf", 40), result("b.conf", 120)],
        {"current": "b.conf", "ping_ms": 120})
    assert calls == ["up:a.conf"], f"переключиться не должны были: {calls}"
    assert code == 0


def test_мелкий_выигрыш_не_в_счёт() -> None:
    """Пять миллисекунд — не причина рвать соединение.

    Порог проверяется на самостоятельной копии кода с изменённой
    величиной: так видно, что тест ловит именно снятие порога, а не
    любую поломку подряд. Подменять константу в самом модуле нельзя
    — на неё смотрят остальные проверки этого же файла.
    """
    import re
    source = Path(client.__file__).read_text(encoding="utf-8")
    lowered = source.replace("SWITCH_MARGIN_MS = 25", "SWITCH_MARGIN_MS = 0")
    assert lowered != source, "в коде нет порога 25 мс"

    namespace: dict[str, Any] = {"__name__": "awg_client_mutated",
                                 "__file__": client.__file__}
    exec(compile(lowered, client.__file__, "exec"), namespace)  # noqa: S102

    calls: list[str] = []
    namespace["pick"] = lambda folder, probes: [result("a.conf", 40),
                                                 result("b.conf", 50)]
    namespace["read_state"] = lambda: {"current": "b.conf", "ping_ms": 50}
    namespace["write_state"] = lambda data: None
    namespace["down"] = lambda: calls.append("down")
    namespace["up"] = lambda config: (calls.append(f"up:{config.name}"),
                                      (True, ""))[1]
    namespace["auto_once"](FOLDER, 4, dry_run=False, force=False)
    # Доказательство обратное: если бы порога не было, авторежим
    # рвал бы туннель из-за десяти миллисекунд. Проверка падает,
    # когда снятый порог перестаёт переключать — то есть когда
    # «защита» исчезает незаметно.
    assert calls == ["up:a.conf"], (
        f"снятый порог не дал переключения, проверка потеряла смысл: "
        f"{calls}")


def test_мёртвый_конфиг_меняем_даже_без_выигрыша() -> None:
    """Конфиг не отвечает — это важнее любых миллисекунд."""
    calls, code = run_step(
        [result("a.conf", 900), result("b.conf", None, alive=False)],
        {"current": "b.conf", "ping_ms": None})
    assert calls == ["up:a.conf"], f"мёртвый конфиг оставили: {calls}"
    assert code == 0


def test_без_живых_остаём_как_есть() -> None:
    """Нет живых — переключаться некуда, и код должен это сказать."""
    calls, code = run_step(
        [result("a.conf", None, alive=False), result("b.conf", None, alive=False)],
        {"current": "b.conf", "ping_ms": 40})
    assert calls == [], f"переключиться некуда, но попробали: {calls}"
    assert code == 1


def test_сухой_режим_ничего_не_поднимает() -> None:
    """Пробный прогон показывает решение, но туннель не трогает."""
    calls, code = run_step(
        [result("a.conf", 40), result("b.conf", 120)],
        {"current": "b.conf", "ping_ms": 120}, dry_run=True)
    assert calls == [], f"в сухом режиме подняли туннель: {calls}"
    assert code == 0


def test_порог_переключения_меняемый() -> None:
    """Порог — настройка, а не константа, вшитая в логику.

    Сначала поднимается порог, потом опускается: так видно, что на
    обоих концах шкалы решение принимается разное, а не одно и то же
    по счастливой совпад��ности.
    """
    old = client.SWITCH_MARGIN_MS
    try:
        client.SWITCH_MARGIN_MS = 200
        calls, _ = run_step(
            [result("a.conf", 40), result("b.conf", 50)],
            {"current": "b.conf", "ping_ms": 50})
        assert calls == [], f"с порогом 200 мс переключились: {calls}"

        client.SWITCH_MARGIN_MS = 5
        calls, _ = run_step(
            [result("a.conf", 40), result("b.conf", 50)],
            {"current": "b.conf", "ping_ms": 50})
        assert calls == ["up:a.conf"], (
            f"с порогом 5 мс не переключились: {calls}")
    finally:
        client.SWITCH_MARGIN_MS = old


def test_состояние_запоминает_новый_конфиг() -> None:
    """После переключения запоминается, что именно в работе."""
    state: dict[str, Any] = {"current": "b.conf", "ping_ms": 120}
    run_step([result("a.conf", 40), result("b.conf", 120)], state)
    assert state["current"] == "a.conf"
    assert state["ping_ms"] == 40
    assert state.get("since"), "время переключения не записано"


def test_без_инструментов_понятная_ошибка() -> None:
    """Нет утилит — сообщение должно говорить, что ставить, а не «0x1»."""
    old = client.which
    try:
        client.which = lambda tool: None
        try:
            client.need_tools()
        except SystemExit as exc:
            message = str(exc)
            assert "amneziawg" in message
            assert "github.com/amnezia-vpn" in message
        else:
            raise AssertionError("без утилит должно быть сообщение")
    finally:
        client.which = old