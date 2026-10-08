r"""Включить характеры из chars.py в бота.

Зачем скрипт, а не правка
------------------------
Файл `ada_bot.py` правился много раз подряд, и в нём оказались
невидимые символы: точное совпадение текста перестаёт работать, и
обычная правка отказывается находить нужное место. Чинить это
выборочно — значит ещё несколько заходов. Поэтому подключение
делается скриптом, который проверяет, что каждый кусок на месте, и
ругается, если нет.

Что подключается
----------------
1. `import chars` — сам модуль характеров.
2. `chat_id` в `build_persona_text` — чтобы подсказка модели знала,
   что настроил именно этот собеседник.
3. Первичная логика в `handle` — бот отвечает сам, не звая модель.
4. Команда `/характер` — настройка характера прямо в чате.
5. Ключ характера в `load_config` — чтобы он дошёл до подсказки.

Запуск:
    .venv\\Scripts\\python.exe tools\\wire_chars.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent / "hosting" / "pythonanywhere" \
    / "bots" / "ada_bot.py"


def patch(old: str, new: str, label: str, once: bool = False) -> bool:
    """Заменить кусок. False — кусок не найден.

    `once=True` меняет только первое вхождение. Это нужно для
    импортов: в файле их два, потому что один блок стоит внутри
    `try`, а второй — рядом на случай, если первый не сработал.
    Импорт характеров нужен один раз, иначе второй перекроет первый
    тем же самым модулем и ничего не изменится.
    """
    body = BOT.read_text(encoding="utf-8")
    if new in body and old not in body:
        print(f"  уже сделано: {label}")
        return True
    count = body.count(old)
    if count == 0:
        print(f"  НЕ НАЙДЕНО: {label}")
        return False
    if not once and count != 1:
        print(f"  НАЙДЕНО {count} РАЗ: {label} — не трогаю")
        return False
    BOT.write_text(body.replace(old, new, 1), encoding="utf-8")
    print(f"  сделано: {label}")
    return True


def main() -> int:
    print("=== подключаю характеры ===")
    ok = True

    # 1. Импорт. Меняется только первое вхождение: в файле их два,
    #    потому что один блок стоит внутри `try`, а второй рядом.
    ok &= patch(
        "    from persona import (DETAIL_LEVEL, GLOSSARY, PERSONAS, "
        "SCIENCE_LEVEL,",
        "    import chars as chars_mod\n    from persona import (DETAIL_LEVEL, "
        "GLOSSARY, PERSONAS, SCIENCE_LEVEL,",
        "импорт chars", once=True)

    # 2. Подсказка для модели знает собеседника.
    #    Отступ здесь 21 пробел, а не 23 — в этом и причина, по
    #    которой обычная правка файла не находила это место.
    ok &= patch(
        "                     data: dict[str, Any]) -> str:",
        "                     data: dict[str, Any],\n"
        "                     chat_id: int = 0) -> str:",
        "chat_id в build_persona_text")

    # 3. Ключ характера должен попасть в настройки: без него подсказка
    #    не знает, чей характер собирать, и берёт первого попавшегося.
    ok &= patch(
        '    return {"token": token, "providers": providers, "active": active,',
        '    return {"token": token, "providers": providers, "active": active,\n'
        '            "persona_key": str(data.get("persona_key") or ""),',
        "persona_key в load_config")

    # 4. Первичная логика и команда настройки — в `handle`, до модели.
    #    Точка врезки выбрана одна: после разбора команд и до записи
    #    в историю. Раньше этих двух случаев бот звал модель даже на
    #    «привет», а «2+2» мог посчитать неправильно.
    ok &= patch(
        '    state["history"].append((sender, text[:500]))',
        '    # Первичная логика: бот отвечает сам, не звая модель.\n'
        '    #\n'
        '    #    Арифметику и время надо считать кодом, а не моделью:\n'
        '    #    модель посчитает «17*23» с вероятностью опечатки, а\n'
        '    #    выражение в Python — без. И пока ключ модели недоступен\n'
        '    #    или сеть моргнула, бот остаётся полезным, а не\n'
        '    #    превращается в извиняющуюся заглушку.\n'
        '    key = config.get("persona_key") or "ada"\n'
        '    quick = chars_mod.builtin_answer(key, text)\n'
        '    if quick:\n'
        '        send(token, chat_id, quick)\n'
        '        return\n'
        '\n'
        '    # Настройка характера: команда человека, а не вопрос к модели.\n'
        '    #    Отвечать тут должен сам бот: модель о настройках ничего\n'
        '    #    не знает и ответила бы наугад.\n'
        '    for cmd in chars_mod.CHAR_CMDS:\n'
        '        if text.lower().startswith(cmd):\n'
        '            answer, _ = chars_mod.char_command(\n'
        '                key, chat_id, text[len(cmd):])\n'
        '            send(token, chat_id, answer)\n'
        '            return\n'
        '\n'
        '    state["history"].append((sender, text[:500]))',
        "первичная логика и /характер")

    print()
    if not ok:
        print("ЧТО-ТО НЕ СОБРАЛОСЬ — смотрите строки выше", file=sys.stderr)
        return 1

    # Проверка, что файл вообще разбирается.
    import ast
    ast.parse(BOT.read_text(encoding="utf-8"))
    print("ada_bot.py разбирается, все правки на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())