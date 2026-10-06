"""Режим «Авто»: программа сама решает, как выполнять задачу.

Задача одна и та же, а способы разные: «посчитай 2+2» не требует ни
разведки, ни субагентов, а «собери многостраничный сайт по этому макету»
требует и того, и другого. Заставлять человека угадывать режим перед
каждой задачей — значит либо тратить время, либо забывать включить нужное
и получать ответ по памяти модели вместо проверки по источникам.

Решение принимается в три ступени, и каждая следующая хуже предыдущей:

1. **Модель.** Один запрос с жёстким форматом ответа: нужно ли искать в
   интернете и на сколько частей дробить задачу.
2. **Признаки из текста.** Если модель промолчала или ответила мусором —
   разбираем слова в самой задаче. Дешевле и предсказуемее, чем просить
   ещё раз.
3. **Обычный режим.** Ничего не включаем. Задача выполнится и без этого.

Требования, из-за которых модуль написан так, а не иначе:

* **Решение не может уронить задачу.** Любая ошибка на любой ступени
  приводит к обычному режиму, а не к отказу работать.
* **Причина обязана быть видна.** Решение без объяснения — это
  непредсказуемость: человек не понимает, почему задача выполнялась
  полтора минуты, и в следующий раз выключит «Авто» навсегда.
* **Решение не может стоить дороже задачи.** Один запрос с маленьким
  лимитом токенов и без инструментов.
* **Мощность ограничена аккаунтами.** Субагентов не может быть больше,
  чем свободных ключей: иначе половина задания будет ждать в очереди.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

#: Максимум субагентов, которых имеет смысл запускать. Больше — уже не
#: параллельная работа, а очередь, в которой все ждут одного.
MAX_SUBAGENTS = 6

#: Сколько токенов отдаём классификатору. Ответ — короткий JSON, а
#: reasoning-модели тратят первые токены на размышление и при малом
#: лимите возвращают пустоту: мы это уже видели на openai/gpt-oss.
DECIDER_MAX_TOKENS = 1500

#: Признаки того, что задача про то, что вышло недавно. Слова взяты из
#: реальных формулировок, а не из общих соображений: «новый», «сейчас»,
#: «актуальн» встречаются и в «новый файл», где поиск не нужен.
_FRESH_WORDS = (
    "новый", "новые", "новое", "последн", "свеж", "актуальн", "сегодня",
    "сейчас", "текущ", "на сегодня", "верси", "релиз", " changelog",
    "цена", "цены", "курс", "новости", "обзор", "сравнени", "рейтинг",
    "документац", "дока", "официальн", "стабильн", "производств",
)

#: Признаки того, что задача про собственное знание: математику, текст,
#: перевод, разбор готового кода. Поиск тут не нужен и только тратит время.
_LOCAL_WORDS = (
    "посчитай", "посчитать", "вычисли", "переведи", "перевод", "напиши текст",
    "придумай", "исправь опечат", "сумм", "сложи", "раздели", "объясни",
    "перескажи", "составь список", "приведи в порядок этот файл",
)

#: Признаки задачи, которая дробится на части. Одна модель справляется с
#: одной страницей и не справляется с десятью.
_SPLIT_WORDS = (
    "сайт", "лендинг", "лендинги", "приложение", "игру", "игра", "панель",
    "дашборд", "личный кабинет", "модуль", "микросервис", "перенос",
    "перепиши", "вынеси", "дроб",
)

#: Признаки, по которым дробить нужно сразу, даже если задача короткая.
#: «Многостраничный сайт» не требует длинного текста, чтобы быть большой
#: работой: требовать тут длины значит пропускать ровно те задачи, ради
#: которых режим и сделан.
_STRONG_SPLIT = (
    "многостранич", "несколько страниц", "много страниц", "все страниц",
    "каждую страницу", "каждой страниц", "для каждого", "каждый экран",
    "все экраны", "каждый файл", "каждую папку", "много файлов",
    "под ключ", "целиком", "полностью", "перенеси всё",
)


@dataclass
class Decision:
    """Решение по режиму и почему оно такое."""

    web_research: bool = False
    subagents: int = 0
    reason: str = ""
    #: Чем решено: model | heuristic | default.
    source: str = "default"
    model: str = ""
    #: Что модель ответила, — для журнала. Пусто, если решали признаками.
    raw: str = ""

    @property
    def mode(self) -> str:
        """Короткое имя режима для интерфейса."""
        if self.subagents and self.web_research:
            return "разведка + субагенты"
        if self.subagents:
            return f"субагенты ({self.subagents})"
        if self.web_research:
            return "веб-разведка"
        return "обычный"

    def to_dict(self) -> dict[str, Any]:
        return {
            "web_research": self.web_research,
            "subagents": self.subagents,
            "reason": self.reason,
            "source": self.source,
            "model": self.model,
            "mode": self.mode,
        }


@dataclass
class Limits:
    """Чем ограничен выбор: сколько аккаунтов и сколько шагов."""

    free_accounts: int = 0
    max_steps: int = 40
    #: Разрешено ли решение о субагентах вообще (например, режим выбран рукой).
    allow_subagents: bool = True
    allow_web: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ разбор

#: Ключи, которые модель может назвать вместо `web_research`.
_TRUE_WORDS = ("да", "true", "yes", "1", "нужно", "да_нужно")
_FALSE_WORDS = ("нет", "false", "no", "0", "не нужно", "нет_нужно")


def _truthy(value: Any) -> bool:
    """Понимает и логическое, и словесное «да»."""
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return False


def _as_int(value: Any, *, low: int, high: int) -> int:
    """Число из ответа модели. Мусок и «нет» — это ноль, а не единица."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(low, min(high, value))
    if isinstance(value, float):
        return max(low, min(high, int(value)))
    text = str(value or "").strip().lower()
    match = re.search(r"\d+", text)
    if not match:
        return 0
    return max(low, min(high, int(match.group(0))))


