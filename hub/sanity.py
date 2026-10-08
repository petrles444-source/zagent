"""Проверка адекватности ответов модели.

Дешёвые и бесплатные модели часто ведут себя предсказуемо плохо: смешивают
языки, теряют контекст, начинают повторяться, отвечают пустотой. Такие модели
нельзя пускать в агента, поэтому здесь набор быстрых проверок.

Проверки:
    language      отвечает ли на том же языке, что и вопрос
    context       воспроизводит ли токен из конца промпта (понимает ли контекст)
    follow        выполняет ли простую инструкцию (регистр, счёт, JSON)
    not_degenerate не пустой ли ответ, нет ли повторов и «зацикливания»
    latency       не слишком ли медленная

Каждая проверка даёт 0/1 балл и текст замечания. Итог — оценка 0..1 и вердикт.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

#: Признаки зацикливания: один короткий токен повторяется много раз.
_REPEAT_RE = re.compile(r"(.{2,40}?)\1{4,}", re.S)

#: Фразы-отказы, которые выдают заглушку вместо модели.
_REFUSAL_HINTS = (
    "i cannot assist",
    "i'm sorry",
    "as an ai language model",
    "i don't have access",
    "no puedo",
)


@dataclass
class Check:
    """Результат одной проверки."""

    name: str
    passed: bool
    detail: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "score": self.score,
        }


@dataclass
class SanityReport:
    """Итог проверки одной модели."""

    ref: str
    checks: list[Check] = field(default_factory=list)
    score: float = 0.0
    verdict: str = "unknown"
    latency_ms: int = 0
    sample: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict in ("good", "usable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "score": round(self.score, 2),
            "verdict": self.verdict,
            "latency_ms": self.latency_ms,
            "sample": self.sample,
            "checks": [c.to_dict() for c in self.checks],
        }


def _verdict_for(score: float, checks: list[Check]) -> str:
    """Вердикт по баллам. Критичные проверки (context, follow) весят больше."""
    critical = [c for c in checks if c.name in ("context", "follow", "not_degenerate")]
    critical_failed = [c for c in critical if not c.passed]
    if not critical or (len(critical_failed) == 0):
        if score >= 0.85:
            return "good"
        if score >= 0.6:
            return "usable"
        return "poor"
    if len(critical_failed) == 1 and score >= 0.5:
        return "usable"
    return "poor"


def check_language(answer: str, question: str) -> Check:
    """Ответ должен быть на том же языке, что и вопрос (для кириллицы)."""
    def script_share(text: str) -> float:
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return 0.0
        cyrillic = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
        latin = sum(1 for c in letters if c.isascii() and c.isalpha())
        total = cyrillic + latin
        return cyrillic / total if total else 0.0

    # Ответ без единой буквы - это не «латиница», а математика, JSON или
    # команда. Раньше доля считалась как cyrillic/total, где total - число
    # букв: при нуле букв получался 0.0, срабатывала ветка «ответ ушёл в
    # латиницу» и модель получала 0.0 за то, что ответила точно.
    # Проверять тут нечего - и это не должно ни портить, ни хвалить.
    letters_in_answer = sum(1 for c in answer if c.isalpha())
    if not letters_in_answer:
        return Check("language", True,
                     "ответ без букв (число, JSON или команда): проверять нечего",
                     1.0)

    q = script_share(question)
    a = script_share(answer)
    if q < 0.5:
        # Вопрос не на кириллице — сравнивать нечего, но смешение всё равно ловим.
        return Check("language", True, "вопрос не на кириллице", 1.0)

    if a >= 0.7:
        return Check("language", True, f"кириллица {a:.0%}", 1.0)
    if a <= 0.3:
        return Check("language", False, f"ответ ушёл в латиницу ({a:.0%} кириллицы)", 0.0)
    return Check("language", False, f"смешение языков ({a:.0%} кириллицы)", 0.5)


def check_context(answer: str, token: str) -> Check:
    """Модель должна вспомнить токен, который был в начале длинного промпта."""
    if not answer.strip():
        return Check("context", False, "пустой ответ", 0.0)
    if token.lower() in answer.lower():
        return Check("context", True, "токен из контекста найден", 1.0)
    return Check("context", False, f"не вспомнила токен «{token}»", 0.0)


def check_follow(answer: str) -> Check:
    """Простая инструкция: вернуть ровно JSON с заданным ключом."""
    text = answer.strip()
    if not text:
        return Check("follow", False, "пустой ответ", 0.0)

    # Пытаемся найти JSON-объект в ответе.
    match = re.search(r"\{[^{}]*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and str(data.get("status")) == "ready":
            return Check("follow", True, "JSON-инструкция выполнена", 1.0)
        return Check("follow", False, "JSON есть, но ключи неверны", 0.5)

    if "ready" in text.lower():
        return Check("follow", True, "содержательно, хотя без JSON", 0.7)
    return Check("follow", False, "не выполнила инструкцию", 0.0)


def check_not_degenerate(answer: str) -> Check:
    """Ответ не должен быть пустым, из одних повторов или отказом."""
    text = answer.strip()
    if not text:
        return Check("not_degenerate", False, "пустой ответ", 0.0)

    low = text.lower()
    if any(hint in low for hint in _REFUSAL_HINTS):
        return Check("not_degenerate", False, "отказ вместо ответа", 0.0)

    if _REPEAT_RE.search(text):
        return Check("not_degenerate", False, "зацикливание: фраза повторяется", 0.0)

    words = text.split()
    unique = len(set(words))
    ratio = unique / len(words) if words else 0.0
    if len(words) >= 12 and ratio < 0.35:
        return Check("not_degenerate", False, f"слишком много повторов ({ratio:.0%} уникальных)", 0.0)

    return Check("not_degenerate", True, f"{len(words)} слов", 1.0)


def check_latency(duration_ms: int, *, slow_after_ms: int = 5000) -> Check:
    """Слишком медленная модель в цикле агента тоже непригодна."""
    if duration_ms <= slow_after_ms:
        return Check("latency", True, f"{duration_ms} мс", 1.0)
    if duration_ms <= slow_after_ms * 3:
        return Check("latency", True, f"{duration_ms} мс (медленно)", 0.6)
    return Check("latency", False, f"{duration_ms} мс — слишком медленно", 0.0)


#: Промпт-проба: требует и контекст, и формат, и конкретный токен.
PROBE_CONTEXT_TOKEN = "ZEBRA-7391"

def build_probe_prompt(lang: str = "ru") -> tuple[str, str, str]:
    """Собрать текст пробы. Возвращает (system, user, token).

    Токен зарыт в начале длинного текста, чтобы проверить удержание контекста.
    """
    token = PROBE_CONTEXT_TOKEN
    filler = (
        "Ниже приведён служебный протокол проверки. Прочитайте его целиком. "
        "Код объекта для дальнейших операций: "
        f"{token}. "
        "Протокол содержит следующие разделы. "
    )
    filler += "Раздел 1. Регистрация запросов. " * 6
    filler += "Раздел 2. Обработка ошибок. " * 6
    filler += "Раздел 3. Формирование ответа. " * 6

    if lang == "en":
        system = "You are a strict API responder. Answer only with the requested JSON."
        user = (
            filler
            + '\nAnswer with JSON only, no prose: {"status": "ready", "code": "<the code from the protocol>"}.'
        )
    else:
        system = "Ты строгий API-ответчик. Отвечай только запрошенным JSON, без пояснений."
        user = (
            filler
            + '\nОтветь только JSON без слов: {"status": "ready", "code": "<код из протокола>"}.'
        )
    return system, user, token


def evaluate(
    ref: str,
    answer: str,
    *,
    question: str,
    token: str,
    duration_ms: int,
    lang: str = "ru",
    slow_after_ms: int = 5000,
) -> SanityReport:
    """Собрать полный отчёт по ответу модели."""
    checks = [
        check_not_degenerate(answer),
        check_context(answer, token),
        check_follow(answer),
        check_language(answer, question),
        check_latency(duration_ms, slow_after_ms=slow_after_ms),
    ]
    score = sum(c.score for c in checks) / len(checks)
    report = SanityReport(
        ref=ref,
        checks=checks,
        score=score,
        verdict=_verdict_for(score, checks),
        latency_ms=duration_ms,
        sample=answer.strip()[:200],
    )
    return report


def time_call(func):
    """Декоратор: замеряетwall-clock вызова."""

    async def wrapper(*args, **kwargs):
        started = time.perf_counter()
        result = await func(*args, **kwargs)
        elapsed = int((time.perf_counter() - started) * 1000)
        if isinstance(result, dict):
            result.setdefault("_elapsed_ms", elapsed)
        return result

    return wrapper
