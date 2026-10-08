#!/usr/bin/env python3
r"""Клиент Xray для Windows: подключение по конфигам WARP.

Зачем свой клиент, а не Nekoray или v2rayN
--------------------------------------------
Готовые клиенты (Nekoray, v2rayN) работают с ключами
VLESS, которые импортируются в окне вручную. Наши конфиги —
другое: это готовые JSON-файлы Xray с WireGuard-аутбаундом,
и их нужно просто отдать xray.exe. Отдельный клиент решает
три вещи, которых в готовых программах нет:

1. **Выбор лучшего.** Задержка до каждого адреса меряется
   TCP-рукопожатием (ICMP недоступен, а UDP-замер бессмысленен
   — см. awg_ping), и подключение идёт к самому быстрому.
2. **Авторежим.** Раз в `ROTATE_MIN` минут адреса меряются
   заново, и туннель переключается, только если новый лучший
   быстрее текущего более чем на `SWITCH_MARGIN_MS`.
3. **Проверка.** После запуска клиент сам открывает адрес
   через локальный прокси: если ответа нет, конфиг не работает,
   и об этом сказано сразу, а не по молчанию.

Что делает клиент с системой
-----------------------------
Никакого системного прокси. Xray слушает только
127.0.0.1:10808 (SOCKS) и 127.0.0.1:10809 (HTTP). Программы
ходят в интернет через него, если указать эти адреса сами:

    set HTTP_PROXY=http://127.0.0.1:10809
    set HTTPS_PROXY=http://127.0.0.1:10809
    set NO_PROXY=localhost,127.0.0.1

Это намеренно: «включил VPN» и «весь трафик через WARP» —
разные вещи, и второй режим должен включаться осознанно.

Где живут ключи
----------------
Конфиги читаются из папки загрузок (по умолчанию) или из
папки, заданной ключом `--from`. В репозиторий они не
попадают: внутри каждого файла лежит приватный ключ
WireGuard, а приватные ключи в репозиторий не выкладываются.

Установка
---------
    .venv\\Scripts\\python.exe tools\\xray_client.py install
    .venv\\Scripts\\python.exe tools\\xray_client.py list
    .venv\\Scripts\\python.exe tools\\xray_client.py ping
    .venv\\Scripts\\python.exe tools\\xray_client.py up 3
    .venv\\Scripts\\python.exe tools\\xray_client.py status
    .venv\\Scripts\\python.exe tools\\xray_client.py down
    .venv\\Scripts\\python.exe tools\\xray_client.py auto --rotate 30
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Где искать конфиги по умолчанию. Именно туда приходят
#: файлы от владельца VPN, и именно поэтому папка задаётся
#: ключом: у другого пользователя путь будет свой.
DEFAULT_SOURCE = Path.home() / "Downloads"

#: Маска конфигов. Все файлы от владельца называются
#: одинаково, и маска ловит только их, не трогая остальное.
CONFIG_GLOB = "XrayWARP*.json"

#: Папка программы: сам xray.exe и рабочая копия конфига.
#: Обе внутри tmp/ — в репозиторий не попадают, и на место
#: их всегда можно поставить заново.
BIN_DIR = ROOT / "tmp" / "xray-bin"
RUN_DIR = ROOT / "tmp" / "xray-run"

#: Локальные порты. Конфиги слушают именно их, а два
#: конфига одновременно не встанут: второй не сможет
#: занять уже занятые порты.
SOCKS_PORT = 10808
HTTP_PORT = 10809

#: Свежий портативный Xray для Windows. Версия не зафиксирована
#: намеренно: протокол WireGuard стабилен, а в новых сборках
#: чинятся рукопожатия с провайдерами.
DOWNLOAD_URL = ("https://github.com/XTLS/Xray-core/releases/"
                "latest/download/Xray-windows-64.zip")

#: Адрес проверки туннеля. Простой текстовый адрес, отвечает
#: всегда, TLS не нужен: если через прокси пришёл ответ,
#: трафик дошёл до выхода WARP.
PROBE_HOST = "cp.cloudflare.com"

#: Как часто менять туннель в авторежиме, минут.
ROTATE_MIN = 30

#: На сколько миллисекунд текущий туннель должен быть хуже
#: лучшего, чтобы переключиться. Без порога туннель прыгал
#: бы между двумя почти одинаковыми адресами каждые полчаса,
#: а переподключение обрывает сессии.
SWITCH_MARGIN_MS = 25

#: Таймауты. Рукопожатие — секунды, проверка туннеля —
#: чуть больше, потому что путь длиннее.
TCP_TIMEOUT = 3.0
PROBE_TIMEOUT = 10.0

#: Сколько раз меряется рукопожатие. Берётся минимум: одна
#: неудачная проба из-за чужого трафика не должна портить
#: картину.
RTT_TRIES = 3


def find_configs(folder: Path) -> list[Path]:
    """Найти конфиги в папке. Возвращает отсортированный список."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob(CONFIG_GLOB) if p.is_file())


