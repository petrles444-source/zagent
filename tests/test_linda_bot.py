"""Линда: английские фразы в конце ответа и разбор ключевых слов.

Главное в этом боте — пара английских фраз в конце каждого ответа.
Значит, под проверку попадает именно она: не сама формулировка
(её пишет модель), а то, что бот умеет опереться на фразы из
готового ответа, когда по какой-то причине модель их не дала.

Отдельная проверка — иностранные слова с транскрипцией. Правило
«любое иностранное слово в кавычках, с чтением, переводом и
контекстом» общее для обоих ботов, и оно единственное, что
отличает их речь от обычной переписки.
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
    spec = importlib.util.spec_from_file_location(name, BOTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


linda = load("linda_bot")

CONFIG = {
    "token": "t",
    "providers": [{"name": "p", "base_url": "u", "model": "m",
                   "api_key": "k"}],
    "active": 0,
    "persona": "persona",
    "heartbeat_chat_id": "",
    "face": persona.PERSONAS[1],
}


def message(chat_id: int, text: str, *, private: bool = False) -> dict[str, Any]:
    return {
        "message_id": 1,
        "chat": {"id": chat_id, "type": "private" if private else "group"},
        "from": {"id": 7, "is_bot": False, "first_name": "Иван"},
        "text": text,
    }


# =============================================================== фразы


def test_берёт_фразы_из_готового_ответа() -> None:
    """Английские строки достаются из ответа модели."""
    answer = (
        "Сначала нужно сделать «deploy the files» — выложить файлы.\n"
        "Потом проверить «health check» — что сервер отвечает.\n"
        "И смотреть «the logs» — что пишется в журнал.\n"
        "И «the metrics» — цифры по нагрузке.\n"
    )
    found = linda.english_phrases(answer)
    assert found, "фразы не нашлись"
    # Берутся именно первые две: берутся все четыре — это уже список,
    # и он не запоминается.
    assert found == ["deploy the files", "health check"], f"взято: {found}"


def test_берёт_ровно_две_фразы() -> None:
    """Одна фраза — пример, три — список, который не запоминают."""
    answer = "\n".join([
        "«the first step» — первый шаг",
        "«the second step» — второй шаг",
        "«the third step» — третий шаг",
        "«the fourth step» — четвёртый шаг",
    ])
    found = linda.english_phrases(answer)
    assert len(found) == linda.PHRASES_AT_END, f"взято: {found}"
    assert linda.PHRASES_AT_END == 2
    assert found[0] == "the first step"


def test_отбрасывает_хвост_с_переводом() -> None:
    """В «якорь» идёт сама фраза, без перевода и разбора.

    Иначе человек получит в конце ответа строку, где английский текст
    продублирован русским, — выглядит как сбой, а не как учебный
    материал.
    """
    answer = "«deploy the files» — выложить файлы; здесь: на сервер."
    found = linda.english_phrases(answer)
    assert found == ["deploy the files"], f"взяли не то: {found}"


def test_одно_слово_фразой_не_считается() -> None:
    """Слово — это слово. Фраза учит больше, чем один образец."""
    found = linda.english_phrases("«deploy» — выложить.\n«switch» — переключить.")
    assert found == [], f"однословные записи попали в якорь: {found}"


def test_убирает_звёздочки_и_кавычки() -> None:
    """Фраза должна быть чистой, а не с оформлением ответа."""
    found = linda.english_phrases("- **the payload** — что передаём\n"
                                  "- «the request» — сам запрос")
    assert found == ["the payload", "the request"], f"как есть: {found}"


def test_останавливается_на_первых_двух_уникальных() -> None:
    """Повтор одной фразы не занимает место в паре."""
    answer = ("«deploy the files» — выложить\n"
              "«deploy the files» — то же самое\n"
              "«check the logs» — проверить журнал")
    found = linda.english_phrases(answer)
    assert len(found) == 2
    assert len(set(item.lower() for item in found)) == 2


def test_пустой_ответ_даёт_пустой_якорь() -> None:
    """Нет ответа — нет и фраз, а не выдуманные примеры."""
    assert linda.english_phrases("") == []
    assert linda.english_phrases("только русский текст") == []


def test_русский_текст_не_считается_фразой() -> None:
    """Служебные слова бота в якорь не попадают."""
    found = linda.english_phrases("Ответь на последнюю реплику по-русски.")
    assert found == [], f"русская строка попала в якорь: {found}"


# =============================================================== подсказка


def test_подсказка_требует_ровно_две_фразы() -> None:
    """Требование пары фраз должно быть в подсказке явно."""
    text = linda.build_persona(persona.PERSONAS[1])
    assert "две английские фразы" in text
    assert "из разбора" in text, (
        "не сказано, что фразы берутся из самого ответа, "
        "а не случайные")


def test_подсказка_требует_перевод() -> None:
    """Фраза без перевода ничему не учит."""
    text = linda.build_persona(persona.PERSONAS[1])
    assert "перевод" in text


def test_подсказка_содержит_общие_правила_речи() -> None:
    """Уровни детализации и строгости наследуются из persona.py."""
    text = linda.build_persona(persona.PERSONAS[1])
    assert str(persona.DETAIL_LEVEL) in text
    assert str(persona.SCIENCE_LEVEL) in text


def test_собственный_текст_добавляется_в_конец() -> None:
    """Личный текст из настроек главнее общих правил."""
    text = linda.build_persona(persona.PERSONAS[1], "Я ещё учу детей.")
    assert text.rstrip().endswith("Я ещё учу детей.")


# =============================================================== словари


def test_словарь_содержит_нужное() -> None:
    """В словаре есть слова, без которых правило не работает.

    Модель без подсказки транскрипцию выдумывает: «fallback» читается
    то «фолбэк», то «фалбек». Таблица нужна именно для этого.
    """
    for word in ("fallback", "deploy", "token", "endpoint", "cdn", "swf"):
        assert word in persona.GLOSSARY, f"в словаре нет {word}"
        meaning = persona.GLOSSARY[word]
        assert "[" in meaning, f"у {word} нет транскрипции"
        assert "—" in meaning, f"у {word} нет перевода"


def test_словарь_есть_у_учительниц_и_нет_у_ады() -> None:
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



def test_склонение_не_ломает_поиск_слов() -> None:
    """Слово внутри другого слова не считается совпадением.

    «браузеры» не должно ловиться как «браузер»: разбор в кавычки
    попадёт лишнее слово, и ответ станет неуклюжим.
    """
    assert persona.glossary_note("открыли браузеры") == []
    assert persona.glossary_note("настройка deploy") != []


def test_уже_разобранное_слово_не_разбирается_дважды() -> None:
    """Если разбор уже есть, второй раз его дописывать нельзя."""
    text = '«fallback» [фолбэк] — запасной путь.'
    assert persona.glossary_note(text) == []