def parse_decision(text: str) -> Decision | None:
    """Разобрать ответ классификатора. None — ответ непригоден.

    Разбор мягкий по очевидным причинам: строгий `json.loads` отверг бы
    ответ, в котором модель забыла запятую, а такой ответ всё равно
    полезен. Не берётся только первое число и только целое — это уже
    не «мягкий разбор», а выдумывание решения.
    """
    raw = str(text or "")
    if not raw.strip():
        return None
    # Модели часто оборачивают JSON в блок ```json.
    for candidate in (raw, *_json_blocks(raw)):
        data = _loads(candidate)
        if not isinstance(data, dict):
            continue
        # Ответ может быть обёрнут: {"decision": {...}}.
        inner = data.get("decision") or data.get("mode") or data
        if not isinstance(inner, dict):
            continue
        web = _first_key(inner, ("web_research", "web", "research", "internet",
                                 "search", "нужен_поиск", "поиск"))
        subs = _first_key(inner, ("subagents", "sub", "parts", "pieces", "субагенты",
                                  "агенты", "частей", "част"))
        reason = _first_key(inner, ("reason", "why", "why_not", "обоснование",
                                    "причина", "почему")) or ""
        if web is None and subs is None and not reason:
            continue
        return Decision(
            web_research=_truthy(web),
            subagents=_as_int(subs, low=0, high=MAX_SUBAGENTS),
            reason=" ".join(str(reason).split())[:200],
            source="model",
            raw=raw[:400],
        )
    return None


