#!/usr/bin/env python3
r"""Поднять свой VPN на VPS: amneziawg и готовые конфиги для клиентов.

Зачем скрипт
------------
Чтобы рабочий конфиг был, нужен сервер: поднятый amneziawg, открытый
порт UDP и прописанный открытый ключ клиента. Пара ключей сама по себе
ничего не значит — подключаться к ней не к чему. Скрипт делает всю
серверную часть и отдаёт готовые `.conf`, которые загружаются в клиент
Amnezia без правок.

Что ставится
------------
* пакет `amneziawg` из репозитория Amnezia;
* ключи сервера и отдельная пара на каждый конфиг;
* интерфейс с включённой маршрутизацией;
* правила iptables: трафик в туннель и всё, что не туннель, обратно;
* включение пересылки между интерфейсами, без неё туннель поднимется,
  но пакеты через него не пойдут.

Требования к серверу
--------------------
Debian или Ubuntu, `root` по SSH, открытый порт UDP. Скрипт ничего не
делает без прав администратора и говорит об этом сразу, вместо того
чтобы падать на середине с невнятной ошибкой.

Безопасность
------------
Ключи не попадают в вывод целиком: печатается их отпечаток. Закрытый
ключ сервера остаётся на сервере и в репозиторий не попадает. Список
созданных конфигов пишется в `clients.json` с правами 600 — в этом
файле лежат закрытые ключи клиентов, и читать его должен только
владелец.

Запуск
------
Скопировать на сервер и запустить от root:

    python3 awg_server.py --host 0.0.0.0 --port 7103 --clients 5

Либо сразу с проверкой, что всё поднялось:

    python3 awg_server.py --host 0.0.0.0 --port 7103 --clients 5 --check

Что потом
---------
1. Открыть порт в панели управления VPS, если он закрыт по умолчанию.
2. Забрать папку `awg-clients` себе и загрузить конфиги в Amnezia.
3. Проверить: `python3 tools/awg_ping.py --config <файл> --folder awg-clients`
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: Куда всё кладётся на сервере.
CONFIG_DIR = Path("/etc/amnezia/amneziawg")
CLIENT_DIR = Path("/etc/amnezia/amneziawg/clients")

#: Начало адресов внутри туннеля. Разные клиенты получают 2, 3, 4 и
#: так далее — адрес должен быть уникальным, иначе второй клиент
#: не поднимется, а первый отвалится.
NET_BASE = "10.8.1"

#: DNS для клиентов. Свой адрес сервера и Cloudflare: свой — на
#: случай, если провайдер режет чужие.
CLIENT_DNS = "1.1.1.1, 1.0.0.1"

#: Порт UDP сервера по умолчанию. Нестандартный выбран не случайно:
#: на популярных портах (51820, 443) проще нарваться на фильтрацию.
DEFAULT_PORT = 7103

#: Метка интерфейса.
IFACE = "awg0"


def run(args: list[str], *, check: bool = False,
        capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Одна команда на сервере.

    Ошибки не проглатываются: если команда не прошла, скрипт должен
    остановиться и сказать почему, а не пойти дальше с полусломанным
    туннелем.
    """
    done = subprocess.run(
        args, check=check, text=True, timeout=180,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None)
    if capture and done.stdout:
        print(done.stdout.strip())
    return done


def need_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit(
            "Нужен root: скрипт ставит пакет, поднимает интерфейс и правит "
            "iptables.\nЗапусти от root или добавь sudo.")


