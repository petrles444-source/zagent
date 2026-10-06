"""Отчёты по прогону: Markdown для человека и JSON для счётчиков."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .checks import CheckResult
from .task import Task


@dataclass
class RunReport:
    """Всё, что известно о прогоне."""

    task_id: str
    started_at: str
    duration_sec: float
    agent: dict[str, Any] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)
    penalties: list[dict[str, Any]] = field(default_factory=list)
    ref_usage: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    tree: str = ""
    staged_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ счёт

    @property
    def total_weight(self) -> int:
        return sum(c.weight for c in self.checks)

    @property
    def earned(self) -> int:
        return sum(c.earned for c in self.checks)

    @property
    def penalty_points(self) -> int:
        return sum(int(p.get("points", 0)) for p in self.penalties)

    @property
    def percent(self) -> float:
        """Процент с учётом штрафов, но не ниже нуля.

        Штрафы хранятся отрицательными, поэтому они **прибавляются**: иначе
        процент уходит за сотню — и это уже случилось, пока не поправили знак.

        Отрицательный процент в отчёте бесполезен: он не говорит, что делать.
        """
        base = self.total_weight or 1
        raw = (self.earned + self.penalty_points) / base * 100
        return round(max(0.0, raw), 1)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks) and not self.penalties

    @property
    def reinvented_wheel(self) -> bool:
        return bool(self.ref_usage.get("reinvented_wheel"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "started_at": self.started_at,
            "duration_sec": round(self.duration_sec, 1),
            "agent": self.agent,
            "score": {
                "earned": self.earned,
                "total": self.total_weight,
                "percent": self.percent,
                "passed": self.ok,
                "penalty_points": self.penalty_points,
            },
            "checks": [
                {
                    "id": c.id, "kind": c.kind, "passed": c.passed,
                    "weight": c.weight, "earned": c.earned, "message": c.message,
                }
                for c in self.checks
            ],
            "penalties": self.penalties,
            "ref_usage": self.ref_usage,
            "artifacts": self.artifacts,
            "staged_refs": self.staged_refs,
            "tree": self.tree,
            "notes": self.notes,
            "reinvented_wheel": self.reinvented_wheel,
        }


class Reporter:
    """Запись отчётов в папку прогона."""

    def __init__(self, out_root: Path) -> None:
        self.out_root = Path(out_root)

    def run_dir(self, stamp: str | None = None) -> Path:
        stamp = stamp or datetime.now().strftime("%Y-%m-%d_%H%M")
        path = self.out_root / stamp
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, report: RunReport, directory: Path) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        md = directory / f"{report.task_id}.md"
        js = directory / f"{report.task_id}.json"
        md.write_text(to_markdown(report), encoding="utf-8")
        js.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                      encoding="utf-8")
        return {"markdown": md, "json": js}

    def save_summary(self, reports: list[RunReport], directory: Path) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        md = directory / "ИТОГ.md"
        js = directory / "summary.json"
        md.write_text(to_summary_markdown(reports), encoding="utf-8")
        js.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "runs": [r.to_dict() for r in reports],
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        return {"markdown": md, "json": js}


def to_markdown(report: RunReport) -> str:
    """Человекочитаемый отчёт по одному прогону."""
    verdict = "ПРОЙДЕНО" if report.ok else "НЕ ПРОЙДЕНО"
    lines = [
        f"# {report.task_id} — {verdict}",
        "",
        f"**Начало:** {report.started_at}  ",
        f"**Длительность:** {report.duration_sec:.1f} с  ",
        f"**Итог:** {report.earned} из {report.total_weight} "
        f"({report.percent}%)"
        + (f", штрафы {report.penalty_points}" if report.penalties else ""),
        "",
    ]

    if report.agent:
        info = report.agent
        lines += [
            "## Агент",
            "",
            f"- финальная фаза: `{info.get('phase', '?')}`",
            f"- шагов: {info.get('steps', '?')}",
            f"- моделей: {', '.join(info.get('models_used') or []) or '—'}",
            f"- токенов: {info.get('tokens', '?')}",
            f"- задача завершена агентом: {'да' if info.get('ok') else 'нет'}",
            "",
        ]
        if info.get("pending_question"):
            lines += [
                f"> Агент задал вопрос и остановился: {info['pending_question']}",
                ">",
                "> Проверки ниже отражают незавершённую работу.",
                "",
            ]

    lines += ["## Проверки", "", "| Проверка | Вес | Итог | Комментарий |",
              "|---|---:|:---:|---|"]
    for check in report.checks:
        mark = "✔" if check.passed else "✘"
        weight = f"{check.earned}/{check.weight}" if not check.passed else str(check.weight)
        comment = check.message.replace("|", "/").replace("\n", " ")
        lines.append(f"| {check.id} | {weight} | {mark} | {comment} |")

    if report.penalties:
        lines += ["", "## Штрафы", ""]
        for penalty in report.penalties:
            lines.append(f"- **{penalty.get('points', 0):+d}** — {penalty.get('reason', '?')}")

    if report.ref_usage:
        usage = report.ref_usage
        verdict_word = "использован" if usage.get("used") else "НЕ использован"
        lines += [
            "", "## Эталон", "",
            f"- вердикт: {verdict_word}",
            f"- сходство с эталоном: {usage.get('similarity', 0)} "
            f"(порог {usage.get('threshold', '?')})",
            f"- упомянут в коде/документации: {'да' if usage.get('mentioned') else 'нет'}",
        ]
        if usage.get("reinvented_wheel"):
            lines += [
                "",
                "> `reinvented_wheel` — это не приговор. Если задача была "
                "нестандартной, а эталон слабо подходил, метка врёт. "
                "Смотрите, растёт ли таких прогонов.",
            ]

    lines += ["", "## Артефакты", "", "```", report.tree or "(пусто)", "```", ""]

    if report.notes:
        lines += ["## Замечания стенда", ""]
        lines += [f"- {note}" for note in report.notes]
        lines.append("")

    return "\n".join(lines)


def to_summary_markdown(reports: list[RunReport]) -> str:
    """Сводка по нескольким прогонам."""
    if not reports:
        return "# Прогонов не было\n\nПроверьте путь к заданиям.\n"

    total = sum(r.total_weight for r in reports)
    earned = sum(r.earned for r in reports)
    passed = [r for r in reports if r.ok]
    reused = [r for r in reports if not r.reinvented_wheel and r.ref_usage]
    lines = [
        "# Итог стенда",
        "",
        f"**Прогонов:** {len(reports)}  ",
        f"**Пройдено целиком:** {len(passed)}  ",
        f"**Баллов:** {earned} из {total} "
        f"({round(earned / (total or 1) * 100, 1)}%)  ",
        f"**Эталон использован:** {len(reused)} из {len([r for r in reports if r.ref_usage])}",
        "",
        "| Задание | Итог | % | Время | Эталон | Главная претензия |",
        "|---|:---:|---:|---:|:---:|---|",
    ]
    for report in sorted(reports, key=lambda r: -r.percent):
        failed = [c for c in report.checks if not c.passed]
        worst = failed[0].message if failed else "—"
        ref_mark = "—" if not report.ref_usage else ("✔" if not report.reinvented_wheel else "✘")
        lines.append(
            f"| {report.task_id} | {'✔' if report.ok else '✘'} | {report.percent}% | "
            f"{report.duration_sec:.0f} с | {ref_mark} | {worst[:80]} |"
        )

    lines += ["", "## Что чинить первым", ""]
    problems: dict[str, list[str]] = {}
    for report in reports:
        for check in report.checks:
            if not check.passed:
                problems.setdefault(check.kind, []).append(f"{report.task_id}:{check.id}")
    if not problems:
        lines.append("Все проверки прошли.")
    else:
        # Сначала то, что ломается чаще всего: это самые общие дефекты.
        for kind, where in sorted(problems.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"- **{kind}** — {len(where)} раз: {', '.join(where[:8])}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["RunReport", "Reporter", "to_markdown", "to_summary_markdown", "asdict", "Task"]