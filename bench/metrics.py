"""Сводные метрики по прогонам.

Без чисел непонятно, растёт агент или деградирует. Собранные здесь показатели
отвечают на вопросы, которые важнее процента: где ломается чаще всего, нужен
ли вообще стенд и что чинить в библиотеке эталонов.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .reporter import RunReport

#: Сколько последних прогонов подряд нужно для сигнала «агент деградирует».
TREND_WINDOW = 5


@dataclass
class Metrics:
    """Итоговые числа по набору прогонов."""

    runs: int = 0
    passed: int = 0
    earned: int = 0
    total: int = 0
    duration_sec: float = 0.0
    failed_checks: Counter = None       # type: ignore[assignment]
    reinvented: int = 0
    with_ref: int = 0
    agent_finished: int = 0
    agent_blocked: Counter = None       # type: ignore[assignment]
    per_task: dict[str, float] = None   # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failed_checks is None:
            self.failed_checks = Counter()
        if self.agent_blocked is None:
            self.agent_blocked = Counter()
        if self.per_task is None:
            self.per_task = {}

    # ------------------------------------------------------------------ сводка

    @property
    def success_rate(self) -> float:
        """Доля прогонов без единого провала.

        Строже, чем средний процент: девять задач по 95% и одна по 20% дают
        хороший средний балл при одном реальном провале.
        """
        return round(self.passed / self.runs * 100, 1) if self.runs else 0.0

    @property
    def score(self) -> float:
        return round(self.earned / self.total * 100, 1) if self.total else 0.0

    @property
    def ref_hit_rate(self) -> float:
        """Доля прогонов, где эталон реально использован."""
        return round((self.with_ref - self.reinvented) / self.with_ref * 100, 1) if self.with_ref else 0.0

    @property
    def completion_rate(self) -> float:
        """Доля прогонов, где агент сам объявил задачу выполненной.

        Проверки файлов и «агент доволен» — разные вещи: можно сдать полный
        набор файлов и упасть по лимиту шагов.
        """
        return round(self.agent_finished / self.runs * 100, 1) if self.runs else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "passed": self.passed,
            "success_rate": self.success_rate,
            "score": self.score,
            "earned": self.earned,
            "total": self.total,
            "duration_sec": round(self.duration_sec, 1),
            "completion_rate": self.completion_rate,
            "ref_hit_rate": self.ref_hit_rate,
            "reinvented_wheel": self.reinvented,
            "runs_with_ref": self.with_ref,
            "per_task_percent": self.per_task,
            "failed_checks": dict(self.failed_checks.most_common()),
            "agent_blocked_reasons": dict(self.agent_blocked.most_common(10)),
        }

    def to_markdown(self) -> str:
        rows = [
            "# Метрики стенда",
            "",
            f"| Показатель | Значение |",
            "|---|---:|",
            f"| Прогонов | {self.runs} |",
            f"| Пройдено целиком | {self.passed} ({self.success_rate}%) |",
            f"| Баллы | {self.earned} из {self.total} ({self.score}%) |",
            f"| Агент довёл до конца | {self.completion_rate}% |",
            f"| Эталон использован | {self.ref_hit_rate}% "
            f"({self.with_ref - self.reinvented} из {self.with_ref}) |",
            f"| Общее время | {self.duration_sec / 60:.1f} мин |",
            "",
        ]
        if self.failed_checks:
            rows += [
                "## Что ломается",
                "",
                "| Вид проверки | Провалов |",
                "|---|---:|",
            ]
            for kind, count in self.failed_checks.most_common(10):
                rows.append(f"| {kind} | {count} |")
            rows.append("")
            first = self.failed_checks.most_common(1)[0]
            rows += [
                f"Начинать правки с `{first[0]}` — на него приходится "
                f"{first[1]} провалов.",
                "",
            ]
        if self.agent_blocked:
            rows += ["## Чем останавливался агент", ""]
            for reason, count in self.agent_blocked.most_common(10):
                rows.append(f"- {reason} — {count} раз")
            rows.append("")
        if len(self.per_task) > 1:
            rows += ["## По заданиям", "", "| Задание | % |", "|---|---:|"]
            for task, percent in sorted(self.per_task.items(), key=lambda kv: kv[1]):
                rows.append(f"| {task} | {percent}% |")
            rows.append("")
        return "\n".join(rows)


def collect(reports: list[RunReport]) -> Metrics:
    """Собрать метрики по отчётам."""
    metrics = Metrics(runs=len(reports))
    for report in reports:
        metrics.earned += report.earned
        metrics.total += report.total_weight
        metrics.duration_sec += report.duration_sec
        if report.ok:
            metrics.passed += 1
        for check in report.checks:
            if not check.passed:
                metrics.failed_checks[check.kind] += 1
        if report.ref_usage:
            metrics.with_ref += 1
            if report.reinvented_wheel:
                metrics.reinvented += 1
        if report.agent.get("ok"):
            metrics.agent_finished += 1
        reason = report.agent.get("error") or report.agent.get("pending_question")
        if reason:
            metrics.agent_blocked[str(reason)[:120]] += 1
        metrics.per_task[report.task_id] = report.percent
    return metrics


def trend(reports: list[RunReport], window: int = TREND_WINDOW) -> dict[str, Any]:
    """Растёт агент или нет: сравниваем начало и конец.

    Одна точка тренда не даёт ничего: при window=1 это просто шум, поэтому
    при недостатке данных возвращаем ``null`` и честно говорим об этом.
    """
    ordered = sorted(reports, key=lambda r: r.started_at)
    if len(ordered) < window * 2:
        return {
            "enough_data": False,
            "needed": window * 2,
            "have": len(ordered),
        }
    early = collect(ordered[:window])
    late = collect(ordered[-window:])
    delta = round(late.score - early.score, 1)
    return {
        "enough_data": True,
        "window": window,
        "early_score": early.score,
        "late_score": late.score,
        "delta": delta,
        "verdict": "растёт" if delta > 2 else ("падает" if delta < -2 else "плато"),
    }


def save(metrics: Metrics, reports: list[RunReport], directory: Path) -> dict[str, Path]:
    """Записать метрики рядом с отчётами."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    js = directory / "metrics.json"
    md = directory / "МЕТРИКИ.md"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics.to_dict(),
        "trend": trend(reports),
    }
    js.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md.write_text(
        metrics.to_markdown()
        + f"\nТренд: {trend(reports)}\n",
        encoding="utf-8",
    )
    return {"json": js, "markdown": md}


def load_history(reports_dir: Path) -> list[dict[str, Any]]:
    """Собрать отчёты прошлых прогонов из папок отчётов.

    Нужно для сравнения «сейчас против тогда»: без истории первая же метрика
    говорит о качестве, но не о динамике.
    """
    reports_dir = Path(reports_dir)
    found: list[dict[str, Any]] = []
    for path in sorted(reports_dir.glob("*/*.json")):
        if path.name == "summary.json" or path.name == "metrics.json":
            continue
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return found


__all__ = ["Metrics", "collect", "trend", "save", "load_history"]