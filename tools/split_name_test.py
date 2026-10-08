r"""Переписать тест про имя: разделить вопрос и приветствие.

Зачем
-----
Тест `test_имя_с_вопросом_сразу_получает_ответ` требовал, чтобы любое
сообщение с именем уходило в модель. С появлением первичной логики это
перестало быть так: короткое «Ада, привет» бот закрывает сам, без
модели, — это дешевле, быстрее и не зависит от ключа.

Проверка падала не из-за ошибки в боте, а из-за устаревшего ожидания.
Поэтому она переписывается на две части:

* вопрос по имени — уходит в модель (старое поведение, оно и нужно);
* короткое приветствие по имени — отвечает сам бот (новое поведение).

Запуск:
    .venv\\Scripts\\python.exe tools\\split_name_test.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent / "tests" / "test_ada_bot.py"

START = '@pytest.mark.parametrize("name", ["АДА привет", "привет, ada!",'
MARK = "leftover in captured[0], ("


def main() -> int:
    text = TESTS.read_text(encoding="utf-8")
    start = text.find(START)
    if start == -1:
        print("  начало теста не найдено")
        return 1

    # Конец — строка с остатком вопроса, после неё идёт следующий тест.
    mark = text.find(MARK, start)
    if mark == -1:
        print("  конец теста не найден")
        return 1
    end = text.find("\n\n\n", mark)
    if end == -1:
        print("  не нашёл границу следующего теста")
        return 1

    NEW = '''@pytest.mark.parametrize("name", ["Ада, сколько нужно принести",
                                  "ада объясни, что такое Ruffle",
                                  "Ана, помоги разобраться с циклом",
                                  "АДА, почему не запускается сервер"])
def test_имя_с_вопросом_сразу_получает_ответ(clean: list, name: str) -> None:
    """Имя вместе с вопросом — это уже вопрос, а не зовущий.

    Раньше здесь отправлялось «Что хотели узнать?» на любое сообщение
    с именем, и человек, задавший вопрос, получал отказ отвечать на
    свой же вопрос. Теперь имя убирается, а остаток уходит модели.

    Приветствий среди параметров нет намеренно: «Ада, привет» — это
    короткое приветствие, и на него бот отвечает сам, без модели.
    Отдельный тест ниже проверяет именно это.
    """
    captured: list[str] = []

    def capture(provider: dict[str, Any], prompt: str, system: str = "") -> str:
        captured.append(prompt)
        return "ответ по существу"

    ada.ask_model = capture
    ada.handle(CONFIG, message(100 + len(captured), name))
    assert captured, f"«{name}» не дошло до модели"
    assert "Что хотели узнать" not in clean[-1][1], "отказ вместо ответа"
    assert "ответ по существу" in clean[-1][1]
    # Имя из вопроса убрано, а само содержание — осталось. Проверять
    # надо остаток после вырезания имени, а не последнее слово: в
    # «привет, ada!» последнее слово и есть имя.
    leftover = ada.NAME_TRIGGERS.sub("", name).strip(" ,.:!?\\u2014-")
    assert leftover in captured[0], (
        f"остаток вопроса «{leftover}» не дошёл до модели")


@pytest.mark.parametrize("greeting", ["Ада, привет", "привет, ада!",
                                      "Толя, здорово", "Кети, привет"])
def test_короткое_приветствие_отвечает_бот_сам(clean: list,
                                               greeting: str) -> None:
    """Приветствие по имени закрывает бот сам, модель не зовёт.

    Экономия видна сразу: приветствие — самая частая реплика, а
    отправлять её в модель значит платить и ждать там, где хватает
    одной заготовки. Имя вырезается раньше, поэтому в само приветствие
    оно попасть не должно.
    """
    captured: list[str] = []

    def capture(provider: dict[str, Any], prompt: str, system: str = "") -> str:
        captured.append(prompt)
        return "ответ по существу"

    ada.ask_model = capture
    ada.handle(CONFIG, message(200 + len(captured), greeting))

    assert not captured, f"«{greeting}» ушло в модель вместо заготовки"
    assert clean, f"на «{greeting}» не отвечено вовсе"
    answer = clean[-1][1]
    for word in ("Ада", "Толя", "Кети", "Анатолий"):
        assert word not in answer, (
            f"имя «{word}» осталось в ответе: {answer!r}")'''

    text = text[:start] + NEW + text[end:]
    TESTS.write_text(text, encoding="utf-8")
    ast.parse(text)
    print("  тест переписан на два: вопрос уходит в модель, приветствие нет")
    print("test_ada_bot.py разбирается")
    return 0


if __name__ == "__main__":
    sys.exit(main())