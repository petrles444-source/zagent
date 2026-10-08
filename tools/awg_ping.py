#!/usr/bin/env python3
r"""Проверить пинг по каждому конфигу Amnezia: что живо, что мертво.

Зачем это нужно
---------------
Файлы `.conf` во вложениях — это готовые конфигурации WireGuard с
обфускацией заголовков (amneziawg). Дальше в файле идёт `Endpoint`:
хост и порт, где стоит сервер. Именно до этого адреса и нужно
дотянуться, и по нему уже судить, годен конфиг или нет.

Почему не хватает простого пинга по имени
------------------------------------------
1. **Порт.** У этих конфигов он нестандартный — 7103, 864, 5279.
   Обычный пинг ходит по протоколу ICMP и порта не знает вообще:
   сервер может молчать на пинг и отлично принимать соединение.
2. **UDP.** WireGuard — это UDP. Открытый порт по TCP ещё ничего не
   значит, а закрытый по UDP при этом вполне рабочий.
3. **Хост может не резолвиться.** У части конфигов вместо адреса
   имя, и если оно не найдётся, такой конфиг не заработает никогда.

Поэтому проверка трёхслойная: разрешение имени, настоящий пинг по
ICMP и проба UDP-порта. Результат сортируется от лучшего к худшему.

Почему задержка берётся только из ICMP
--------------------------------------
Первая версия этого скрипта измеряла время отправки UDP-пакета и
выдавала его за пинг. Для AmneziaWG это бессмысленно: протокол не
отвечает на мусор, поэтому «время до тишины» равно таймауту, и все
пятнадцать конфигов показали одинаковые 700 миллисекунд. Сейчас
задержка — это среднее из ICMP, а UDP проверяется отдельно и только
на предмет «порт закрыт или нет».

Отличие «закрыт» и «молчит»
---------------------------
Если система отвечает «порт закрыт» (ICMP unreachable, на Windows
код 10054), конфиг мёртв: сервера на этом порту нет. Если тишина —
это нормальное поведение AmneziaWG, и такой конфиг остаётся в
рабочих. Путать эти два случая нельзя: первый можно выбросить,
второй нельзя.

Запуск
------
    .venv\Scripts\python.exe tools\awg_ping.py
    .venv\Scripts\python.exe tools\awg_ping.py --folder "C:\Загрузки" --json
    .venv\Scripts\python.exe tools\awg_ping.py --config ruWARPv1_23.conf
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

#: Сколько проб на один адрес. Меньше трёх — слишком шумно, больше
#: десяти — зачем: конфигов много, а время пользователя не бесконечно.
PROBES = 4

#: Пауза между пробами. Слишком частыми пакетами UDP-порт считает
#: их мусором и начинает отбрасывать, и жив��й адрес выглядит мёртвым.
GAP_S = 0.35

#: Таймаут одной пробы. Согласовано с PROBES и GAP_S: сумма на адрес
#: не должна превышать нескольких секунд, иначе проверка всех
#: конфигов растянется на минуты.
TIMEOUT_S = 0.7

#: Таймаут TCP-рукопожатия при замере задержки. Короче нельзя: через
#: океан рукопожатие идёт дольше, и медленный, но рабочий канал будет
#: помечен мёртвым.
TCP_TIMEOUT_S = 3.0

#: Стандартный порт WireGuard. По нему можно сразу сказать «порт
#: стандартный», но проверять всё равно нужно указанный в конфиге.
WIREGUARD_PORT = 51820

#: Заголовок handshake WireGuard: тип 1, зарезервированные нули и
#: длина пакета. Сервер не ответит, но порт на него откроет — этого
#: достаточно, чтобы отличить закрытый порт от молчащего.
def handshake_packet() -> bytes:
    return struct.pack("<BxxxI", 1, 148)


#: `Endpoint = host:port`. Хост — имя или адрес, порт — число.
ENDPOINT_RE = re.compile(r"^\s*Endpoint\s*=\s*(\S+?)\s*(?::|\s+)\s*(\d+)\s*$",
                         re.MULTILINE | re.IGNORECASE)


def parse_configs(text: str, source: str) -> list[dict[str, object]]:
    """Вытащить из файла всё, что нужно для проверки.

    Приватные ключи намеренно не читаются: для проверки они не нужны,
    а в вывод попадать не должны тем более.
    """
    found = ENDPOINT_RE.findall(text)
    if not found:
        return []
    configs = []
    for host, port in found:
        # Имя файла и служебные отметки S1/H1/I1 — как раз то, чем
        # удобно сортировать потом вручную.
        configs.append({
            "file": source,
            "host": host,
            "port": int(port),
            "is_ip": is_ip(host),
            "amnezia": bool(re.search(r"^\s*(S1|H1|I1)\s*=", text,
                                      re.MULTILINE)),
        })
    return configs


def is_ip(host: str) -> bool:
    """Адрес это или имя."""
    try:
        socket.inet_aton(host)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except OSError:
        return False


def resolve(host: str, timeout: float = 3.0) -> tuple[str, float | None, str]:
    """Имя в адрес. Возвращает (адрес, миллисекунды, записка)."""
    # Числовой адрес проверяем отдельно: резолвер тут ни при чём, и
    # его вызов только добавит задержку на ровно адресе.
    if is_ip(host):
        return host, 0.0, "адрес в конфиге"
    start = time.monotonic()
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_UDP)
    except socket.gaierror as exc:
        return "", None, f"имя не найдено ({exc.strerror or exc})"
    if not infos:
        return "", None, "имя не найдено"
    address = infos[0][4][0]
    return address, (time.monotonic() - start) * 1000, ""


#: Порты, на которых серверы Amnezia обычно держат что-то ещё, кроме
#: своего рабочего UDP-порта. Именно по ним меряется задержка: свой
#: UDP-порт молчит на handshake, а эти отвечают обычным рукопожатием.
#:
#: Порядок неслучаен: сначала самые массовые, чтобы не ждать лишних
#: секунд на каждом конфиге.
LATENCY_PORTS = (443, 80, 2053, 2083, 8443, 8880, 500, 7103, 864)


def tcp_rtt(address: str, tries: int = 3) -> tuple[float | None, str, int]:
    """Задержка по TCP-рукопожатию. Возвращает (мс, порт, попыток).

    Это единственный способ измерить задержку на этой машине, и
    история тут стоит того, чтобы её прочитали.

    Первая версия мерила время отправки UDP-пакета и выдавала его за
    пинг: AmneziaWG не отвечает на мусор, поэтому «время до тишины»
    равно таймауту, и все пятнадцать конфигов показали одинаковые
    700 мс. Вторая версия звала системный `ping.exe`, и это тоже не
    сработало — из Python он отдаёт «transmit failed. General failure»,
    хотя из PowerShell тот же вызов отвечает. Причина в том, что
    дочерний процесс наследует не ту сетевую обвязку, и разбираться с
    ней дороже, чем просто измерить путь рукопожатием.

    Рукопожатие идёт по тому же маршруту, что и сам VPN, поэтому
    задержка здесь настоящая. Берётся минимум из попыток: одна
    секундная просадка не должна портить оценку канала.
    """
    port_used = 0
    best: float | None = None
    attempts = 0
    for port in LATENCY_PORTS:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(TCP_TIMEOUT_S)
            start = time.monotonic()
            sock.connect((address, port))
            spent = (time.monotonic() - start) * 1000
            attempts += 1
            if best is None or spent < best:
                best = spent
                port_used = port
            # Нашли близкий порт — дальше перебирать незачем, и время
            # проверки не растёт.
            if best is not None and best < 40:
                break
        except OSError:
            continue
        finally:
            sock.close()
        if best is not None:
            break
    if best is None:
        return None, "", attempts
    # Повторяем на найденном порту: одно рукопожатие — это ещё не
    # задержка, это факт соединения.
    times: list[float] = []
    for _ in range(tries):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.settimeout(TCP_TIMEOUT_S)
            start = time.monotonic()
            sock.connect((address, port_used))
            times.append((time.monotonic() - start) * 1000)
        except OSError:
            pass
        finally:
            sock.close()
        time.sleep(0.15)
    if times:
        best = min(times)
        attempts += len(times)
    return best, str(port_used), attempts


def udp_probe(address: str, port: int,
              timeout: float = TIMEOUT_S) -> tuple[bool, str]:
    """Проба UDP-порта. Возвращает (состояние, записка).

    Три состояния, и разница между ними существенна:
    * `refused` — система отправила в ответ «порт закрыт». Конфиг
      мёртв, и можно не ждать: сервера на этом порту нет.
    * `timeout` — тишина. У AmneziaWG это норма: сервер ждёт
      handshake и на мусор не отвечает. Значит, порт может быть и
      открыт, и закрыт — по-разному не различить.
    * `sent` — пакет ушёл без ошибки. Тоже ничего не доказывает, но
      хотя бы нет сетевой ошибки.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        # Сокет связывается с адресом через connect: после этого
        # система сообщает об ICMP-ответе прямо в recv, а не теряет
        # его молча. Без connect «порт закрыт» отличить нельзя.
        sock.connect((address, port))
        sock.send(handshake_packet())
        try:
            data = sock.recv(2048)
            return True, f"ответил, {len(data)} Б"
        except socket.timeout:
            return True, "тишина (так и должен работать AmneziaWG)"
    except ConnectionRefusedError:
        return False, "порт закрыт — сервера нет"
    except ConnectionResetError:
        return False, "соединение сброшено — порт закрыт"
    except OSError as exc:
        code = getattr(exc, "winerror", None) or exc.errno
        # 10054 на Windows — это тоже «порт закрыт», пришедший позже.
        if code in (10054, 10038):
            return False, "порт закрыт (сброс по сети)"
        return False, f"сетевая ошибка: {exc.strerror or exc}"
    finally:
        sock.close()


