r"""Собирать подсказку для модели под каждого собеседника.

Зачем
-----
Подсказка для модели собиралась один раз, при запуске бота:

    "persona": build_persona_text(face, data)

Но настройки характера живут по `chat_id`: человек в группе может
переключить «веселее» для себя, и это не должно менять характер
для всех остальных. Значит подсказка обязана собираться заново на
каждое сообщение — иначе модель получит настройки того, кто спросил
первым, и будет отвечать не тем характером, который только что
настроили.

Цена пересборки нулевая: это пара строк и чтение маленького файла.

Запуск:
    .venv\\Scripts\\python.exe tools\\fix_prompt_per_chat.py
"""

from __future__ import annotations

import ast
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent / "hosting" / "pythonanywhere" \
    / "bots" / "ada_bot.py"


def main() -> int:
    body = BOT.read_text(encoding="utf-8")
    changed = []

    # 1. При старте собираем подсказку с нулевым собеседником: она
    #    нужна для проверок, но для реальных ответов не годится —
    #    настройки могут быть другими.
    old_load = '            "persona": build_persona_text(face, data),'
    new_load = ('            "persona": build_persona_text(face, data, 0),\n'
                '            # Подсказка пересобирается на каждое сообщение:\n'
                '            # характер настраивается лично, по чату.\n'
                '            "char_key": str(data.get("persona_key")\n'
                '                              or face.get("key")\n'
                '                              or "ada"),')
    if old_load in body:
        body = body.replace(old_load, new_load, 1)
        changed.append("char_key в настройках")

    # 2. Перед обращением к модели собираем подсказку заново.
    old_ask = ('        answer = ask_model(providers[config["active"]], '
               'prompt, config["persona"])')
    new_ask = ('        # Подсказка — под этого собеседника: его настройки\n'
               '        # характера, а не чужие.\n'
               '        system = chars_mod.prompt(config.get("char_key")\n'
               '                                      or "ada", chat_id)\n'
               '        answer = ask_model(providers[config["active"]], '
               'prompt, system)')
    if old_ask in body:
        body = body.replace(old_ask, new_ask, 1)
        changed.append("пересборка подсказки в handle")

    if not changed:
        print("уже сделано:", "ничего не менял")
        return 0

    BOT.write_text(body, encoding="utf-8")
    ast.parse(body)
    for item in changed:
        print("  сделано:", item)
    print("ada_bot.py разбирается")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())