r"""Переписать тест про правило иностранных слов.

Зачем
-----
Тест назывался «правило про слова — одно на всех» и требовал, чтобы
и Ада, и Линда получали в подсказку один и тот же `style_note` с
разбором иностранных слов.

Однаковость здесь была ошибкой, а не требованием. Правило разбора
слов нужно Линде и Кети — они объясняют и переводят. Болтливой Аде
оно мешает: она флиртует и болтает, а не разбирает термины, и
заставлять её каждый ответ заканчивать словарём значит испортить
характер.

Поэтому проверка переворачивается: правило обязано быть у Кети и
Линды и обязано **отсутствовать** у Ады.

Запуск:
    .venv\\Scripts\\python.exe tools\\split_glossary_test.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent / "tests" / "test_linda_bot.py"

OLD_HEAD = 'def test_подсказка_про_слова_одна_и_та_же() -> None:'


def main() -> int:
    text = TESTS.read_text(encoding="utf-8")
    start = text.find(OLD_HEAD)
    if start == -1:
        print("  тест не найден")
        return 1
    end = text.find("\n\n\ndef ", start + 10)
    if end == -1:
        print("  не нашёл конец теста")
        return 1

    NEW = '''def test_словарь_есть_у_учительниц_и_нет_у_ады() -> None:
    """Правило разбора иностранных слов — не у всех.

    Раньше тест требовал, чтобы правило было «одно на всех», и проверял
    Аду с Линдой. Но разбор слов нужен тем, кто объясняет: Линде и
    Кети. У болтливой Ады он испортил бы характер — она флиртует и
    разговаривает, а не ведёт словарь.

    Проверяется поэтому в обе стороны: у Кети и Линды правило есть, у
    Ады — нет. Отсутствие проверяется отдельно, потому что «строка не
    найдена» для `assert` выглядит как успех наоборот.
    """
    from ada_bot import build_persona_text

    ada_text = build_persona_text(persona.PERSONAS[0],
                                 {"persona_key": "ada"}, 0)
    linda_text = linda.build_persona(persona.PERSONAS[1])
    note = persona.style_note()

    assert note in linda_text, "у Линды должно быть правило про слова"
    assert note not in ada_text, (
        "у Ады правило разбора слов быть не должно — оно ломает "
        "её характер")

    # У Кети правило обязано быть: она переводит и объясняет слова.
    import chars
    katy_text = chars.prompt("katy", 0)
    assert "кавычки" in katy_text, "у Кети должно быть правило про слова"
'''

    text = text[:start] + NEW + text[end:]
    TESTS.write_text(text, encoding="utf-8")
    ast.parse(text)
    print("  тест переписан: правило есть у Линды и Кети, нет у Ады")
    print("test_linda_bot.py разбирается")
    return 0


if __name__ == "__main__":
    sys.exit(main())