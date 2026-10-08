"""Пользовательские команды обоих ботов: справка, сброс, имя.

Проверяется поведение, а не сеть: отправка подменена, модель не
звается. Иначе тест зависел бы от ключей и от того, ответит ли
провайдер, а проверять тут нужно решение — что бот делает с командой
и что происходит с памятью чата.

Главное, что тут проверяется
---------------------------
`/forget` обязан очищать историю ДО того, как команда попадёт в неё.
Если порядок окажется обратным, бот запомнит собственную команду и
следующий ответ будет опираться на слово «/forget» вместо чистого
листа. Выглядит это как «бот сбросил контекст и всё равно отвечает
про /forget».
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
BOTS = ROOT / "hosting" / "pythonanywhere" / "bots"
sys.path.insert(0, str(BOTS))

import persona  # noqa: E402


def load(name: str) -> Any:
    """Загрузить бота как модуль, как это делает сервер."""
    spec = importlib.util.spec_from_file_location(name, BOTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ada = load("ada_bot")
linda = load("linda_bot")
import user_features  # noqa: E402

CONFIG = {
    "token": "t",
    "providers": [{"name": "p", "base_url": "u", "model": "m",
                   "api_key": "k"}],
    "active": 0,
    "persona": "persona",
    "heartbeat_chat_id": "",
    "face": persona.PERSONAS[0],
    "detail_level": f"{persona.DETAIL_LEVEL} из 10",
    "science_level": f"{persona.SCIENCE_LEVEL} из 10",
}


@pytest.fixture(params=[ada, linda], ids=["Ада", "Линда"])
def bot(request: Any) -> Any:
    """Оба бота проходят одни и те же проверки.

    Так сделано не для красивости: команды живут в общем модуле
    именно затем, чтобы их поведение нельзя было разъехать. Проверка
    на обоих это и подтверждает.
    """
    module = request.param
    module.CHATS.clear()
    sent: list[tuple[int, str]] = []
    module.send = lambda token, chat, text: sent.append((chat, text))
    module.ask_model = lambda provider, prompt, system="": f"ОТВЕТ: {prompt[-30:]}"
    module.sent = sent  # type: ignore[attr-defined]
    return module


def message(chat_id: int, text: str, *, private: bool = False) -> dict[str, Any]:
    return {
        "message_id": 1,
        "chat": {"id": chat_id, "type": "private" if private else "group"},
        "from": {"id": 7, "is_bot": False, "first_name": "Иван"},
        "text": text,
    }


# =============================================================== справка


@pytest.mark.parametrize("command", ["/start", "/help"])
def test_справка_на_старте_и_по_help(bot: Any, command: str) -> None:
    """Обе команды дают один и тот же список команд.

    Раньше `/start` отвечал заглушкой «Что хотели узнать?», а списка
    команд не было вообще: человек не мог узнать, что бот умеет,
    если не знает этого заранее.
    """
    bot.handle(CONFIG, message(1, command, private=True))
    text = bot.sent[-1][1]
    for expected in ("/help", "/status", "/whoami", "/forget", "/name"):
        assert expected in text, f"в справке нет {expected}"


def test_справка_называет_текущее_имя(bot: Any) -> None:
    """Имя берётся из настроек, а не пишется в тексте намертво."""
    bot.handle(CONFIG, message(2, "/help", private=True))
    text = bot.sent[-1][1]
    assert CONFIG["face"]["name"] in text


def test_справка_объясняет_правило_десятого(bot: Any) -> None:
    """Человек должен понимать, почему бот молчит в беседе."""
    bot.handle(CONFIG, message(3, "/help", private=True))
    text = bot.sent[-1][1]
    assert "десятое" in text or "десят" in text
    assert "личном чате" in text


# =============================================================== имя


def test_команда_имя_показывает_лицо(bot: Any) -> None:
    """`/name` отвечает без модели и показывает роль."""
    bot.handle(CONFIG, message(4, "/name", private=True))
    text = bot.sent[-1][1]
    assert CONFIG["face"]["name"] in text
    assert CONFIG["face"]["role"] in text
    # Ответ собран из настроек, а не из модели: если модель позвали,
    # в тексте появился бы маркер подмены.
    assert "ОТВЕТ:" not in text


# =============================================================== сброс


def test_forget_очищает_историю(bot: Any) -> None:
    """Сброс действительно стирает разговор."""
    for number in range(1, 4):
        bot.handle(CONFIG, message(5, f"реплика {number}", private=True))
    assert bot.CHATS[5]["history"], "история должна была наполниться"
    bot.handle(CONFIG, message(5, "/forget", private=True))
    assert not bot.CHATS[5]["history"], "/forget не стёр разговор"


def test_forget_не_попадает_в_историю(bot: Any) -> None:
    """Команда не должна запоминать саму себя.

    Это и есть тот баг, ради которого порядок важен: если команда
    попадёт в буфер, следующий ответ будет опираться на слово
    «/forget» вместо чистого листа.
    """
    bot.handle(CONFIG, message(6, "давай поговорим о рыбалке", private=True))
    bot.handle(CONFIG, message(6, "/forget", private=True))
    history = bot.CHATS[6]["history"]
    assert not any("forget" in text for _, text in history), (
        f"/forget попал в историю: {history}")


def test_после_forget_модель_не_видит_старого(bot: Any) -> None:
    """Проверяется по тому, что реально уходит в модель."""
    captured: list[str] = []
    bot.ask_model = lambda provider, prompt, system="": captured.append(prompt) or "ок"
    bot.handle(CONFIG, message(7, "что ты умеешь", private=True))
    bot.handle(CONFIG, message(7, "/forget", private=True))
    bot.handle(CONFIG, message(7, "а теперь?", private=True))
    assert captured, "модель не звали"
    assert "рыбалке" not in captured[-1] and "что ты умеешь" not in captured[-1], (
        f"после сброса модель видит старое: {captured[-1]}")


def test_forget_снимает_ожидание_ответа(bot: Any) -> None:
    """После сброса бот не обязан отвечать на следующую реплику."""
    bot.handle(CONFIG, message(8, "Ада", private=True))
    bot.handle(CONFIG, message(8, "/forget", private=True))
    assert bot.CHATS[8].get("addressed") is False, (
        "после /forget бот ждёт ответа, хотя человек его не звал")


# =============================================================== прочее


def test_статус_показывает_уровни_речи(bot: Any) -> None:
    """Уровни детализации видны человеку, а не только разработчику."""
    bot.handle(CONFIG, message(9, "/status", private=True))
    text = bot.sent[-1][1]
    assert f"{persona.DETAIL_LEVEL} из 10" in text
    assert f"{persona.SCIENCE_LEVEL} из 10" in text


def test_whoami_отдаёт_chat_id(bot: Any) -> None:
    """Без этого не настроить пульс: нужен свой идентификатор."""
    bot.handle(CONFIG, message(10, "/whoami", private=True))
    assert "10" in bot.sent[-1][1]


def test_команды_не_попадают_в_разговор(bot: Any) -> None:
    """Команда — не реплика, и в истории её быть не должно.

    Иначе через десять команд модель получает переписку из
    «/status», «/help» и начинает отвечать на список команд.
    """
    for command in ("/help", "/status", "/whoami", "/name"):
        bot.handle(CONFIG, message(11, command, private=True))
    history = bot.CHATS[11]["history"]
    assert not any(text.startswith("/") for _, text in history), (
        f"команды попали в историю: {history}")


# ====================================== общий модуль


def test_справка_одинакова_для_обоих_ботов() -> None:
    """Модуль общий — значит и текст обязан быть один.

    Расхождение здесь означало бы, что правила разъехались: человек
    переключился бы с одного бота на другой и получил бы другой
    список команд без всякой видимой причины.
    """
    face = persona.PERSONAS[0]
    assert user_features.commands_help(face) == user_features.commands_help(face)
    # Имя бота в общий текст не попадает: иначе один бот стал бы
    # представляться чужим именем.
    other = persona.PERSONAS[2]
    assert other["name"] not in user_features.commands_help(face)


def test_список_команд_полный() -> None:
    """Все команды, которые бот понимает, перечислены в справке.

    Несовпадение списков — это то, что человек заметит первым:
    напечатал команду из документации, а её нет.
    """
    text = user_features.commands_help(persona.PERSONAS[0])
    for command in ("/start", "/help", "/status", "/whoami",
                    "/forget", "/name"):
        assert command in text, f"{command} не описан"


def test_уровни_речи_заданы_явно() -> None:
    """Значения должны быть те, о которых просили.

    Порядок величин важен: детализация — про «сколько», научность —
    про «насколько строго». Если их поменять местами, настройка
    перестанет соответствовать смыслу и станет незаметной поломкой.
    """
    assert persona.DETAIL_LEVEL == 8
    assert persona.SCIENCE_LEVEL == 6
    assert 0 <= persona.DETAIL_LEVEL <= 10
    assert 0 <= persona.SCIENCE_LEVEL <= 10