def _json_blocks(text: str) -> list[str]:
    """Кандидаты на JSON из текста ответа."""
    blocks = re.findall(r"```(?:json)?\s*(.+?)```", text, re.S)
    # Первый и последний волнистый блок: модель могла обрамить ответ
    # фигурными скобками прямо в тексте.
    blocks.append(text.strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        blocks.append(text[start:end + 1])
    return [b.strip() for b in blocks if b and b.strip()]


def _loads(text: str) -> Any:
    """JSON, а если не вышло — как Python-литерал. Никакого `eval`."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def _first_key(data: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


# ---------------------------------------------------------------- признаки


def _has(text: str, words: tuple[str, ...]) -> list[str]:
    """Какие из слов встретились — их и показываем в объяснении."""
    return [word for word in words if word.strip() and word in text]


def score_task(task: str, limits: Limits | None = None) -> Decision:
    """Решение по самому тексту задачи. Используется, если модель молчала.

    Намеренно грубо и предсказуемо: человек должен иметь возможность
    предсказать решение заранее, иначе «Авто» превращается в лотерею.
    """
    limits = limits or Limits()
    text = (task or "").lower().replace("ё", "е")
    fresh = _has(text, _FRESH_WORDS)
    local = _has(text, _LOCAL_WORDS)
    split = _has(text, _SPLIT_WORDS)
    strong = _has(text, _STRONG_SPLIT)

    # Поиск: нужен там, где важна свежесть. Признаки «своей работы» важнее:
    # «посчитай и сравни с документацией» — это всё-таки про документацию.
    web = bool(fresh) and not (local and not fresh)
    if local and fresh:
        web = True

    # Дробление: задача либо сама говорит про масштаб («многостраничный»),
    # либо длинная и про то, что делают в больших объёмах. Одной
    # многословности мало — описание одного файла бывает длинным.
    long_task = len(task or "") > 320
    subs = bool(strong) or (bool(split) and long_task)

    reason_bits: list[str] = []
    if web:
        reason_bits.append("задача про то, что меняется — нужен интернет")
    if subs:
        reason_bits.append("задача на несколько частей — нужны субагенты")
    if not reason_bits:
        reason_bits.append("признаков разведки и разбиения нет")

    decision = Decision(
        web_research=web and limits.allow_web,
        subagents=min(3, MAX_SUBAGENTS) if subs else 0,
        reason="; ".join(reason_bits),
        source="heuristic",
    )
    if subs and not limits.allow_subagents:
        decision.subagents = 0
    return apply_limits(decision, limits)


def apply_limits(decision: Decision, limits: Limits) -> Decision:
    """Ограничить решение тем, чем реально располагаем.

    Субагентов нельзя больше, чем свободных аккаунтов: каждый занимает
    свой аккаунт, а лишние будут стоять в очереди и только растянут
    задачу. Ниже двух субагентов дробить бессмысленно — выигрыш не
    окупит накладных расходов.
    """
    if not limits.allow_web:
        decision.web_research = False
    if not limits.allow_subagents:
        decision.subagents = 0
        if decision.web_research:
            decision.reason += "; субагенты выключены режимом"
        return decision

    cap = MAX_SUBAGENTS
    if limits.free_accounts:
        # Два аккаунта оставляем главному агенту: иначе он не сможет
        # собрать результат, пока части ещё работают.
        cap = max(0, min(cap, limits.free_accounts - 2))
    if decision.subagents > cap:
        decision.reason += f"; субагентов урезали до {cap} по числу аккаунтов"
        decision.subagents = cap
    return decision


# ------------------------------------------------------------------ модель


#: Инструкция классификатору. Короткая намеренно: длинный промпт стоит
#: токенов на каждой задаче, а решать тут немного.
DECIDER_SYSTEM = (
    "Ты распределитель задач. Ответь ТОЛЬКО JSON, без пояснений и без "
    "блока ```json:\n"
    '{"web_research": true|false, "subagents": 0..6, "reason": "коротко, по-русски"}\n'
    "\n"
    "web_research — нужен ли интернет: задача про то, что меняется "
    "(новые версии, цены, новости, свежая документация) или требует "
    "проверки фактов по источникам. Не нужен для математики, перевода, "
    "текста и правки готовых файлов, которые уже есть рядом.\n"
    "subagents — на сколько частей дробить: 0 означает «одна модель "
    "справится». Больше нужен только для больших задач: многостраничный "
    "сайт, много файлов, много экранов.\n"
    "reason — одно предложение, почему именно так."
)


async def decide_by_model(task: str, caller: Any, *,
                          limits: Limits | None = None) -> Decision | None:
    """Спросить модель. None — она не ответила или ответ непригоден.

    Ошибки не поднимаются наружу: классификатор не имеет права уронить
    задачу, иначе отказ одной вспомогательной модели остановил бы работу.
    """
    limits = limits or Limits()
    try:
        result = await caller.ask(
            [{"role": "system", "content": DECIDER_SYSTEM},
             {"role": "user", "content": task}],
            temperature=0.0,
            max_tokens=DECIDER_MAX_TOKENS,
        )
    except Exception:
        return None

    if result.get("error"):
        return None
    decision = parse_decision(str(result.get("text") or ""))
    if decision is None:
        return None
    decision.model = str(result.get("model") or "")
    return apply_limits(decision, limits)


async def choose(task: str, caller: Any | None = None, *,
                 limits: Limits | None = None) -> Decision:
    """Решение о режиме: модель, затем признаки, иначе обычный.

    Порядок не случаен. Модель понимает нюансы, которых нет в списках
    слов, но может промолчать, не ответить или ответить мусором — тогда
    разбираем текст сами. Никогда не отказываем: худший вариант, обычный
    режим, всегда работает.
    """
    limits = limits or Limits()

    if caller is not None:
        decision = await decide_by_model(task, caller, limits=limits)
        if decision is not None:
            # Модель могла ответить «обычный режим» на задачу, где есть
            # явный «новый» и явный «сайт». Тогда верим тексту: он
            # сработает на таких задачах, а модель — не всегда.
            return _merge(decision, score_task(task, limits), task, limits)

    return score_task(task, limits)


def _merge(by_model: Decision, by_words: Decision, task: str,
           limits: Limits) -> Decision:
    """Соединить два решения: модель решает, слова только подстраховывают.

    Разлад не даём: если модель ответила «интернет не нужен», а в задаче
    есть «последняя версия» и «цена», верим тексту. Ошибиться в сторону
    лишней разведки дешевле, чем ответить по памяти модели то, что
    изменилось после её обучения.
    """
    reason = by_model.reason or ""
    web = by_model.web_research
    subs = by_model.subagents

    if by_words.web_research and not web:
        web = True
        reason = (reason + "; в тексте есть «" + "», «".join(
            _has(task.lower().replace("ё", "е"), _FRESH_WORDS)[:2]) + "»").strip("; ")
    if by_words.subagents and not subs:
        subs = by_words.subagents
        reason = (reason + "; задача на несколько частей").strip("; ")
    if not reason:
        reason = by_words.reason
    return apply_limits(Decision(
        web_research=web, subagents=subs, reason=reason[:200],
        source="model", model=by_model.model, raw=by_model.raw,
    ), limits)