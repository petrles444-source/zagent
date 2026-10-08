r"""Три точечные правки в `handle`: отступы, имя, дубль.

Зачем
-----
Файл восстановлен из резервной копии после того, как
`tools/rebuild_handle.py` потерял хвост функции — вместе с вызовом
модели. Полная пересборка тут не годится: она режет функцию по
маркеру, и маркер однажды не нашёлся, а остаток молча исчез.

Поэтому здесь три правки по отдельности, каждая с проверкой, что
кусок найден ровно один раз. Ничего не пересобирается целиком.

Что правится
------------
1. `state["history"].append(...)` уехал внутрь `if command in
   COMMANDS:` из-за предыдущего скрипта и стал недостижимым.
2. Комментарий блока первичной логики потерял отступ.
3. Первичная логика стоит до обработки имени, из-за чего «Ада, как
   дела?» уходило в приветствие вместе с именем.

Запуск:
    .venv\\Scripts\\python.exe tools\\fix_handle_small.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent / "hosting" / "pythonanywhere" \
    / "bots" / "ada_bot.py"


def patch(old: str, new: str, label: str) -> bool:
    body = BOT.read_text(encoding="utf-8")
    count = body.count(old)
    if count != 1:
        print(f"  НЕ НАЙДЕНО ({count} раз): {label}")
        return False
    BOT.write_text(body.replace(old, new, 1), encoding="utf-8")
    print(f"  сделано: {label}")
    return True


def main() -> int:
    print("=== точечные правки в handle ===")
    ok = True

    # 1. Строка истории вернулась из-под `return` наружу.
    ok &= patch(
        "        return\n\n"
        "        state[\"history\"].append((sender, text[:500]))\n",
        "        return\n\n"
        "    state[\"history\"].append((sender, text[:500]))\n",
        "история пишется снова")

    # 2. Отступ у комментария блока.
    ok &= patch(
        "\n# Первичная логика: бот отвечает сам, не звая модель.\n",
        "\n    # Первичная логика: бот отвечает сам, не звая модель.\n",
        "отступ комментария")

    # 3. Порядок: сначала имя, потом первичная логика.
    #
    #    Блок первичной логики вырезается и ставится после обработки
    #    имени. Заодно текст для логики берётся уже очищенным от
    #    имени: иначе «Ада, как дела?» целиком уходит в приветствие.
    ok &= patch(
        "        state[\"history\"][-1] = (sender, stripped[:500])\n",
        "        state[\"history\"][-1] = (sender, stripped[:500])\n"
        "        # Дальше работаем с текстом без имени: иначе «Ада, как\n"
        "        # дела?» ушло бы в приветствие вместе с обращением.\n"
        "        text = stripped\n",
        "текст чистится от имени")

    body = BOT.read_text(encoding="utf-8")

    marker = "    # Первичная логика: бот отвечает сам, не звая модель.\n"
    start = body.find(marker)
    if start == -1:
        print("  НЕ НАЙДЕН блок первичной логики")
        return 1

    # Граница блока — первая строка, где блок заканчивается: проверка
    # частоты ответа в беседе.
    end = body.find("    if not is_private and not state[\"addressed\"]", start)
    if end == -1:
        print("  НЕ НАЙДЕН конец блока")
        return 1

    block = body[start:end]
    body = body[:start] + body[end:]

    # Точка вставки — сразу после `text = stripped`.
    anchor = "        text = stripped\n"
    if anchor not in body:
        print("  НЕ НАЙДЕНА точка вставки")
        return 1
    body = body.replace(anchor, anchor + "\n" + block, 1)

    BOT.write_text(body, encoding="utf-8")
    print("  сделано: первичная логика перенесена после обработки имени")

    ast.parse(body)
    print("ada_bot.py разбирается")
    print()
    print("всё собрано" if ok else "ЧТО-ТО НЕ СОБРАЛОСЬ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())