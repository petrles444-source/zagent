"""Регрессии: агент обязан читать собственный исходник и не вставать из-за этого.

Здесь три ошибки, которые человек сразу увидел бы, но которые молчали:

* `read_file` объявлял бинарным сам `hub/tools.py` — модуль, который
  определяет поиск бинарников, содержал их подписи как текст;
* двоичный файл останавливал всю задачу вопросом человеку;
* «делай всё, не спрашивая» (YOLO) не отменяло вопросов: решение принималось
  по настройке «выходить за папку».
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.agent import Agent, AgentConfig, make_guard  # noqa: E402
from hub.autonomy import AccessLevel, Autonomy, Escalation  # noqa: E402
from hub.tools import looks_binary, run_tool  # noqa: E402


# ============================================================ бинарники


def test_исходник_инструментов_читается() -> None:
    """Главное. Файл, который определяет `BINARY_MARKERS`, содержит их как
    текст — и при поиске подстрок объявлял бинарным сам себя. Агент,
    которому поручили аудит этого проекта, доходил до `hub/tools.py` и
    получал отказ.

    Слово «GIF8» в комментарии — это не картинка.
    """
    source = (ROOT / "hub" / "tools.py").read_bytes()[:4096]
    assert looks_binary(source) is False, (
        "модуль определения бинарников не должен считать бинарным себя")


@pytest.mark.parametrize("name", [
    "hub/agent.py", "hub/worker.py", "hub/ui.py", "hub/swarm_run.py",
    "README.md", "config/tiers.json", "config/gateways.json",
])
def test_исходники_читаются(name: str) -> None:
    source = (ROOT / name).read_bytes()[:4096]
    assert looks_binary(source) is False, f"{name} принят за двоичный"


@pytest.mark.parametrize("data", [
    b"GIF89a" + bytes(200),
    b"GIF87a" + bytes(200),
    b"PK\x03\x04" + bytes(200),
    b"\x89PNG\r\n\x1a\n" + bytes(200),
    b"\xff\xd8\xff\xe0" + bytes(200),
    b"%PDF-1.7\n" + bytes(200),
    b"\x7fELF\x02\x01" + bytes(200),
    bytes(300),
])
def test_настоящие_бинарники_узнаются(data: bytes) -> None:
    assert looks_binary(data) is True


def test_подпись_в_середине_текста_не_считается_файлом() -> None:
    """Подпись должна быть в начале файла, а не где попало.

    Именно на этом стоял баг: `b"GIF8"` находился в комментарии, а
    настоящая картинка начинается с `GIF89a` в первом байте.
    """
    text = "Документ описывает форматы: GIF89a, PK\\x03\\x04, %PDF-."
    assert looks_binary(text.encode("utf-8")) is False


@pytest.mark.parametrize("codec", ["utf-8", "cp1251", "cp866"])
def test_русский_текст_читается_в_любой_кодировке(codec: str) -> None:
    """Файл в windows-1251 не декодируется как UTF-8, но читается прекрасно.

    На русской машине таких файлов осталось немало, и раньше такой файл
    объявлялся двоичным — то есть агент не мог прочитать исходник на
    соседнем компьютере.
    """
    body = 'def f():\n    """Привет, мир."""\n    return "Привет"\n'
    assert looks_binary(body.encode(codec)) is False


def test_мусор_не_проходит_за_текст() -> None:
    """В однобайтовой кодировке раскладывается любая последовательность
    байтов, поэтому «декодируется» — недостаточный признак. Проверяется
    правдоподобие: у текста почти нет управляющих символов."""
    noise = bytes((b * 37 + 11) % 256 for b in range(200))
    assert looks_binary(noise) is True


# ============================================================ чтение


def test_чтение_своего_исходника_проходит(tmp_path: Path) -> None:
    """Сквозная проверка настоящим инструментом, а не только функцией."""
    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=Autonomy.YOLO)
    guard = make_guard(config)
    guard.set_workspace(str(tmp_path), None)

    source = (ROOT / "hub" / "tools.py").read_text(encoding="utf-8")
    (tmp_path / "tools.py").write_text(source, encoding="utf-8")

    got = run_tool("read_file", guard, base=tmp_path, path="tools.py")
    assert got.ok, got.error
    assert got.needs_user is False
    assert "Инструменты агента" in str(got.data.get("content") or "")


def test_бинарный_файл_не_останавливает_задачу(tmp_path: Path) -> None:
    """Двоичный файл — пропущенный файл, а не препятствие.

    Раньше на него задавался вопрос человеку, и работа вставала: «Сделать
    скриншот или прочитать метаданные?» — на что человек ответить не мог.
    """
    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=Autonomy.YOLO)
    guard = make_guard(config)
    guard.set_workspace(str(tmp_path), None)
    (tmp_path / "картинка.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(300))

    got = run_tool("read_file", guard, base=tmp_path, path="картинка.png")
    assert got.ok is False, "двоичный файл нельзя прочитать как текст"
    assert got.needs_user is False, "задачу нельзя останавливать из-за файла"
    assert "Пропусти" in str(got.error), (
        "сообщение должно говорить агенту, что делать дальше")


# ============================================================ вопросы


class _Sel:
    require_vision = False

    def stats(self) -> dict:
        return {}


def _agent(tmp_path: Path, autonomy: Autonomy,
           escalation: Escalation = Escalation.AUTO) -> Agent:
    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=autonomy)
    guard = make_guard(config)
    guard.escalation = escalation
    guard.set_workspace(str(tmp_path), None)
    return Agent(_Sel(), guard, config)


def _ask(tmp_path: Path, autonomy: Autonomy,
         escalation: Escalation = Escalation.AUTO) -> bool:
    """Остановится ли агент на инструменте, попросившем помощи.

    Подменяется `run_tool` именно в `hub.agent`: модуль импортирует его по
    имени, и подмена в `hub.tools` на него не действует. Отдельно проверяется,
    что подмена действительно сработала: вопрос не появился бы и просто
    потому, что инструмент не выполнялся, и проверка прошла бы вхолостую.
    """
    import asyncio

    import hub.agent as agent_mod

    calls = []

    def asks(name, guard, *, base=None, **kwargs):
        calls.append(name)
        return agent_mod.ToolResult(
            False, error="нужна помощь", needs_user=True,
            question="Продолжать?")

    original = agent_mod.run_tool
    agent_mod.run_tool = asks
    try:
        agent = _agent(tmp_path, autonomy, escalation)

        async def scenario() -> bool:
            await agent._run_tool({"tool": "read_file", "path": "x"}, "gw/м")
            return agent.pending_question is not None

        asked = asyncio.run(scenario())
        assert calls == ["read_file"], f"инструмент не выполнился: {calls}"
        return asked
    finally:
        agent_mod.run_tool = original


def test_yolo_не_спрашивает(tmp_path: Path) -> None:
    """«Делай всё, не спрашивая» обязано означать именно это.

    Условие остановки проверяло только `escalation` — настройку «можно ли
    выходить за папку», — и автономия в нём не участвовала. При полном
    доступе и YOLO агент всё равно вставал и ждал ответа человека.
    """
    assert _ask(tmp_path, Autonomy.YOLO) is False, (
        "YOLO остановился и ждёт ответа")


def test_yolo_не_спрашивает_даже_при_escalation_on(tmp_path: Path) -> None:
    """Даже «спрашивать при любой неуверенности» не должно перебивать YOLO.

    Иначе настройка автономии оказывается сильнее неё, то есть не
    работает вовсе.
    """
    assert _ask(tmp_path, Autonomy.YOLO, Escalation.ON) is False


def test_обычный_режим_по_прежнему_спрашивает(tmp_path: Path) -> None:
    """Проверка на то, что «не спрашивать в YOLO» не превратилось в
    «не спрашивать никогда»."""
    assert _ask(tmp_path, Autonomy.NORMAL) is True


def test_escalation_off_не_спрашивает(tmp_path: Path) -> None:
    assert _ask(tmp_path, Autonomy.NORMAL, Escalation.OFF) is False


# ============================================================ свой код


def test_чтение_своего_кода_не_запрещено(tmp_path: Path) -> None:
    """`self_edit` ограничивает запись в код программы, а не чтение.

    Проверяется явно, потому что вопрос «не защита ли это мешает читать?» —
    разумный: режим разработки выключен по умолчанию, и можно решить, что
    он блокирует и чтение.
    """
    config = AgentConfig(base_dir=str(tmp_path), access=AccessLevel.FULL,
                         autonomy=Autonomy.YOLO)
    guard = make_guard(config)
    guard.set_workspace(str(tmp_path), None)
    (tmp_path / "hub").mkdir()
    (tmp_path / "hub" / "tools.py").write_text("x = 1\n", encoding="utf-8")

    got = run_tool("read_file", guard, base=tmp_path, path="hub/tools.py")
    assert got.ok, f"чтение своего кода запрещено: {got.error}"