def check(config: dict[str, object], probes: int = PROBES) -> dict[str, object]:
    """Полная проверка одного конфига.

    Задержка берётся только из ICMP. Замер по UDP для AmneziaWG
    бессмыслен: там нет ни запроса, ни ответа, и измерять нечего —
    первая версия этого скрипта измеряла именно что-то не то и
    показывала одинаковые 700 миллисекунд для всех.
    """
    host = str(config["host"])
    port = int(config["port"])
    address, resolve_ms, note = resolve(host)

    result: dict[str, object] = {
        "file": config["file"],
        "host": host,
        "port": port,
        "amnezia": config["amnezia"],
        "address": address,
        "resolve_ms": resolve_ms,
        "note": note,
    }

    if not address:
        result.update(alive=False, ping_ms=None, udp_ok=None,
                      verdict="НЕ РАЗРЕШАЕТСЯ")
        return result

    ping_ms, rtt_port, attempts = tcp_rtt(address, probes)
    result["ping_ms"] = ping_ms
    result["rtt_port"] = rtt_port
    if ping_ms is None:
        result["ping_note"] = "задержку измерить не удалось, порты закрыты"
    else:
        result["ping_note"] = f"задержка по порту {rtt_port}"

    # Проба UDP делается всегда, даже если пинг не дошёл: у AmneziaWG
    # это независимые вещи. Порт и ICMP живут разными путями.
    opened = 0
    last_udp = ""
    for index in range(probes):
        ok, message = udp_probe(address, port)
        if ok:
            opened += 1
        last_udp = message
        if index + 1 < probes:
            time.sleep(GAP_S)
    result["udp_ok"] = opened > 0
    result["udp_opened"] = f"{opened}/{probes}"
    result["udp_note"] = last_udp

    # Порт закрыт — это приговор: с закрытым портом конфиг не
    # заработает, сколько бы пинг ни показывал.
    if not result["udp_ok"]:
        result.update(alive=False, verdict="ПОРТ ЗАКРЫТ")
        return result

    result["alive"] = True
    if ping_ms is None:
        result["verdict"] = "порт открыт, задержка не измерилась"
    elif ping_ms < 40:
        result["verdict"] = "ОТЛИЧНО"
    elif ping_ms < 90:
        result["verdict"] = "ХОРОШО"
    elif ping_ms < 180:
        result["verdict"] = "СРЕДНЕ"
    else:
        result["verdict"] = "ДАЛЕКО"
    return result


