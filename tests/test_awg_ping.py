"""Анализатор конфигов Amnezia: разбор файлов и решение «жив или нет».

Проверка сети подменяется заглушками: тест, который зависит от того,
дотянулся ли до чужого сервера сегодня, завтра сломается без нашей
помощи. Само решение — считать ли конфиг рабочим — проверяется здесь
по-настоящему, потому что именно в нём была ошибка: первая версия
скрипта мерила время отправки UDP-пакета и выдавала его за задержку,
и все пятнадцать конфигов показывали одинаковые 700 миллисекунд.

Что считается правильным ответом
--------------------------------
Закрытый порт — это приговор: сервера на нём нет, конфиг не заработает
ни при каких условиях. Тишина — это нормальное поведение AmneziaWG,
такой конфиг остаётся рабочим. Путать эти два случая нельзя, и
проверяется здесь именно то, что путать нельзя.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

_spec = importlib.util.spec_from_file_location("awg_ping", TOOLS / "awg_ping.py")
assert _spec and _spec.loader
awg = importlib.util.module_from_spec(_spec)
sys.modules["awg_ping"] = awg
_spec.loader.exec_module(awg)

# Настоящий кусок конфига из вложений: обфусцированные заголовки и
# нестандартный порт. Именно из-за них нужен собственный разбор.
SAMPLE = """[Interface]
PrivateKey = n1AQTH3Wmp2uC24ZT/Gratuvfbc2vkFKqMe1vSSyU4M=
Address = 172.16.0.2, 2606:4700:110:8554:23f2:e26f:2e37:bd98
DNS = 1.1.1.1
MTU = 1280
S1 = 0
H1 = 1
I1 = <b 0xce0000000108>

