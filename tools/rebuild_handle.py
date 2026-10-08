r"""Привести `handle` в порядок: отступы и порядок вызовов.

Зачем
-----
`tools/fix_handle_order.py` перенёс блок первичной логики после
обработки имени и при этом:

* строку `state["history"].append(...)` оставил с отступом внутри
  `if command in COMMANDS:`, то есть сделал её недостижимой — она
  стояла после `return` и не выполнялась никогда;
* потерял отступ у комментария блока;
* оставил встроенную логику глядя на исходный `text`, а не на текст
  без имени.

Всё три видно только при чтении файла глазами, и правка обычным
инструментом не берётся из-за невидимых символов, поэтому здесь
функция пересобирается целиком — одним куском и одним отступом.

Запуск:
    .venv\\Scripts\\python.exe tools\\rebuild_handle.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent / "hosting" / "pythonanywhere" \
    / "bots" / "ada_bot.py"

#: Начало функции и первый оператор после неё. По нему обрезается
#: прежнее содержимое.
HEAD = "def handle(config: dict[str, Any], message: dict[str, Any]) -> None:"

#: Операторы, которые живут в теле и не трогаются этой правкой.
#: Всё после маркера `ЗДЕСЬ_ДАЛЬШЕ` переносится без изменений.
TAIL_MARK = "    # В беседе бот отвечает на каждое сообщение."

BODY = '''def handle(config: dict[str, Any], message: dict[str, Any]) -> None:
    """Одно входящее сообщение.

    Порядок здесь важен и проверен тестами:

    1. команды — до всего остального, иначе модель через десять
       вызовов получает переписку из `/help` и начинает отвечать на
       список команд;
    2. запись в историю;
    3. вырезание имени — чтобы дальше работать с чистым текстом;
    4. первичная логика — короткие случаи бот закрывает сам;
    5. команда настройки характера;
    6. и только потом модель.
    """
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = str(message.get("text") or "").strip()
    if chat_id is None or not text:
        return

    # Чужие боты и собственные реплики: иначе Ада отвечает сама себе.
    if (message.get("from") or {}).get("is_bot"):
        return
    sender = (message.get("from") or {}).get("first_name") or "участник"
    is_private = str(chat.get("type") or "") == "private"

    token = config["token"]
    state = chat_state(int(chat_id))
    state["count"] += 1

    # 1. Команды.
    command = text.split()[0].lower().split("@")[0]
    if command in COMMANDS:
        answer = COMMANDS[command](config, state, chat_id)
        if answer:
            send(token, chat_id, answer)
        return

    # 2. История.
    state["history"].append((sender, text[:500]))

    # 3. Обращение по имени.
    #
    #    Раньше здесь отправлялась заглушка «Что хотели узнать?» на
    #    любое сообщение с именем, и человек, задавший вопрос, получал
    #    отказ отвечать на свой же вопрос.
    if NAME_TRIGGERS.search(text):
        state["addressed"] = True
        stripped = NAME_TRIGGERS.sub("", text).strip(" ,.:!?\\u2014-")
        # Голое «Ада» без ничего — это всё ещё просто зовущий, и на
        # него отвечать нечем: вот тут заглушка и уместна. А «Ада,
        # сколько нужно принести» — это уже вопрос, и на него
        # отвечаем.
        if len(stripped) < 3:
            send(token, chat_id, ASK_WHAT)
            return
        state["history"][-1] = (sender, stripped[:500])
        # Дальше идём по очищенному тексту: иначе «Ада, как дела?»
        # попало бы в приветствие вместе с именем.
        text = stripped

    # 4. Первичная логика: бот отвечает сам, не звая модель.
    #
    #    Стоит именно здесь — после вырезания имени и до модели.
    #    Арифметику и время надо считать кодом, а не моделью: модель
    #    посчитает «17*23» с вероятностью опечатки, а выражение в
    #    Python — без. И пока ключ модели недоступен или сеть
    #    моргнула, бот остаётся полезным, а не превращается в
    #    извиняющуюся заглушку.
    key = config.get("persona_key") or "ada"
    quick = chars_mod.builtin_answer(key, text)
    if quick:
        send(token, chat_id, quick)
        return

    # 5. Настройка характера: команда человека, а не вопрос к модели.
    #    Отвечать тут должен сам бот: модель о настройках ничего не
    #    знает и ответила бы наугад.
    for cmd in chars_mod.CHAR_CMDS:
        if text.lower().startswith(cmd):
            answer, _ = chars_mod.char_command(
                key, chat_id, text[len(cmd):])
            send(token, chat_id, answer)
            return

'''


def main() -> int:
    source = BOT.read_text(encoding="utf-8")

    start = source.find(HEAD)
    if start == -1:
        print("  функция handle не найдена")
        return 1

    # Хвост: от комментария про беседу и до следующей функции уровня
    # столбца. Он не трогается — там обращение к модели.
    tail_at = source.find(TAIL_MARK, start)
    if tail_at == -1:
        # Запасной путь: режем по следующей функции верхнего уровня.
        nxt = re.search(r"\n(?=(?:def |class |[A-Z_]+ =|# ---))",
                       source[start + len(HEAD):])
        if not nxt:
            print("  не нашёл конец функции")
            return 1
        tail_at = start + len(HEAD) + nxt.start()
        tail = source[tail_at:tail_at + 1] + source[tail_at:].lstrip("\n")
    else:
        tail = source[tail_at:]

    new_source = source[:start] + BODY + tail
    BOT.write_text(new_source, encoding="utf-8")
    ast.parse(new_source)
    print("  handle пересобрана")
    print("ada_bot.py разбирается")
    return 0


if __name__ == "__main__":
    sys.exit(main())