#!/usr/bin/env python3
"""Управление telegram-ботами из консоли.

    .venv\\Scripts\\python.exe tools\\tgbot.py list
    .venv\\Scripts\\python.exe tools\\tgbot.py build my_helper --model qwen2.5:3b
    .venv\\Scripts\\python.exe tools\\tgbot.py status my_helper
    .venv\\Scripts\\python.exe tools\\tgbot.py plan my_helper

Ключи моделей не читаются и не печатаются: команда `keys` показывает,
какие шлюзы вообще настроены, но не их значения.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import telegram  # noqa: E402
from hub.config import load_gateways  # noqa: E402


def cmd_list(args: argparse.Namespace) -> int:
    bots = telegram.list_bots(root=args.root)
    if not bots:
        print("Ботов пока нет. Собрать:  tgbot.py build <имя>")
        return 0
    print(f"Собрано ботов: {len(bots)}")
    for bot in bots:
        mark = "токен есть" if bot["token_set"] else "НЕТ токена"
        print(f"  {bot['name']:24} модель {bot['model'] or '-':16} {mark}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    try:
        info = telegram.build_bot(args.name, title=args.title or "",
                                  model=args.model, system=args.system or "",
                                  root=args.root, force=args.force)
    except telegram.TelegramError as exc:
        print(f"Ошибка: {exc}")
        return 1
    print(f"Бот собран: {info['dir']}")
    print(f"Файлы: {', '.join(info['files'])}")
    print(f"Модель по умолчанию: {info['model']}"
          + (" (ключ есть)" if info["gateway_has_key"] else ""))
    print("\nОсталось за человеком - этого API у Telegram просто нет:")
    for step in info["human_steps"]:
        print(f"  - {step}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        info = telegram.status(args.name, root=args.root)
    except telegram.TelegramError as exc:
        print(f"Ошибка: {exc}")
        return 1
    if not info.get("ok"):
        print(info.get("error") or "бот не собран")
        return 1
    print(f"Бот {info['name']}: собран, модель {info.get('model') or '-'}")
    if info.get("telegram_ok"):
        print(f"  Telegram отвечает, имя: @{info.get('username')}")
    else:
        print(f"  Telegram: {info.get('error')}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        name = telegram.check_name(args.name)
        telegram.check_model(args.model)
    except telegram.TelegramError as exc:
        print(f"Ошибка: {exc}")
        return 1
    plan = {
        "bot": name,
        "model": args.model,
        "agент_сам": [
            f"собрать код бота в projects/telegram-bots/{name}/",
            "проверить, что секретов в файлах нет (фабрика делает это сама)",
            "написать инструкцию запуска",
        ],
        "вместе_с_человеком": [
            "человек создаёт бота у @BotFather и вписывает токен",
        ],
        "не_умеет": [
            "создать бота без человека - такого API у Telegram нет",
            "писать в чаты по своей воле: chat_id бот получает от человека",
        ],
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def cmd_keys(args: argparse.Namespace) -> int:
    """Какие шлюзы настроены. Значения ключей не показываются."""
    rows = []
    for gateway in load_gateways(args.root):
        gid = str(gateway.get("id") or gateway.get("name") or "")
        if not gid:
            continue
        rows.append((gid, telegram.has_key(gid, root=args.root),
                     bool(gateway.get("keyless"))))
    if not rows:
        print("Шлюзы не настроены.")
        return 0
    for gid, has, keyless in rows:
        if keyless:
            mark = "без ключа"
        else:
            mark = "ключ есть" if has else "КЛЮЧА НЕТ"
        print(f"  {gid:16} {mark}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Фабрика telegram-ботов")
    parser.add_argument("--root", default=None, help="корень проекта")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="что уже собрано").set_defaults(func=cmd_list)

    build = sub.add_parser("build", help="собрать бота")
    build.add_argument("name")
    build.add_argument("--model", default="qwen2.5:3b")
    build.add_argument("--title", default="")
    build.add_argument("--system", default="")
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=cmd_build)

    stat = sub.add_parser("status", help="состояние бота")
    stat.add_argument("name")
    stat.set_defaults(func=cmd_status)

    plan = sub.add_parser("plan", help="план: что агент, что человек")
    plan.add_argument("name")
    plan.add_argument("--model", default="qwen2.5:3b")
    plan.set_defaults(func=cmd_plan)

    sub.add_parser("keys", help="какие шлюзы настроены").set_defaults(
        func=cmd_keys)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
