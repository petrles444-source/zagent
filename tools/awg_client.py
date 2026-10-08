#!/usr/bin/env python3
r"""Клиент amneziawg: подключение, проверка и авторежим на 30 минут.

Зачем отдельный клиент, а не окно Amnezia
----------------------------------------
У Amnezia есть служба и окно, но нет документированной команды
управления: конфиги импортируются через окно, и автоматика там
невозможна. Отдельная утилита `amneziawg` управляется из командной
строки, и весь режим «работает само и переключается» делается на ней.

Что делает авторежим
--------------------
Каждые `ROTATE_MIN` минут:
1. измеряется задержка до каждого конфига (см. `awg_ping`);
2. выбираются живые, из них — самый быстрый;
3. если текущий туннель хуже лучшего более чем на `SWITCH_MARGIN_MS`,
   происходит переключение; если не хуже — ничего не трогаем.

Порог нужен, чтобы не дёргать туннель на каждом шаге из-за пары
миллисекунд разницы: переподключение обрывает сессии, и делать его
каждые полчаса без нужды — вредно.

Что нужно установить
--------------------
    https://github.com/amnezia-vpn/amneziawg-tools
    amneziawg.exe и amneziawg-quick.exe должны быть в PATH

Запуск
------
    .venv\\Scripts\\python.exe tools\\awg_client.py list
    .venv\\Scripts\\python.exe tools\\awg_client.py up --config ru0.conf
    .venv\\Scripts\\python.exe tools\\awg_client.py status
    .venv\\Scripts\\python.exe tools\\awg_client.py auto --rotate 30
    .venv\\Scripts\\python.exe tools\\awg_client.py auto --once --dry-run

Права
-----
Поднять интерфейс может только администратор. Скрипм это проверяет
и говорит заранее, а не падает на середине.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from awg_ping import check, collect  # noqa: E402

#: Интерфейс туннеля. Имя нестандартное, чтобы не пересекаться с
#: обычным WireGuard, если он тоже стоит.
IFACE = "awg0"

#: Как часто менять туннель в авторежиме, минут.
ROTATE_MIN = 30

#: На сколько миллисекунд текущий туннель должен быть хуже лучшего,
#: чтобы переключиться. Без этого порога туннель прыгал бы между
#: двумя почти одинаковыми конфигами на каждом шаге.
SWITCH_MARGIN_MS = 25

#: Файл с состоянием: какой конфиг сейчас поднят и с какого адреса.
STATE = Path.home() / ".awg-auto" / "state.json"


def which(tool: str) -> str | None:
    """Найти утилиту: сначала в PATH, потом в типовых папках."""
    found = shutil.which(tool)
    if found:
        return found
    for folder in (Path(r"C:\Program Files\AmneziaVPN"),
                   Path(r"C:\Program Files\amneziawg"),
                   Path.home() / "amneziawg"):
        candidate = folder / f"{tool}.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def need_tools() -> tuple[str, str]:
    """Проверить наличие утилит и права. Проверка до начала работы."""
    quick = which("amneziawg-quick")
    guard = which("amneziawg")
    missing = [n for n, p in (("amneziawg-quick", quick),
                              ("amneziawg", guard)) if not p]
    if missing:
        raise SystemExit(
            "Не найдены утилиты: " + ", ".join(missing) + "\n"
            "Поставить: https://github.com/amnezia-vpn/amneziawg-tools\n"
            "После установки путь к папке с ними должен быть в PATH.")
    try:
        import ctypes
        ctypes.windll.shell32.IsUserAnAdmin()
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        # Без windll считаем, что прав нет, и проверяем пробой.
        admin = False
    return quick or "", guard or ""


def read_state() -> dict[str, object]:
    """Прочитать состояние. Пустое состояние — не ошибка."""
    if not STATE.is_file():
        return {"current": "", "ping_ms": None, "since": ""}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"current": "", "ping_ms": None, "since": ""}


def write_state(data: dict[str, object]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def status() -> int:
    """Что сейчас поднято."""
    done = subprocess.run([which("amneziawg") or "amneziawg", "show", IFACE],
                          capture_output=True, text=True, timeout=20)
    state = read_state()
    print(f"конфиг в работе: {state.get('current') or '—'}")
    print(f"задержка: {state.get('ping_ms') or '—'} мс")
    print(f"с: {state.get('since') or '—'}")
    if done.stdout.strip():
        print("\nинтерфейс отвечает:")
        for line in done.stdout.strip().splitlines()[:6]:
            print("  " + line)
    else:
        print("\nинтерфейс не поднят")
    return 0


def down() -> None:
    """Снести туннель."""
    subprocess.run([which("amneziawg-quick") or "amneziawg-quick",
                    "down", IFACE],
                   capture_output=True, timeout=30)


def up(config: Path) -> tuple[bool, str]:
    """Поднять туннель из конфига. Возвращает (получилось, записка)."""
    # Прежний туннель гасим всегда: если новый не поднимется,
    # старый всё равно должен уйти, иначе останется мёртвое соединение,
    # которое выглядит как живое.
    down()
    quick = which("amneziawg-quick") or "amneziawg-quick"
    done = subprocess.run([quick, "up", str(config)],
                          capture_output=True, text=True, timeout=90)
    if done.returncode != 0:
        message = (done.stderr or done.stdout or "").strip()
        return False, message[:200] or "неизвестная ошибка"
    return True, ""


def folder_list(folder: Path) -> int:
    """Что лежит в папке с конфигами."""
    files = sorted(folder.glob("*.conf"))
    if not files:
        print(f"в папке {folder} нет файлов .conf")
        return 2
    state = read_state()
    print(f"в папке {folder}:")
    for path in files:
        mark = " ← в работе" if path.name == state.get("current") else ""
        print(f"  {path.name}{mark}")
    print(f"\nвсего: {len(files)}")
    return 0


def pick(folder: Path, probes: int) -> list[dict[str, object]]:
    """Проверить все конфиги и отсортировать от лучшего к худшему."""
    configs = collect(folder, [])
    if not configs:
        return []
    results = []
    for config in configs:
        print(f"  проверяю {config['file']}…", flush=True)
        results.append(check(config, probes))
    order = {"ОТЛИЧНО": 0, "ХОРОШО": 1, "СРЕДНЕ": 2, "ДАЛЕКО": 3}
    results.sort(key=lambda r: (
        not r.get("alive"),
        order.get(str(r["verdict"]).split(" ")[0], 4),
        r.get("ping_ms") or 99999,
    ))
    return results


def auto_once(folder: Path, probes: int, dry_run: bool,
              force: bool) -> int:
    """Один шаг авторежима: проверить, выбрать, возможно переключить."""
    print(f"\n[{time.strftime('%H:%M:%S')}] проверяю конфиги…")
    results = pick(folder, probes)
    alive = [r for r in results if r.get("alive")]
    if not alive:
        print("живых конфигов нет — оставляю как есть")
        return 1

    best = alive[0]
    state = read_state()
    current_name = str(state.get("current") or "")
    current_ping = state.get("ping_ms")

    # Ищем, чему равен текущий конфиг в этом замере: без этого
    # сравнивать не с чем, и пришлось бы каждый раз переподключаться.
    current = next((r for r in results if r["file"] == current_name), None)
    current_now = current.get("ping_ms") if current else None

    print(f"лучший: {best['file']} ({best.get('ping_ms')} мс)")
    if current_name:
        print(f"сейчас: {current_name} ({current_now or '—'} мс)")

    if not force and current_name == best["file"]:
        print("переключение не нужно — лучший уже в работе")
        return 0

    if not force and current_now is not None and best.get("ping_ms") is not None:
        gain = current_now - float(best["ping_ms"])
        if gain < SWITCH_MARGIN_MS:
            print(f"разница {gain:.0f} мс меньше порога "
                  f"{SWITCH_MARGIN_MS} — не трогаю")
            return 0

    if dry_run:
        print(f"СУХОЙ РЕЖИМ: поднял бы {best['file']}")
        return 0

    print(f"переключаю на {best['file']}…")
    ok, note = up(folder / str(best["file"]))
    if not ok:
        print(f"не поднялось: {note}")
        return 1
    write_state({"current": best["file"],
                 "ping_ms": best.get("ping_ms"),
                 "since": time.strftime("%Y-%m-%d %H:%M")})
    print(f"поднято, задержка {best.get('ping_ms')} мс")
    return 0


def auto(folder: Path, rotate: int, probes: int, dry_run: bool) -> int:
    """Авторежим: крутится, пока не остановят."""
    need_tools()
    print(f"авторежим: каждые {rotate} мин, папка {folder}")
    print("остановить — Ctrl+C")
    while True:
        try:
            auto_once(folder, probes, dry_run, force=False)
        except KeyboardInterrupt:
            print("\nостановлено")
            return 0
        except Exception as exc:
            print(f"ошибка шага: {type(exc).__name__}: {exc}")
        # Спим остаток интервала. Проверка занимает своё время, и
        # без вычета прошло бы 30 минут плюс проверка.
        wait = rotate * 60
        spent = 0
        try:
            while spent < wait:
                time.sleep(min(15, wait - spent))
                spent += 15
        except KeyboardInterrupt:
            print("\nостановлено")
            return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="клиент amneziawg")
    parser.add_argument("command",
                        choices=["list", "up", "down", "status", "auto"])
    parser.add_argument("--folder", default=str(Path.home() / "Downloads"),
                        help="папка с конфигами .conf")
    parser.add_argument("--config", help="файл конфига для up")
    parser.add_argument("--rotate", type=int, default=ROTATE_MIN,
                        help="минут между проверками")
    parser.add_argument("--probes", type=int, default=4)
    parser.add_argument("--once", action="store_true",
                        help="один шаг и выход")
    parser.add_argument("--dry-run", action="store_true",
                        help="ничего не переключать, только показать")
    parser.add_argument("--force", action="store_true",
                        help="переключиться, даже если невыгодно")
    args = parser.parse_args()

    folder = Path(args.folder)

    if args.command == "list":
        return folder_list(folder)
    if args.command == "status":
        return status()
    if args.command == "down":
        need_tools()
        down()
        print("туннель снесён")
        return 0
    if args.command == "up":
        need_tools()
        if not args.config:
            print("укажи --config с файлом")
            return 2
        ok, note = up(folder / args.config if not Path(args.config).exists()
                      else Path(args.config))
        if not ok:
            print(f"не поднялось: {note}")
            return 1
        print(f"поднято из {args.config}")
        write_state({"current": os.path.basename(args.config),
                     "ping_ms": None,
                     "since": time.strftime("%Y-%m-%d %H:%M")})
        return 0
    if args.command == "auto":
        if args.once:
            need_tools()
            return auto_once(folder, args.probes, args.dry_run, args.force)
        return auto(folder, args.rotate, args.probes, args.dry_run)
    return 2


if __name__ == "__main__":
    sys.exit(main())