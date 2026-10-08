"""Ада: когда она отвечает, когда молчит и что она помнит.

Проверяется поведение, а не сеть: `send` подменяется, модель не зовётся
настоящая. Иначе тест зависел бы от ключей и от того, ответит ли
провайдер, а проверять тут нужно решение — когда бот вмешивается в
разговор.

Особое внимание к правилу «каждое десятое» и к вызову по имени: это
ровно то, что человек заметит первым, если оно сломается.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOTS = ROOT / "hosting" / "pythonanywhere" / "bots"

_spec = importlib.util.spec_from_file_location(
    "ada_bot", BOTS / "ada_bot.py")
assert _spec and _spec.loader
ada = importlib.util.module_from_spec(_spec)
sys.modules["ada_bot"] = ada
# `ada_bot` импортирует `persona` по имени, а не относительным
# путём: папка ботов кладётся на сервер как есть, без пакета.
sys.path.insert(0, str(BOTS))
import persona  # noqa: E402
_spec.loader.exec_module(ada)


@pytest.fixture(autouse=True)
def clean() -> Any:
    """Чистое состояние на каждый тест.

    Счётчик реплик и буфер живут в модуле: без сброса тесты влияли бы
    друг на друга, и результат зависел бы от порядка запуска.
    """
    ada.CHATS.clear()
    ada.OWN_ID["id"] = None
    sent: list[tuple[int, str]] = []
    ada.send = lambda token, chat, text: sent.append((chat, text))
    ada.ask_model = lambda provider, prompt, system="": f"ОТВЕТ: {prompt[-40:]}"
    return sent


def message(chat_id: int, text: str, *, private: bool = False,
            bot: bool = False, name: str = "Иван") -> dict[str, Any]:
    """Собрать входящее сообщение телеграма."""
    return {
        "message_id": 1,
        "chat": {"id": chat_id, "type": "private" if private else "group"},
        "from": {"id": 7, "is_bot": bot, "first_name": name},
        "text": text,
    }


CONFIG = {"token": "t", "providers": [{"name": "p", "base_url": "u",
                                       "model": "m", "api_key": "k"}],
          "active": 0, "persona": "persona", "heartbeat_chat_id": "",
          # Лицо — часть настроек с тех пор, как у бота появились имена
          # и аватары. Без него бот не знает, чьё имя показывать в
          # статусе, и падает с KeyError прямо при первом обращении.
          "face": persona.PERSONAS[0],
          # Уровни речи — тоже часть настроек: показываются в статусе,
          # и без них строка про детализацию просто не появляется.
          "detail_level": f"{persona.DETAIL_LEVEL} из 10",
          "science_level": f"{persona.SCIENCE_LEVEL} из 10"}


# =============================================================== вызов по имени


@pytest.mark.parametrize("name", ["Ада", "ада", "ADA", "Ada", "ada"])
def test_откликается_на_имя(clean: list, name: str) -> None:
    """Любой вариант написания имени вызывает бота.

    Голое имя — это зовущий, и на него отвечаем приглашением задать
    вопрос. Имени без текста разбирать нечего.
    """
    ada.handle(CONFIG, message(1, name))
    assert clean, f"«{name}» не вызвало бота"
    assert "Что хотели узнать" in clean[0][1]


@pytest.mark.parametrize("name", ["Ада, сколько нужно принести",
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
    leftover = ada.NAME_TRIGGERS.sub("", name).strip(" ,.:!?\u2014-")
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
            f"имя «{word}» осталось в ответе: {answer!r}")


@pytest.mark.parametrize("word", ["адаптер", "палата", "адамантис", "папочка",
                                  "compада", "адаптация"])
def test_не_откликается_на_совпадения_в_словах(clean: list, word: str) -> None:
    """Имя ищется по границам слова: «адаптер» — это не «Ада».

    Бот отвечает на каждое сообщение, поэтому проверяется не молчание,
    а то, что слово **не сочли обращением по имени**.
    """
    ada.handle(CONFIG, message(1, word))
    assert not ada.CHATS[1].get("addressed"), f"«{word}» сочли за имя"
    clean.clear()


def test_после_имени_отвечает_на_следующую_реплику(clean: list) -> None:
    """Позвали по имени без вопроса — следующая фраза уже адресована Аде."""
    ada.handle(CONFIG, message(1, "Ада"))
    clean.clear()
    ada.handle(CONFIG, message(1, "а теперь ответь подробнее"))
    assert clean, "после обращения по имени бот должен ответить"


# =============================================================== каждое сообщение


def test_в_беседе_отвечает_на_каждое_сообщение(clean: list) -> None:
    """В беседе бот отвечает на всё, а не на каждое десятое.

    Раньше стояло `EVERY_N = 10` — из опасения засорять группу. На
    практике человек писал и не получал ответа, то есть читал это как
    «бот сломан». По прямой просьбе стало `EVERY_N = 1`.
    """
    answered = []
    for number in range(1, 11):
        ada.handle(CONFIG, message(2, f"реплика {number}"))
        answered.append(bool(clean))
        clean.clear()
    silent = [i + 1 for i, ok in enumerate(answered) if not ok]
    assert not silent, f"бот молчал на репликах: {silent}"


def test_границы_слова_у_имени_не_срабатывают(clean: list) -> None:
    """«Адаптер» не считается обращением по имени.

    Отдельно от молчания: бот отвечает на всё, поэтому проверить надо
    именно то, что слово **не сочли именем**. Иначе в группе «адаптер»
    вызывал бы бота так же, как настоящее имя.
    """
    for word in ("адаптер", "палата", "толяк", "кетоны", "катька"):
        ada.handle(CONFIG, message(23, word))
        assert not ada.CHATS[23].get("addressed"), f"«{word}» сочли за имя"
        clean.clear()


def test_в_личном_чате_отвечает_на_всё(clean: list) -> None:
    """Один на один — молчать невежливо."""
    for number in range(1, 4):
        ada.handle(CONFIG, message(4, f"вопрос {number}", private=True))
        assert len(clean) == number, "в личном чате ждём ответа на каждый"


# =============================================================== фильтры


def test_игнорирует_сообщения_ботов(clean: list) -> None:
    """Чужие боты: иначе Ада отвечает им и зацикливается."""
    ada.handle(CONFIG, message(5, "Ада", bot=True))
    assert clean == []


def test_игнорирует_пустые_сообщения(clean: list) -> None:
    """Картинки и голосовые без текста не в счёт."""
    ada.handle(CONFIG, message(6, ""))
    assert clean == []
    ada.handle(CONFIG, {"chat": {"id": 6, "type": "group"}, "text": "   "})
    assert clean == []


def test_не_отвечает_на_команду_как_на_вопрос(clean: list) -> None:
    """Команды обрабатываются отдельно, а не как обычная реплика."""
    ada.handle(CONFIG, message(7, "/status"))
    assert len(clean) == 1
    # Имя берётся из настроек, а не пишется в тексте: бот может
    # называться Effy или Mia, и подпись обязана совпадать.
    assert CONFIG["face"]["name"] in clean[0][1]
    assert "на связи" in clean[0][1]


# =============================================================== контекст


def test_в_модель_уходит_контекст_чата(clean: list) -> None:
    """Модель получает последние реплики, а не одну фразу."""
    captured: list[str] = []

    def capture(provider: dict[str, Any], prompt: str,
                system: str = "") -> str:
        captured.append(prompt)
        return "ок"

    ada.ask_model = capture
    for number in range(1, 11):
        ada.handle(CONFIG, message(8, f"реплика {number}", private=True))
    assert captured, "модель не позвали"
    assert "реплика 10" in captured[-1]
    assert "реплика 1" in captured[-1], "контекст обрезан слишком сильно"


def test_контекст_не_растёт_бесконечно(clean: list) -> None:
    """Буфер ограничен: иначе запрос к модели дорожает с каждым часом."""
    ada.ask_model = lambda provider, prompt, system="": "ок"
    for number in range(1, 41):
        ada.handle(CONFIG, message(9, f"реплика {number}", private=True))
    state = ada.CHATS[9]
    assert len(state["history"]) <= ada.CONTEXT_MESSAGES
    assert "реплика 1" not in state["history"][-1][1]


# =============================================================== пульс


def test_пульс_идёт_раз_в_сто_секунд(clean: list) -> None:
    """Ровно раз в 100 секунд, и не чаще.

    Сначала человек пишет в личный чат — только тогда Ада знает, кому
    писать. Дальше два пульса подряд: второй должен быть отложен, а не
    отправлен сразу.
    """
    assert ada.HEARTBEAT_S == 100
    config = dict(CONFIG, heartbeat_chat_id="10")
    ada.handle(config, message(10, "привет", private=True))
    clean.clear()
    ada.heartbeat(config)
    assert len(clean) == 1, "первый пульс должен уйти"
    assert "работаю" in clean[0][1]
    ada.heartbeat(config)
    assert len(clean) == 1, "второй пульс сразу после первого лишний"
    # Время переводим руками: ждать сто секунд ради теста незачем.
    ada.CHATS[10]["beat"] -= ada.HEARTBEAT_S + 1
    ada.heartbeat(config)
    assert len(clean) == 2, "через 100 секунд пульс должен повториться"


def test_пульс_без_чата_молчит(clean: list) -> None:
    """Пока бот никому не отвечал, пульсировать некому."""
    ada.heartbeat(dict(CONFIG, heartbeat_chat_id="999"))
    assert clean == []


# =============================================================== статусы


def test_статус_объясняет_правила(clean: list) -> None:
    """В статусе видно, как со мной говорить."""
    text = ada.status_text(CONFIG)
    assert CONFIG["face"]["name"] in text
    assert "на связи" in text
    assert f"каждое {ada.EVERY_N}-е" in text, (
        "в статусе нет правила про беседу — человек не поймёт, "
        "когда бот ответит")
    assert "/forget" in text, "в статусе нет сброса контекста"
    assert f"{persona.DETAIL_LEVEL} из 10" in text, (
        "в статусе не сказано, насколько подробно бот отвечает")
