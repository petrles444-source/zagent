r"""Почта через временный адрес: проверить ключ, прочитать, отправить.

Зачем
----
Адрес и ключ даны пользователем, и он же просит ими пользоваться:
принимать письма (например, коды подтверждения при регистрации где
либо) и отправлять письма наружу. Скрипт делает ровно три вещи —
показывает состояние ящика, читает входящие, отправляет одно письмо.

Ключ не в коде
--------------
`MAIL_JWT` читается из переменной окружения. В репозитории его нет, и
поэтому `tools/check_secrets.py` такие строки ловит. Пример значения
лежит в `mail.example.json` — там написано `ВСТАВЬТЕ_КЛЮЧ_СЮДА`,
поэтому проверка не считает это настоящим ключом.

Запуск
------
    set MAIL_JWT=...
    .venv\Scripts\python.exe tools\mail.py whoami
    .venv\Scripts\python.exe tools\mail.py list
    .venv\Scripts\python.exe tools\mail.py read 12
    .venv\Scripts\python.exe tools\mail.py send petrles444@gmail.com "Тема" "Текст"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

#: Адрес сервиса. Не секрет: он в настройках почты и в ссылке входа.
BASE = "https://temp-email-api.awsl.uk"

#: Куда ходить за данными. Пути из документации к сервису.
SETTINGS = "/api/settings"
LIST = "/api/parsed_mails?limit={limit}&offset={offset}"
ONE = "/api/parsed_mail/{id}"
SEND_ACCESS = "/api/request_send_mail_access"
SEND = "/api/send_mail"


def jwt() -> str:
    """Ключ доступа из окружения. Пусто — сразу понятно, что делать."""
    value = (os.environ.get("MAIL_JWT") or "").strip()
    if not value:
        raise SystemExit(
            "Нет ключа почты. Задай переменную окружения MAIL_JWT —\n"
            "    set MAIL_JWT=...\n"
            "Ключ выдаётся при создании ящика и в коде проекта быть не должен.")
    return value


def call(path: str, method: str = "GET", payload: dict | None = None,
         timeout: float = 60.0) -> dict:
    """Один запрос к сервису. Ошибки не глотаются."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    headers = {
        "Authorization": f"Bearer {jwt()}",
        # Заголовок обязателен, а не для красоты: сервер стоит за
        # Cloudflare, и запрос без него отбивается с кодом 1010 —
        # «доступ заблокирован по сигнатуре браузера». Название здесь
        # не притворяется чужим: действительно говорю, что это почта.
        "User-Agent": "zagent-mail/1.0 (temp mailbox check)",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        # Код и текст нужны по делу: 401 означает истёкший ключ, а 429 —
        # слишком частые запросы. Оба требуют разных действий.
        raise SystemExit(f"сервер ответил HTTP {exc.code}: {body}") from None
    try:
        return json.loads(raw)
    except ValueError:
        raise SystemExit(f"сервер ответил неразборчиво: {raw[:200]}") from None


def whoami() -> int:
    data = call(SETTINGS)
    address = data.get("address", "?")
    balance = data.get("send_balance", 0)
    print(f"адрес:   {address}")
    print(f"осталось отправок: {balance}")
    if not balance:
        print("\nОтправка невозможна: баланс пуст. Проверь настройку "
              "способа отправки у того, кто раздаёт адреса.")
    return 0


def listing(limit: int, offset: int) -> int:
    data = call(LIST.format(limit=limit, offset=offset))
    items = data.get("results") or []
    print(f"всего: {data.get('count', len(items))}, показано: {len(items)}")
    for item in items:
        print(f"\n  [{item.get('id')}] {item.get('created_at', '')}")
        print(f"  от:  {item.get('sender', '?')}")
        print(f"  тема: {item.get('subject', '')}")
        snippet = " ".join(str(item.get("text") or "").split())[:120]
        if snippet:
            print(f"  текст: {snippet}")
    if not items:
        print("\nПисем нет.")
    return 0


def read_one(mail_id: int) -> int:
    item = call(ONE.format(id=mail_id))
    print(f"от:   {item.get('sender', '?')}")
    print(f"тема: {item.get('subject', '')}")
    print(f"когда: {item.get('created_at', '')}\n")
    print(item.get("text") or "(текста нет, есть только разметка)")
    for attachment in item.get("attachments") or []:
        print(f"\nвложение: {attachment.get('filename')} "
              f"({attachment.get('size')} байт, содержимое не отдаётся)")
    return 0


def send(to_mail: str, subject: str, content: str, from_name: str) -> int:
    # Доступ на отправку запрашивается явно: без этого шага сервер
    # отвечает 403, и по коду ошибки не видно, чего именно не хватает.
    access = call(SEND_ACCESS, method="POST", payload={})
    print(f"доступ на отправку: {access.get('status')}")
    payload = {
        "from_name": from_name,
        "to_mail": to_mail,
        "to_name": "",
        "subject": subject,
        "content": content,
        "is_html": False,
    }
    result = call(SEND, method="POST", payload=payload)
    print(f"отправлено: {result.get('status')}")
    after = call(SETTINGS)
    print(f"осталось отправок: {after.get('send_balance')}")
    return 0


def watch(limit: int, interval: float, rounds: int) -> int:
    """Ждать новых писем. Опрашивать чаще раза в секунду нельзя."""
    seen: set[int] = set()
    for _ in range(rounds):
        data = call(LIST.format(limit=limit, offset=0))
        items = data.get("results") or []
        fresh = [i for i in items if i.get("id") not in seen]
        for item in fresh:
            seen.add(item.get("id"))
            print(f"\nновое [{item.get('id')}] от {item.get('sender', '?')}")
            print(f"  {item.get('subject', '')}")
        if fresh:
            print()
        time.sleep(max(interval, 1.0))
    print(f"новых писем: {len(seen)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="почта через временный адрес")
    parser.add_argument("--address", action="store_true", help="адрес и баланс")
    group = parser.add_subparsers(dest="command")
    listing_parser = group.add_parser("list", help="входящие")
    listing_parser.add_argument("--limit", type=int, default=10)
    listing_parser.add_argument("--offset", type=int, default=0)
    read_parser = group.add_parser("read", help="одно письмо целиком")
    read_parser.add_argument("id", type=int)
    send_parser = group.add_parser("send", help="отправить письмо")
    send_parser.add_argument("to_mail")
    send_parser.add_argument("subject")
    send_parser.add_argument("content")
    send_parser.add_argument("--from-name", default="zagent")
    watch_parser = group.add_parser("watch", help="ждать новых писем")
    watch_parser.add_argument("--interval", type=float, default=3.0)
    watch_parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()

    if args.address or not args.command:
        return whoami()
    if args.command == "list":
        return listing(args.limit, args.offset)
    if args.command == "read":
        return read_one(args.id)
    if args.command == "send":
        return send(args.to_mail, args.subject, args.content, args.from_name)
    if args.command == "watch":
        return watch(10, args.interval, args.rounds)
    return 2


if __name__ == "__main__":
    sys.exit(main())