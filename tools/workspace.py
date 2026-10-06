#!/usr/bin/env python3
r"""Управление воркспейсами из командной строки.

    python tools\workspace.py list
    python tools\workspace.py add C:\projects\myapp --name myapp --access 2
    python tools\workspace.py use myapp
    python tools\workspace.py rm myapp
    python tools\workspace.py set myapp --autonomy strict --max-steps 60
    python tools\workspace.py path          путь активного воркспейса

Воркспейс ограничивает агента папкой: за её пределы он не выходит ни при
каком уровне доступа.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.config import project_root  # noqa: E402
from hub.workspace import WorkspaceError, WorkspaceManager  # noqa: E402


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workspace.py", description="Воркспейсы zagent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="показать все воркспейсы")
    sub.add_parser("path", help="путь активного воркспейса")

    add = sub.add_parser("add", help="добавить папку")
    add.add_argument("path")
    add.add_argument("--name", help="название (по умолчанию имя папки)")
    add.add_argument("--access", type=int, default=2, choices=[1, 2, 3],
                     help="1=чтение, 2=запись, 3=полный")
    add.add_argument("--autonomy", default="normal",
                     choices=["yolo", "normal", "strict", "plan"])
    add.add_argument("--escalation", default="auto", choices=["off", "auto", "on"])

    use = sub.add_parser("use", help="переключиться на воркспейс")
    use.add_argument("id")

    rm = sub.add_parser("rm", help="удалить воркспейс (папку не трогает)")
    rm.add_argument("id")

    change = sub.add_parser("set", help="изменить настройки")
    change.add_argument("id")
    change.add_argument("--name")
    change.add_argument("--access", type=int, choices=[1, 2, 3])
    change.add_argument("--autonomy", choices=["yolo", "normal", "strict", "plan"])
    change.add_argument("--escalation", choices=["off", "auto", "on"])
    change.add_argument("--max-steps", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    manager = WorkspaceManager(project_root())

    try:
        if args.command == "list":
            data = manager.describe()
            print(f"Активный: {data['active']}")
            print(f"Файл:     {data['config_path']}\n")
            for workspace in data["workspaces"]:
                marker = "*" if workspace["id"] == data["active"] else " "
                state = "" if workspace["exists"] else "  [ПАПКИ НЕТ]"
                access = {1: "чтение", 2: "запись", 3: "полный"}[workspace["access"]]
                print(f" {marker} {workspace['id']:<20} {access:<8} "
                      f"{workspace['autonomy']:<7} {workspace['path']}{state}")
            return 0

        if args.command == "path":
            print(manager.active.resolved())
            return 0

        if args.command == "add":
            workspace = manager.add(
                args.path, name=args.name, access=args.access,
                autonomy=args.autonomy, escalation=args.escalation,
            )
            print(f"Добавлен: {workspace.id} -> {workspace.resolved()}")
            print(f"Агент не сможет выйти за пределы этой папки.")
            return 0

        if args.command == "use":
            workspace = manager.activate(args.id)
            print(f"Активный воркспейс: {workspace.id}")
            print(f"  путь: {workspace.resolved()}")
            return 0

        if args.command == "rm":
            manager.remove(args.id)
            print(f"Удалён: {args.id} (папка на диске не тронута)")
            return 0

        if args.command == "set":
            fields = {
                "name": args.name, "access": args.access,
                "autonomy": args.autonomy, "escalation": args.escalation,
                "max_steps": args.max_steps,
            }
            fields = {k: v for k, v in fields.items() if v is not None}
            workspace = manager.update(args.id, **fields)
            print(f"Обновлён: {workspace.id}")
            print(f"  доступ: {workspace.access}, автономия: {workspace.autonomy}, "
                  f"шагов: {workspace.max_steps}")
            return 0

    except WorkspaceError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
