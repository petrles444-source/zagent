"""Параллельный health-check моделей.

Статусы (ТЗ, раздел 5.1):
  ok   — HTTP 200, ответ непустой, время < slow_after
  slow — HTTP 200 и непустой ответ, но время >= slow_after
  down — ошибка сети, 4xx/5xx или пустой ответ
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from hub.bus import gather_chats, log_usage, usage_record
from providers.base import Provider

#: короткий запрос для пинга
HEALTH_PROMPT = "Скажи одно слово: работает?"

#: порог "медленно", сек
SLOW_AFTER_S = 5.0

STATUS_OK = "ok"
STATUS_SLOW = "slow"
STATUS_DOWN = "down"
#: Лимит запросов исчерпан, но модель жива: через минуту отвечит снова.
#: Раньше такой случай считался `down`, и модель выпадала из ротации
#: как нерабочая - хотя в реестре тот же 429 честно помечается
#: как `limited`.
STATUS_LIMITED = "limited"

HEALTH_ROLE = "health"


@dataclass(frozen=True)
class HealthReport:
    """Результат пинга одной модели."""

    model_id: str
    label: str
    status: str
    duration_ms: int
    tokens_in: int
    tokens_out: int
    error: str | None = None
    status_code: int | None = None

    @property
    def seconds(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def alive(self) -> bool:
        return self.status in (STATUS_OK, STATUS_SLOW)


def _classify(result: dict[str, Any], slow_after: float) -> str:
    # 429 и 529 - это не поломка модели, а исчерпанный лимит. Проверяем
    # раньше общего «есть ошибка - значит down», иначе живая модель на
    # минуту уходит из ротации и портит статистику.
    status_code = result.get("status") or result.get("status_code")
    if status_code in (429, 529):
        return STATUS_LIMITED
    if result.get("error") is not None:
        return STATUS_DOWN
    if not str(result.get("text") or "").strip():
        return STATUS_DOWN
    if result.get("duration_ms", 0) >= slow_after * 1000:
        return STATUS_SLOW
    return STATUS_OK


def _to_report(model: dict[str, str], result: dict[str, Any], slow_after: float) -> HealthReport:
    status = _classify(result, slow_after)
    return HealthReport(
        model_id=model["id"],
        label=model.get("label") or model["id"],
        status=status,
        duration_ms=int(result.get("duration_ms") or 0),
        tokens_in=int(result.get("tokens_in") or 0),
        tokens_out=int(result.get("tokens_out") or 0),
        error=result.get("error"),
        status_code=result.get("status"),
    )


def _detail(report: HealthReport) -> str:
    if report.alive:
        return f"tokens: {report.tokens_in}+{report.tokens_out}"
    message = report.error or "пустой ответ"
    if report.status_code:
        return f"HTTP {report.status_code} · {message}"
    return message


async def check_all(
    provider: Provider,
    models: Sequence[dict[str, str]],
    *,
    prompt: str = HEALTH_PROMPT,
    role: str = HEALTH_ROLE,
    slow_after: float = SLOW_AFTER_S,
    log: bool = True,
    root: str | None = None,
) -> list[HealthReport]:
    """Параллельно пингануть все модели и вернуть отчёты в порядке списка."""
    messages = [{"role": "user", "content": prompt}]
    model_ids = [model["id"] for model in models]
    results = await gather_chats(provider, model_ids, messages, temperature=0)

    reports: list[HealthReport] = []
    for model, result in zip(models, results):
        reports.append(_to_report(model, result, slow_after))
        if log:
            log_usage(usage_record(model=model["id"], role=role, result=result), root=root)
    return reports


def format_reports(reports: Sequence[HealthReport]) -> str:
    """Таблица отчётов: id, статус, время, токены или ошибка."""
    if not reports:
        return "Нет моделей для проверки."
    width = max(len(report.model_id) for report in reports) + 2
    lines = [
        f"{report.model_id:<{width}}{report.status:<8}{report.seconds:>6.1f}s  {_detail(report)}"
        for report in reports
    ]
    return "\n".join(lines)
