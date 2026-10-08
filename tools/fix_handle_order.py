r"""Убрать дубль блока и починить порядок в `handle`.

Зачем
-----
Два дефекта, найденные при обновлении тестов.

1. **Дубль.** Блок первичной логики и `/характер` вставлен дважды
   подряд (строки 496–517 и 519–540). Причина в проверке «уже сделано»
   в `tools/wire_chars.py`: она сравнивала новый кусок с файлом как
   есть, а вставленный текст в файле лежит с другим отступом, чем в
   скрипте, — и сравнение не сходилось. Второй запуск вставил копию.
   Работать это не мешало, но любая правка этого места удваивалась бы
   дальше.

2. **Порядок.** Первичная логика стояла **до** обработки имени. Из-за
   этого «Ада, как дела?» уходило в приветствие целиком, вместе с
   именем, и вопрос терялся. Имя должно вырезаться первым, а уже
   потом определяется, ответит бот сам или позовёт модель.

Запуск:
    .venv\\Scripts\\python.exe tools\\fix_handle_order.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent / "hosting" / "pythonanywhere" \
    / "bots" / "ada_bot.py"


def main() -> int:
    lines = BOT.read_text(encoding="utf-8").splitlines(keepends=True)

    # 1. Убрать второй экземпляр блока. Опознаётся по комментарию,
    #    который встречается дважды подряд с небольшим промежутком.
    marker = "# Первичная логика: бот отвечает сам, не звая модель."
    hits = [i for i, line in enumerate(lines) if marker in line]

    removed = 0
    if len(hits) > 1:
        # Второй экземпляр идёт до строки с записью в историю —
        # это граница блока.
        start = hits[1]
        end = start
        while end < len(lines) and "state[\"history\"].append" not in lines[end]:
            end += 1
        while end > start and not lines[end - 1].strip():
            end -= 1
        removed = end - start
        del lines[start:end]
        print(f"  убран дубль блока: {removed} строк")
    else:
        print("  дубля нет")

    body = "".join(lines)

    # 2. Перенести первичную логику ПОСЛЕ обработки имени.
    #
    #    Вырезается весь блок от комментария до строки с записью в
    #    историю и вставляется после `state["history"][-1] = ...`.
    start = body.find(marker)
    if start == -1:
        print("  НЕ НАЙДЕН блок первичной логики")
        return 1
    end = body.find('    state["history"].append', start)
    if end == -1 or end < start:
        print("  НЕ НАЙДЕН конец блока")
        return 1

    block = body[start:end]
    body = body[:start] + body[end:]

    # Точка вставки — сразу после обработки имени.
    anchor = '        state["history"][-1] = (sender, stripped[:500])\n'
    if anchor not in body:
        print("  НЕ НАЙДЕНА точка вставки")
        return 1
    body = body.replace(anchor, anchor + "\n" + block, 1)

    BOT.write_text(body, encoding="utf-8")
    ast.parse(body)
    print("  блок перенесён после обработки имени")
    print("ada_bot.py разбирается")
    return 0


if __name__ == "__main__":
    sys.exit(main())