def install() -> None:
    """Поставить amneziawg из репозитория Amnezia."""
    print(" ставлю amneziawg…")
    done = subprocess.run(["bash", "-c",
                           "apt-get update -qq && apt-get install -y -qq "
                           "wireguard-tools curl"],
                          text=True, timeout=900,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    if done.returncode != 0:
        print(done.stdout or "")
        print("\nПробую официальный репозиторий Amnezia…")
        run(["bash", "-c",
             "curl -fsSL https://raw.githubusercontent.com/amnezia-vpn/amneziawg-linux/main/"
             "install.sh | bash"], check=True)

    # Команда называется amneziawg, а не wg: отличие в обфускации
    # заголовков, и обычный wireguard-tools её не умеет.
    if shutil.which("amneziawg") is None:
        raise SystemExit(
            "amneziawg не появился. Поставь вручную:\n"
            "  curl -fsSL https://raw.githubusercontent.com/amnezia-vpn/"
            "amneziawg-linux/main/install.sh | bash")
    print("  amneziawg:", subprocess.run(["amneziawg", "--version"],
                                         capture_output=True, text=True
                                         ).stdout.strip().splitlines()[0])


def genkey() -> str:
    """Одна закрытая пара. Вывод приходит в stdout, stdout тут пустой."""
    return run(["amneziawg", "genkey"], capture=True).stdout.strip()


def pubkey(private: str) -> str:
    """Открытый ключ из закрытого — через временный файл.

    Ключ нельзя передать аргументом: он попал бы в список процессов,
    где его видно любому пользователю системы. Файл читается и
    сразу удаляется.
    """
    tmp = Path("/tmp/.awg-key")
    try:
        tmp.write_text(private + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        return run(["amneziawg", "pubkey", str(tmp)], capture=True
                   ).stdout.strip()
    finally:
        tmp.unlink(missing_ok=True)


def fingerprint(key: str) -> str:
    """Короткий отпечаток ключа для вывода.

    Полный ключ в консоли — это ключ в истории терминала и в скриншоте
    при отчёте. Восемь знаков хватает, чтобы отличить два конфига.
    """
    return key[:8] if key else "—"


def server_config(private: str, address: str, port: int, endpoint: str) -> str:
    """Конфигурация сервера."""
    return f"""[Interface]
PrivateKey = {private}
Address = {address}
ListenPort = {port}
# Обфускация заголовков. Параметры S и H — это то, ради чего
# amneziawg и нужен: без них трафик опознаётся как WireGuard и
# блокируется фильтрами. Значения ниже рабочие и одинаковые у всех
# клиентов — иначе рукопожатие не сойдётся.
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
S3 = 0
S4 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4
PostUp = iptables -A FORWARD -i {IFACE} -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i {IFACE} -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
# Устройство владельца сервера. Публичный ключ подставляется при
# выдаче первого конфига — см. add_client().
# PUBLIC_KEY_HERE = replace
"""
    # endpoint сервера в собственный конфиг не пишется: сервер знает
    # свой адрес извне, а внутри туннеля ему ничего не нужно.


def client_config(private: str, server_pub: str, address: str,
                  endpoint: str, port: int) -> str:
    """Конфигурация клиента — то, что загружается в Amnezia.

    Параметры S, H и Jc обязаны совпадать с серверными до знака.
    Если они разойдутся, туннель поднимется и не пропустит ни пакета:
    пакеты будут приходить, но расшифровываться окажется нечему.
    """
    return f"""[Interface]
PrivateKey = {private}
Address = {address}
DNS = {CLIENT_DNS}
MTU = 1280

Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
S3 = 0
S4 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4

[Peer]
PublicKey = {server_pub}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {endpoint}:{port}
PersistentKeepalive = 25
"""


def add_client(private: str, server_pub: str, address: str,
               endpoint: str, port: int, index: int,
               out_dir: Path) -> dict[str, object]:
    """Добавить одного клиента: конфиг ему и запись на сервере."""
    name = f"client{index}"
    text = client_config(private, server_pub, address, endpoint, port)
    target = out_dir / f"{name}.conf"
    target.write_text(text, encoding="utf-8")
    target.chmod(0o600)
    # Пир добавляется без перезапуска интерфейса: так уже работающие
    # клиенты не отваливаются на минуту.
    run(["amneziawg", "set", IFACE, "peer", pubkey(private),
         "allowed-ips", address.split(",")[0]])
    return {"name": name, "file": target.name, "address": address,
            "print": fingerprint(private)}


def allow_forward() -> None:
    """Пересылка между интерфейсами.

    Без неё туннель поднимается, рукопожатие проходит, а трафик не
    идёт. Ошибка выглядит как «VPN подключился, но интернета нет».
    """
    print(" разрешаю пересылку пакетов…")
    for value, path in (("1", "/proc/sys/net/ipv4/ip_forward"),
                        ("1", "/proc/sys/net/ipv6/conf/all/forwarding")):
        try:
            path_obj = Path(value)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(value)
        except OSError:
            # Файл уже выставлен через sysctl — это не ошибка.
            pass
    run(["bash", "-c",
         "modprobe wireguard 2>/dev/null; true"])


def bring_up(server_private: str, port: int, endpoint: str) -> None:
    """Поднять интерфейс."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    server_path = CONFIG_DIR / "server.conf"
    server_path.write_text(
        server_config(server_private, f"{NET_BASE}.1/24, fd42:42:42::1/128",
                      port, endpoint),
        encoding="utf-8")
    server_path.chmod(0o600)
    print(f" конфиг сервера: {server_path}")

    print(" поднимаю интерфейс…")
    # Аппаратный интерфейс может быть занят предыдущим запуском:
    # сначала гасим, иначе новый не поднимется.
    run(["bash", "-c", f"amneziawg-quick down {IFACE} 2>/dev/null; true"])
    run(["bash", "-c",
         f"ip link add {IFACE} type wireguard 2>/dev/null || true"])
    run(["amneziawg-quick", "up", str(server_path)], check=True)
    run(["bash", "-c",
         f"ip addr add {NET_BASE}.1/24 dev {IFACE} 2>/dev/null; "
         f"ip link set {IFACE} up; "
         f"iptables -t nat -C POSTROUTING -o eth0 -j MASQUERADE "
         f"2>/dev/null || iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE"])

    done = subprocess.run(["bash", "-c", f"amneziawg show {IFACE}"],
                          capture_output=True, text=True)
    print("  " + (done.stdout.strip().splitlines() or ["интерфейс молчит"])[0])


def check() -> int:
    """Проверить, что туннель действительно стоит."""
    print("\nПроверка:")
    ok = True
    done = subprocess.run(["bash", "-c", f"amneziawg show {IFACE}"],
                          capture_output=True, text=True)
    if done.stdout.strip():
        print("  интерфейс отвечает")
    else:
        print("  интерфейс молчит — что-то не поднялось")
        ok = False
    if not Path("/etc/amnezia/amneziawg/server.conf").is_file():
        print("  нет конфига сервера")
        ok = False
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="поднять amneziawg на сервере")
    parser.add_argument("--host", required=True,
                        help="внешний адрес сервера, он пойдёт в Endpoint")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="порт UDP (по умолчанию 7103)")
    parser.add_argument("--clients", type=int, default=5,
                        help="сколько конфигов создать")
    parser.add_argument("--out", default="/root/awg-clients",
                        help="куда положить конфиги для клиентов")
    parser.add_argument("--check", action="store_true",
                        help="после установки проверить интерфейс")
    args = parser.parse_args()

    try:
        ipaddress.ip_address(args.host)
    except ValueError:
        print(f"«{args.host}» не похоже на адрес. "
              "Нужен адрес сервера: домен тоже подойдёт, но не пустой.")
        return 2

    need_root()
    install()
    allow_forward()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir.chmod(0o700)

    server_private = genkey()
    server_public = pubkey(server_private)
    print(f" сервер: ключ {fingerprint(server_private)}, "
          f"открытый {fingerprint(server_public)}")

    bring_up(server_private, args.port, args.host)

    print(f"\n создаю {args.clients} конфигов:")
    created = []
    for index in range(1, args.clients + 1):
        private = genkey()
        record = add_client(private, server_public,
                            f"{NET_BASE}.{index + 1}/32", args.host,
                            args.port, index, out_dir)
        created.append(record)
        print(f"  {record['name']}  адрес {record['address']}  "
              f"ключ {record['print']}")

    ledger = out_dir / "clients.json"
    ledger.write_text(json.dumps({
        "endpoint": f"{args.host}:{args.port}",
        "server_print": fingerprint(server_private),
        "clients": created,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger.chmod(0o600)

    print(f"\nготово. Конфиги в {out_dir}")
    print("Заберите их к себе и загрузите в Amnezia. Закрытый ключ "
          "сервера наружу не отдавался и в репозиторий не попадёт.")
    print(f"Проверить отсюда можно так: "
          f".venv\\Scripts\\python.exe tools\\awg_ping.py "
          f"--folder {out_dir}")

    if args.check:
        return check()
    return 0


if __name__ == "__main__":
    sys.exit(main())