[Peer]
PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = ru0.tribukvy.ltd:7103
"""


def test_читает_адрес_и_порт() -> None:
    """Из конфига берутся только адрес и порт."""
    found = awg.parse_configs(SAMPLE, "ru0.conf")
    assert len(found) == 1
    item = found[0]
    assert item["host"] == "ru0.tribukvy.ltd"
    assert item["port"] == 7103
    assert item["file"] == "ru0.conf"


def test_замечает_обфускацию_amnezia() -> None:
    """Параметры S, H и I отличают amneziawg от обычного wireguard.

    Убирать нужно все три: любой из них означает, что заголовки
    обфусцированы, а одиночный `I1` без `S1` — такой же признак, как
    и все вместе.
    """
    assert awg.parse_configs(SAMPLE, "x.conf")[0]["amnezia"] is True
    plain = SAMPLE
    for marker in ("S1 = 0", "H1 = 1", "I1 = <b 0xce0000000108>"):
        plain = plain.replace(marker + "\n", "")
    assert awg.parse_configs(plain, "y.conf")[0]["amnezia"] is False


def test_закрытый_порт_ведёт_конфиг_в_тупик() -> None:
    """Главное правило: закрытый порт — конфиг нерабочий.

    Именно здесь важен порядок проверок. Закрытый порт перевешивает
    задержку: медленный, но живой сервер полезен, а быстрый и
    закрытый бесполезен совсем.
    """
    monkey = pytest.MonkeyPatch()
    monkey.setattr(awg, "resolve", lambda host, timeout=3.0: ("203.0.113.5", 0.0, ""))
    # Порт закрыт, но задержка отличная — результат должен быть
    # отрицательным, иначе в выдачу попадёт мёртвый конфиг.
    monkey.setattr(awg, "tcp_rtt", lambda address, tries=3: (12.0, "443", 3))
    monkey.setattr(awg, "udp_probe", lambda address, port, timeout=0.7:
                   (False, "порт закрыт — сервера нет"))
    try:
        result = awg.check({"file": "closed.conf", "host": "x.test",
                            "port": 5555, "amnezia": True, "is_ip": True}, probes=2)
    finally:
        monkey.undo()
    assert result["alive"] is False
    assert result["verdict"] == "ПОРТ ЗАКРЫТ"


def test_тишина_означает_живой_порт() -> None:
    """AmneziaWG не отвечает на мусор — тишина это норма, а не смерть."""
    monkey = pytest.MonkeyPatch()
    monkey.setattr(awg, "resolve", lambda host, timeout=3.0: ("198.51.100.9", 0.0, ""))
    monkey.setattr(awg, "tcp_rtt", lambda address, tries=3: (95.0, "443", 3))
    monkey.setattr(awg, "udp_probe", lambda address, port, timeout=0.7:
                   (True, "тишина (так и должен работать AmneziaWG)"))
    try:
        result = awg.check({"file": "live.conf", "host": "y.test",
                            "port": 7103, "amnezia": True, "is_ip": True}, probes=2)
    finally:
        monkey.undo()
    assert result["alive"] is True
    assert result["ping_ms"] == 95.0
    assert "СРЕДНЕ" in result["verdict"]


def test_неразрешимое_имя_останавливает_проверку() -> None:
    """Нет адреса — дальше идти незачем, конфиг не заработает никогда."""
    monkey = pytest.MonkeyPatch()
    monkey.setattr(awg, "resolve",
                   lambda host, timeout=3.0: ("", None, "имя не найдено"))
    called = {"udp": 0}

    def counting(address: str, port: int, timeout: float = 0.7) -> tuple[bool, str]:
        called["udp"] += 1
        return True, ""

    monkey.setattr(awg, "udp_probe", counting)
    try:
        result = awg.check({"file": "bad.conf", "host": "nope.invalid",
                            "port": 1234, "amnezia": True, "is_ip": False}, probes=2)
    finally:
        monkey.undo()
    assert result["alive"] is False
    assert result["verdict"] == "НЕ РАЗРЕШАЕТСЯ"
    assert called["udp"] == 0, "пробуют порт, хотя адреса нет"


@pytest.mark.parametrize(("ping", "expected"), [
    (25, "ОТЛИЧНО"),
    (60, "ХОРОШО"),
    (150, "СРЕДНЕ"),
    (400, "ДАЛЕКО"),
])
def test_оценки_задержки_по_шкале(ping: float, expected: str) -> None:
    """Границы шкалы задержки не должны молча сдвинуться.

    Пороги подобраны под реальные каналы: быстрый городской, обычный
    европейский и через океан. Если их поменять, ранжирование перестанет
    соответствовать тому, что человек видит на самом деле.
    """
    monkey = pytest.MonkeyPatch()
    monkey.setattr(awg, "resolve", lambda host, timeout=3.0: ("198.51.100.1", 0.0, ""))
    monkey.setattr(awg, "tcp_rtt", lambda address, tries=3: (ping, "443", 3))
    monkey.setattr(awg, "udp_probe", lambda address, port, timeout=0.7: (True, "тишина"))
    try:
        result = awg.check({"file": "t.conf", "host": "z.test", "port": 1,
                            "amnezia": True, "is_ip": True}, probes=2)
    finally:
        monkey.undo()
    assert result["verdict"] == expected


def test_задержка_из_udp_не_берётся() -> None:
    """Регрессия: время «до тишины» не должно считаться задержкой.

    Отправка UDP-пакета в порт amneziawg занимает ровно столько,
    сколько отвечает таймаут: сервер на мусор не отвечает. Если такую
    величину назвать пингом, все конфиги получат одинаковую правдоподобную
    цифру и сортировка станет случайной.
    """
    monkey = pytest.MonkeyPatch()
    monkey.setattr(awg, "resolve", lambda host, timeout=3.0: ("198.51.100.2", 0.0, ""))
    # Задержка приходит только из TCP-рукопожатия, и она честная.
    monkey.setattr(awg, "tcp_rtt", lambda address, tries=3: (77.0, "2053", 4))
    monkey.setattr(awg, "udp_probe", lambda address, port, timeout=0.7: (True, "тишина"))
    try:
        result = awg.check({"file": "r.conf", "host": "r.test", "port": 1,
                            "amnezia": True, "is_ip": True}, probes=2)
    finally:
        monkey.undo()
    assert result["ping_ms"] == 77.0
    assert result["rtt_port"] == "2053"
    assert "times" not in result, (
        "время UDP-пробы снова попало в результат как задержка")


def test_приватный_ключ_не_попадает_в_результат() -> None:
    """Закрытый ключ в вывод утекать не должен.

    Он попадает в отчёт, а отчёт копируют в чат и на скриншот. Сам
    ключ для проверки не нужен, поэтому и не читается.
    """
    found = awg.parse_configs(SAMPLE, "key.conf")
    blob = str(found)
    assert "PrivateKey" not in blob
    assert "n1AQTH3Wmp2uC24ZT" not in blob


def test_пустой_файл_не_роняет_разбор() -> None:
    """Файл без строки Endpoint — это не конфиг, и это не ошибка."""
    assert awg.parse_configs("just text\nwithout endpoint\n", "junk.txt") == []


def test_сортировка_кладёт_быстрые_вперёд() -> None:
    """Порядок выдачи: живые, затем по задержке."""
    results: list[dict[str, Any]] = [
        {"file": "dead.conf", "alive": False, "ping_ms": None, "verdict": "ПОРТ ЗАКРЫТ"},
        {"file": "slow.conf", "alive": True, "ping_ms": 300, "verdict": "ДАЛЕКО"},
        {"file": "fast.conf", "alive": True, "ping_ms": 40, "verdict": "ОТЛИЧНО"},
    ]
    order = {"ОТЛИЧНО": 0, "ХОРОШО": 1, "СРЕДНЕ": 2, "ДАЛЕКО": 3}
    results.sort(key=lambda r: (
        not r.get("alive"),
        order.get(str(r["verdict"]).split(" ")[0], 4),
        r.get("ping_ms") or 99999,
    ))
    assert [r["file"] for r in results] == ["fast.conf", "slow.conf", "dead.conf"]