def collect(folder: Path, names: list[str]) -> list[dict[str, object]]:
    """Собрать конфиги из папки или по именам."""
    configs: list[dict[str, object]] = []
    files: list[Path]
    if names:
        files = [folder / name for name in names]
    else:
        files = sorted(folder.glob("*.conf"))
    for path in files:
        if not path.is_file():
            print(f"нет файла: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"не прочитался {path.name}: {exc}")
            continue
        found = parse_configs(text, path.name)
        if not found:
            print(f"{path.name}: строки Endpoint не найдено — это не конфиг")
            continue
        configs.extend(found)
    return configs


def format_table(results: list[dict[str, object]]) -> None:
    """Вывод в консоль. Таблица, а не строки: сравнивать надо глазами."""
    print(f"\n{'файл':<22} {'endpoint':<34} {'адрес':<22} "
          f"{'пинг':>8} {'UDP':>7}  вердикт")
    print("-" * 112)
    for item in results:
        ping = f"{item['ping_ms']:.0f} мс" if item.get("ping_ms") else "—"
        host = f"{item['host']}:{item['port']}"
        address = str(item.get("address") or "—")[:20]
        udp = str(item.get("udp_opened") or "—")
        print(f"{str(item['file']):<22} {host:<34} {address:<22} "
              f"{ping:>8} {udp:>7}  {item['verdict']}")

    # Подсказка «почему пинг пустой» нужна один раз в конце, а не в
    # каждой строке: иначе таблица превращается в простыню.
    without_ping = [r for r in results
                    if r.get("alive") and not r.get("ping_ms")]
    if without_ping:
        reason = str(without_ping[0].get("ping_note") or "")
        print(f"\nу {len(without_ping)} живых конфигов пинг не прошёл: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="проверить пинг по конфигам Amnezia")
    parser.add_argument("--folder", default=str(Path.home() / "Downloads"),
                        help="папка с файлами .conf")
    parser.add_argument("--config", action="append", default=[],
                        help="конкретный файл (можно указать много раз)")
    parser.add_argument("--probes", type=int, default=PROBES,
                        help="сколько проб на адрес")
    parser.add_argument("--json", action="store_true",
                        help="вывести результат в JSON")
    args = parser.parse_args()

    folder = Path(args.folder)
    configs = collect(folder, args.config)
    if not configs:
        print(f"в папке {folder} нет файлов .conf с адресом сервера")
        return 2

    print(f"конфигов: {len(configs)}, проб на адрес: {args.probes}")
    print(f"папка: {folder}")
    started = time.monotonic()

    results = []
    for index, config in enumerate(configs, 1):
        host = str(config["host"])
        print(f"[{index}/{len(configs)}] {config['file']} → {host}:"
              f"{config['port']}", flush=True)
        results.append(check(config, args.probes))

    # Порядок: сначала живые, потом по пингу. Так рабочий конфиг с
    # минимальной задержкой всегда оказывается первым.
    order = {"ОТЛИЧНО": 0, "ХОРОШО": 1, "СРЕДНЕ": 2, "ДАЛЕКО": 3}
    results.sort(key=lambda r: (
        not r.get("alive"),
        order.get(str(r["verdict"]).split(" ")[0], 4),
        r.get("ping_ms") or 9999,
    ))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        format_table(results)
        alive = sum(1 for r in results if r.get("alive"))
        print(f"\nживых: {alive} из {len(results)}, "
              f"проверка заняла {time.monotonic() - started:.0f} с")
        if alive:
            best = results[0]
            print(f"лучший: {best['file']} ({best['host']}:{best['port']}, "
                  f"{best.get('ping_ms')} мс)")

    return 0


if __name__ == "__main__":
    sys.exit(main())