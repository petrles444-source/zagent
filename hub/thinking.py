"""Размышление главного агента: запрос разворачивается до детализации 10/10.

Зачем это
---------
Человек пишет коротко: «почини тесты». Модель-смысловик (локальная,
быстрая, всегда на месте) разворачивает это в рабочее задание: что именно
считается результатом, в каком порядке делать, какие крайние случаи, что
проверить перед сдачей, и какие вопросы остались к человеку. Дальше с этим
развёрнутым текстом работает основной агент.

Почему локальная модель
-----------------------
Размышление идёт на каждой задаче, поэтому оно обязано быть быстрым и
бесплатным: локальный рантайм отвечает за секунды и не тратит квоту шлюзов.
Основную работу по коду он всё равно не тянет — это не задача этой модели,
и заметки в каталоге об этом честно написаны.

Уровень детализации 10/10 означает конкретный формат, а не «больше текста»:
пять обязательных разделов, каждый из которых человек может проверить
и поправить перед запуском.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator

from hub import local_llm
from hub.local_llm import LocalLLMError

#: Сколько ждём локальную модель. На процессоре 3B модель думает секунды,
#: но первый запрос грузит веса и может занять минуту — потолок нужен,
#: иначе задача встала бы на размышлении.
THINK_TIMEOUT_S = 300.0

#: Разделы, которые обязаны быть в ответе. Порядок — это и есть порядок
#: работы: размышление обязано читаться сверху вниз.
SECTIONS: tuple[tuple[str, str], ...] = (
    ("Как я понял задачу", "2–4 предложениями: что человек хочет получить "
     "и что считается результатом."),
    ("Результат", "критерии готовности — список проверяемых признаков, "
     "а не «должно работать»."),
    ("Порядок работы", "нумерованные шаги. Каждый шаг — одно действие, "
     "которое можно закончить и проверить."),
    ("Крайние случаи и риски", "что может сломаться, какие допущения "
     "нельзя принимать без проверки."),
    ("Проверка перед сдачей", "точный список команд и осмотров, которыми "
     "доказывается, что задача сделана."),
    ("Вопросы к человеку", "если всё однозначно — так и напиши. Молчание "
     "здесь читается как «вопросы есть, но он их придумал»."),
)

SYSTEM = (
    "Ты — размышление главного агента. Тебе дают короткий запрос человека "
    "и рабочую обстановку. Твоя работа — развернуть запрос в задание, "
    "которое можно взять в руки и выполнить без уточнений.\n"
    "\n"
    "Требования к уровню детализации 10/10:\n"
    "- пиши по-русски, конкретно, без воды и без вступлений;\n"
    "- каждый пункт должен быть проверяемым: команда, файл, условие;\n"
    "- не выдумывай того, чего нет в запросе: непонятное выноси в раздел "
    "«Вопросы к человеку»;\n"
    "- не давай оценок вроде «сложно» или «просто» — разворачивай;\n"
    "- если в запросе есть картинка или файлы, скажи, что с ними делать.\n"
    "\n"
    "Обязательные разделы ответа, в этом порядке и с этими заголовками:\n"
    + "\n".join(f"{i + 1}. {name} — {hint}" for i, (name, hint) in
                enumerate(SECTIONS))
    + "\n\nОтвечай только этими разделами. Без вступления и без прощания."
)

#: Куда смотреть в каталоге: локальный рантайм держит и другие модели,
#: но размышление ведёт та, что помечена лучшей. Поле tier — единственный
#: механизм приоритета в проекте, поэтому и тут он.
GATEWAY = "ollama"

_CACHE_TTL_S = 60.0


class ThinkingError(RuntimeError):
    """Размышление не получилось. Задача при этом не должна падать."""


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def local_models() -> list[str]:
    """Что реально установлено в рантайме, по именам из каталога."""
    try:
        return [str(m.get("name") or m.get("id") or "")
                for m in local_llm.models()]
    except LocalLLMError as exc:
        raise ThinkingError(f"Ollama недоступен: {exc}") from exc


def pick_model(available: list[str] | None = None) -> str:
    """Модель для размышления: лучшая из локальных по каталогу.

    Порядок решения: каталог (tiers.json) говорит, какая локальная модель
    главная; если её нет в рантайме, берём следующую по рангу, а если
    каталог молчит — первую установленную. Молча выбирать нельзя: человек
    должен видеть в журнале, чьё мнение стало заданием.
    """
    installed = available if available is not None else local_models()
    installed = [m for m in installed if m]
    if not installed:
        raise ThinkingError("в Ollama нет ни одной модели")

    ranked: list[tuple[int, str]] = []
    tiers_file = _root() / "config" / "tiers.json"
    try:
        data = json.loads(tiers_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for entry in data.get("models") or []:
        if entry.get("gateway") != GATEWAY:
            continue
        name = str(entry.get("model") or "")
        if name in installed:
            try:
                tier = int(entry.get("tier") or 99)
            except (TypeError, ValueError):
                tier = 99
            ranked.append((tier, name))
    if ranked:
        ranked.sort()
        return ranked[0][1]
    # Каталог пуст или расходится с рантаймом: первая установленная.
    return sorted(installed)[0]


def build_user_prompt(request: str, context: str = "") -> str:
    """Текст, который уходит модели: запрос плюс обстановка."""
    parts = [f"ЗАПРОС ЧЕЛОВЕКА:\n{request.strip()}"]
    if context.strip():
        parts.append(f"ОБСТАНОВКА:\n{context.strip()}")
    parts.append(
        "Разверни запрос в задание по разделам выше. Уровень детализации 10/10."
    )
    return "\n\n".join(parts)


def deepen(request: str, *, model: str | None = None,
           context: str = "", base: str = local_llm.DEFAULT_BASE,
           timeout: float = THINK_TIMEOUT_S) -> str:
    """Развернуть запрос и вернуть текст задания.

    Молчание здесь означает «мысль не сложилась»: возвращаем пустую строку,
    а не исключение — задача должна выполниться по исходному запросу, просто
    без развёрнутого плана.
    """
    text = (request or "").strip()
    if not text:
        return ""
    chosen = model or pick_model()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_prompt(text, context)},
    ]
    try:
        return "".join(local_llm.stream_chat(
            chosen, messages, base=base, timeout=timeout)).strip()
    except LocalLLMError as exc:
        raise ThinkingError(str(exc)) from exc


def deepen_stream(request: str, *, model: str | None = None,
                  context: str = "",
                  base: str = local_llm.DEFAULT_BASE,
                  timeout: float = THINK_TIMEOUT_S) -> Iterator[str]:
    """То же самое по словам: человек видит мысль в процессе.

    На процессоре модель думает секунды, и молчание на экране выглядит
    как зависание. Поток поэтому не «опция интерфейса», а часть смысла.
    """
    text = (request or "").strip()
    if not text:
        return
    chosen = model or pick_model()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_prompt(text, context)},
    ]
    try:
        yield from local_llm.stream_chat(
            chosen, messages, base=base, timeout=timeout)
    except LocalLLMError as exc:
        raise ThinkingError(str(exc)) from exc


def shorten(plan: str, limit: int = 4000) -> str:
    """Обрезать размышление перед передачей агенту.

    Основной агент получает план как контекст, а не как инструкцию
    выполнить всё буквально: очень длинный текст съедает окно модели,
    которое нужно самой задаче. Хвост режем по границе строки.
    """
    text = (plan or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline > limit // 2:
        cut = cut[:newline]
    return cut.rstrip() + "\n… (размышление обрезано)"


def describe() -> dict[str, Any]:
    """Состояние размышления для панели: модель, рантайм, разделы."""
    data: dict[str, Any] = {
        "gateway": GATEWAY,
        "sections": [name for name, _ in SECTIONS],
        "timeout_s": THINK_TIMEOUT_S,
    }
    try:
        installed = local_models()
    except ThinkingError as exc:
        data.update({"running": False, "error": str(exc), "model": ""})
        return data
    data["running"] = True
    data["models"] = installed
    try:
        data["model"] = pick_model(installed)
    except ThinkingError as exc:
        data["model"] = ""
        data["error"] = str(exc)
    return data