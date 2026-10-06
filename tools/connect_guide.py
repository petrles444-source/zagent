#!/usr/bin/env python3
r"""Печать инструкций: как подключить модели zagent в другой софт.

    python tools\connect_guide.py                    все инструменты
    python tools\connect_guide.py opencode           только OpenCode
    python tools\connect_guide.py opencode --json    машинный вид

Использует ключи из config/secrets.local.json: цель в том, чтобы не искать их
по сайтам. В stdout попадают значения полностью — это локальная утилита.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.config import load_gateways, project_root  # noqa: E402
from hub.connect import TARGET_LABELS, TARGET_REASONS, TARGETS, build_guide  # noqa: E402
from hub.registry import collect  # noqa: E402


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def print_guide(guide: dict, only: str | None = None) -> None:
    order = [only] if only else guide["target_order"]

    for target in order:
        block = guide["targets"].get(target)
        if block is None:
            print(f"Неизвестный инструмент: {target}")
            print("Доступные: " + ", ".join(guide["target_order"]))
            return

        usable = [e for e in block["entries"] if e.get("available")]
        blocked = [e for e in block["entries"] if not e.get("available")]

        print()
        print("=" * 72)
        print(f"  {block['label']}")
        print("=" * 72)

        if not usable:
            print()
            print("  Нет подключаемых шлюзов. Причины:")
            for entry in blocked:
                print(f"    {entry['label']}: {entry.get('reason')}")
            continue

        for entry in usable:
            print()
            print(f"  --- {entry['label']} " + "-" * max(0, 56 - len(entry['label'])))
            print(f"  provider id : {entry['provider_id']}")
            print(f"  base URL    : {entry['base_url']}")
            if entry.get("keyless"):
                print("  api key     : не нужен")
            else:
                print(f"  api key     : {entry.get('api_key') or '(не задан)'}")
                print(f"  переменная  : {entry['env_var']}")
            print(f"  моделей     : {len(entry.get('models') or [])}")
            print()
            for line in (entry.get("instruction") or "").splitlines():
                print(f"  {line}")

        if blocked:
            print()
            print("  Не подключается:")
            for entry in blocked:
                print(f"    {entry['label']}: {entry.get('reason')}")

    if only and TARGET_REASONS.get(only):
        print()
        print(f"  Важно: {TARGET_REASONS[only]}")


async def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(description="Инструкции по подключению моделей")
    parser.add_argument("target", nargs="?", choices=sorted(TARGETS),
                        help="инструмент; без аргумента — все")
    parser.add_argument("--json", action="store_true", help="вывести JSON")
    args = parser.parse_args(argv)

    root = project_root()
    try:
        gateways = load_gateways(root, env={})
    except Exception as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2

    try:
        registry = await collect(gateways, root=root)
    except Exception as exc:
        print(f"Не удалось собрать реестр: {exc}", file=sys.stderr)
        return 2

    guide = build_guide(registry)

    if args.json:
        import json

        print(json.dumps(guide, ensure_ascii=False, indent=2))
        return 0

    if not sys.stdout.isatty() and args.target is None:
        # В пайп не пишем заголовки разделов: только полезная часть.
        pass

    print_guide(guide, args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