def describe(path: Path) -> tuple[str, str]:
    """Имя конфига и адрес выхода из него.

    Имя берётся из поля remarks — так подписал конфигы
    владелец. Адрес — endpoint первого пира WireGuard:
    именно до него мерится задержка.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    name = data.get("remarks") or data.get("remark") or path.stem
    endpoint = ""
    for outbound in data.get("outbounds", []):
        if outbound.get("protocol") != "wireguard":
            continue
        peers = outbound.get("settings", {}).get("peers") or []
        if peers and peers[0].get("endpoint"):
            endpoint = peers[0]["endpoint"]
        break
    return str(name), endpoint


def split_endpoint(endpoint: str) -> tuple[str, int]:
    """Разобрать адрес вида host:port. Возвращает (хост, порт)."""
    host, _, port = endpoint.rpartition(":")
    return host, int(port or 0)


def tcp_rtt(host: str, port: int,
            timeout: float = TCP_TIMEOUT) -> float | None:
    """Задержка TCP-рукопожатия в миллисекундах.

    ICMP из Python на Windows недоступен, а UDP-замер не
    отражает скорость туннеля. TCP-рукопожатие — тот же путь,
    которым пойдут данные, поэтому оно и меряется.
    """
    best: float | None = None
    for _ in range(RTT_TRIES):
        started = time.perf_counter()
        try:
            with socket.create_connection((host, port),
                                          timeout=timeout):
                elapsed = (time.perf_counter() - started) * 1000
        except OSError:
            continue
        best = elapsed if best is None else min(best, elapsed)
    return best


def rank(paths: list[Path]) -> list[tuple[Path, str, float | None]]:
    """Измерить задержку до каждого конфига. Возвращает список
    (файл, адрес, миллисекунды) — живые первыми, по возрастанию."""
    measured: list[tuple[Path, str, float | None]] = []
    for path in paths:
        _, endpoint = describe(path)
        if not endpoint:
            measured.append((path, "", None))
            continue
        host, port = split_endpoint(endpoint)
        measured.append((path, endpoint, tcp_rtt(host, port)))
    live = [row for row in measured if row[2] is not None]
    dead = [row for row in measured if row[2] is None]
    live.sort(key=lambda row: row[2])
    return live + dead


# =============================================================== установка


def xray_binary() -> Path | None:
    """Путь к xray.exe, если он уже скачан."""
    candidate = BIN_DIR / "xray.exe"
    return candidate if candidate.is_file() else None


def install(timeout: float = 300.0) -> Path:
    """Скачать портативный Xray и вернуть путь к exe.

    Качается архив целиком, а не exe: в архиве кроме exe есть
    геоданные, без которых Xray ругается на запуск.
    """
    existing = xray_binary()
    if existing:
        return existing

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    archive = BIN_DIR / "xray.zip"
    print(f"качую Xray: {DOWNLOAD_URL}")
    with urllib.request.urlopen(DOWNLOAD_URL, timeout=timeout) as answer, \
            archive.open("wb") as target:
        shutil.copyfileobj(answer, target)

    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(BIN_DIR)
    archive.unlink()

    binary = xray_binary()
    if binary is None:
        raise RuntimeError("в архиве нет xray.exe")
    return binary


# =============================================================== запуск


def state_file() -> Path:
    """Файл состояния: какой конфиг поднят и какой процесс."""
    return RUN_DIR / "state.json"


def read_state() -> dict[str, object]:
    """Прочитать состояние. Пустой словарь — ничего не поднято."""
    path = state_file()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(state: dict[str, object]) -> None:
    """Записать состояние."""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    state_file().write_text(json.dumps(state, ensure_ascii=False,
                                       indent=2), encoding="utf-8")


def proxy_alive() -> bool:
    """Отвечает ли локальный HTTP-прокси."""
    try:
        with socket.create_connection(("127.0.0.1", HTTP_PORT),
                                      timeout=1.0):
            return True
    except OSError:
        return False


def probe_proxy(timeout: float = PROBE_TIMEOUT) -> str:
    """Открыть адрес через прокси. Возвращает строку статуса.

    Возвращается именно первая строка ответа («HTTP/1.1 200
    OK»), а не тело: по ней видно, что запрос дошёл до выхода
    WARP и вернулся.
    """
    request = (f"GET http://{PROBE_HOST}/ HTTP/1.1\r\n"
               f"Host: {PROBE_HOST}\r\n"
               "Connection: close\r\n\r\n")
    try:
        with socket.create_connection(("127.0.0.1", HTTP_PORT),
                                      timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request.encode())
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(len(c) for c in chunks) > 64 * 1024:
                    break
    except OSError as exc:
        return f"нет связи с прокси: {exc}"

    head = b"".join(chunks).split(b"\r\n", 1)[0]
    return head.decode("ascii", errors="replace") or "пустой ответ"


def up(config: Path) -> tuple[bool, str]:
    """Поднять туннель по конфигу. Возвращает (получилось, записка)."""
    binary = xray_binary()
    if binary is None:
        return False, "xray.exe не найден — сначала: install"
    if not config.is_file():
        return False, f"конфига нет: {config}"

    # Один туннель за раз: второй не встанет на те же порты.
    if proxy_alive():
        stopped = down()
        if not stopped[0]:
            return False, f"старый туннель не снялся: {stopped[1]}"

    # Рабочая копия конфига — побайтово. Xray читает её, а
    # оригинал в Downloads трогать не надо.
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    active = RUN_DIR / "active.json"
    active.write_bytes(config.read_bytes())

    log = (RUN_DIR / "xray.log").open("wb")
    flags = 0
    if os.name == "nt":
        # Окно консоли не выскакивает: клиент запускается из
        # bat-файла двойным щелчком.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(binary), "run", "-c", str(active)],
        cwd=str(RUN_DIR), stdout=log, stderr=subprocess.STDOUT,
        creationflags=flags)

    name, endpoint = describe(config)
    write_state({"pid": process.pid, "config": str(config),
                 "name": name, "endpoint": endpoint,
                 "started": time.time()})

    # Туннель поднимается не мгновенно: ждём, пока порт
    # ответит, и проверяем выход в интернет.
    for _ in range(int(PROBE_TIMEOUT)):
        if proxy_alive():
            break
        if process.poll() is not None:
            return False, f"xray.exe упал сразу — см. {RUN_DIR}/xray.log"
        time.sleep(1.0)
    else:
        return False, "порт не открылся вовремя — см. xray.log"

    status = probe_proxy()
    if "200" not in status and "301" not in status and \
            "302" not in status:
        return False, f"туннель поднялся, но выхода нет: {status}"
    return True, f"{name} ({endpoint}): {status}"


def down() -> tuple[bool, str]:
    """Опустить туннель. Возвращает (получилось, записка)."""
    state = read_state()
    if not state:
        if proxy_alive():
            return False, ("порт занят чужим процессом — найдите его "
                           "в диспетчере задач")
        return True, "ничего не поднято"

    pid = state.get("pid")
    if pid is not None:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       capture_output=True, timeout=30)
    for leftover in RUN_DIR.glob("active.json"):
        leftover.unlink()
    state_file().unlink(missing_ok=True)

    for _ in range(10):
        if not proxy_alive():
            return True, f"туннель {state.get('name', '')} снят"
        time.sleep(0.5)
    return False, "порт всё ещё занят"


def status() -> dict[str, object]:
    """Текущее состояние клиента."""
    state = read_state()
    alive = proxy_alive()
    result: dict[str, object] = {
        "running": bool(state) and alive,
        "name": state.get("name", ""),
        "endpoint": state.get("endpoint", ""),
        "proxy": f"127.0.0.1:{HTTP_PORT}",
    }
    if alive:
        result["probe"] = probe_proxy()
    return result


# =============================================================== авторежим


def should_switch(current_ms: float, best_ms: float,
                  margin: float = SWITCH_MARGIN_MS) -> bool:
    """Стоит ли переключаться. Порог — чтобы не дёргать туннель.

    Переключение происходит, только когда выигрыш больше
    порога: на паре миллисекунд менять туннель нельзя, и
    соединения рвутся зря.
    """
    return (current_ms - best_ms) > margin


def auto(rotate_min: int = ROTATE_MIN, margin: float = SWITCH_MARGIN_MS,
         once: bool = False, dry_run: bool = False,
         folder: Path = DEFAULT_SOURCE) -> int:
    """Авторежим: меряет все адреса и переключается на лучший.

    Логика та же, что в awg_client: текущий туннель меряется
    отдельно, и переключение — только при выигрыше больше
    порога. `once` — один шаг без цикла, `--dry-run` — без
    реального переключения.
    """
    configs = find_configs(folder)
    if not configs:
        print(f"конфигов нет в {folder}")
        return 1

    while True:
        print(f"\nмеряю {len(configs)} адресов: "
              f"{time.strftime('%H:%M:%S')}")
        table = rank(configs)
        for path, endpoint, ms in table:
            _, name = describe(path)
            mark = f"{ms:.0f} мс" if ms is not None else "недоступен"
            print(f"  {name:12} {endpoint:30} {mark}")

        live = [row for row in table if row[2] is not None]
        if not live:
            print("ни один адрес не отвечает — жду")
        else:
            best_path, best_endpoint, best_ms = live[0]
            state = read_state()
            current_endpoint = str(state.get("endpoint", ""))
            # Текущий туннель меряется по своему адресу: если он
            # отвалился, задержка не измерится, и переключение
            # произойдёт в любом случае.
            if current_endpoint:
                host, port = split_endpoint(current_endpoint)
                current_ms = tcp_rtt(host, port)
            else:
                current_ms = None

            best_name, _ = describe(best_path)
            if current_ms is None:
                reason = "текущий туннель не отвечает"
            elif should_switch(current_ms, best_ms, margin):
                reason = (f"выигрыш {current_ms - best_ms:.0f} мс "
                          f"при пороге {margin:.0f}")
            else:
                print(f"  оставляем {state.get('name', '?')}: "
                      f"{current_ms:.0f} → {best_ms:.0f} мс, "
                      f"выигрыш меньше порога {margin:.0f} мс")
                reason = None

            if reason:
                print(f"  переключаю на {best_name} ({best_endpoint}): "
                      f"{reason}")
                if not dry_run:
                    result = up(best_path)
                    print(f"  {'ок' if result[0] else 'сбой'}: "
                          f"{result[1]}")

        if once:
            return 0
        time.sleep(rotate_min * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="клиент Xray WARP")
    parser.add_argument("--from", dest="folder",
                        default=str(DEFAULT_SOURCE),
                        help="папка с конфигами")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("install", help="скачать xray.exe")
    commands.add_parser("list", help="список конфигов")
    commands.add_parser("ping", help="замер задержек")
    commands.add_parser("status", help="состояние туннеля")
    commands.add_parser("down", help="опустить туннель")

    up_cmd = commands.add_parser("up", help="поднять туннель")
    up_cmd.add_argument("which", nargs="?", default="best",
                        help="номер или имя конфига, best — самый "
                             "быстрый")

    auto_cmd = commands.add_parser("auto", help="авторежим")
    auto_cmd.add_argument("--rotate", type=int, default=ROTATE_MIN,
                          help="как часто мерить, минут")
    auto_cmd.add_argument("--margin", type=float,
                          default=SWITCH_MARGIN_MS,
                          help="выигрыш для переключения, мс")
    auto_cmd.add_argument("--once", action="store_true",
                          help="один шаг, без цикла")
    auto_cmd.add_argument("--dry-run", action="store_true",
                          help="без реального переключения")

    args = parser.parse_args()
    folder = Path(args.folder)

    if args.command == "install":
        binary = install()
        version = subprocess.run([str(binary), "version"],
                                 capture_output=True, text=True,
                                 timeout=60)
        print(f"xray.exe: {binary}")
        print(version.stdout.strip() or version.stderr.strip())
        return 0

    configs = find_configs(folder)
    if not configs:
        print(f"конфигов нет в {folder}")
        print("Скопируйте файлы XrayWARP_*.json в папку загрузок "
              "или укажите --from")
        return 1

    if args.command == "list":
        for index, path in enumerate(configs, 1):
            name, endpoint = describe(path)
            print(f"  {index:2} {name:12} {endpoint}")
        return 0

    if args.command == "ping":
        table = rank(configs)
        for path, endpoint, ms in table:
            name, _ = describe(path)
            mark = f"{ms:.0f} мс" if ms is not None else "недоступен"
            print(f"  {name:12} {endpoint:30} {mark}")
        return 0

    if args.command == "status":
        info = status()
        if info["running"]:
            print(f"поднят: {info['name']} ({info['endpoint']})")
            print(f"прокси: socks5://{info['proxy']}, "
                  f"http://{info['proxy']}")
            print(f"проверка: {info.get('probe', '')}")
        else:
            print("туннель не поднят")
        return 0

    if args.command == "down":
        ok, note = down()
        print(note)
        return 0 if ok else 1

    if args.command == "up":
        which = str(args.which)
        if which == "best":
            table = rank(configs)
            live = [row for row in table if row[2] is not None]
            if not live:
                print("ни один адрес не отвечает")
                return 1
            chosen = live[0][0]
        elif which.isdigit():
            index = int(which)
            if not 1 <= index <= len(configs):
                print(f"номер от 1 до {len(configs)}")
                return 1
            chosen = configs[index - 1]
        else:
            hits = [p for p in configs
                    if which.lower() in describe(p)[0].lower()]
            if len(hits) != 1:
                print(f"подходящих конфигов: {len(hits)}")
                return 1
            chosen = hits[0]

        ok, note = up(chosen)
        print(("ок: " if ok else "сбой: ") + note)
        if ok:
            print(f"прокси: http://127.0.0.1:{HTTP_PORT}")
            print("Чтобы ходить через него из консоли:")
            print(f"  set HTTP_PROXY=http://127.0.0.1:{HTTP_PORT}")
            print(f"  set HTTPS_PROXY=http://127.0.0.1:{HTTP_PORT}")
            print("  set NO_PROXY=localhost,127.0.0.1")
        return 0 if ok else 1

    if args.command == "auto":
        return auto(args.rotate, args.margin, args.once,
                    args.dry_run, folder)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
