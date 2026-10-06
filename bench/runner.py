"""Оркестрация прогона: задание → песочница → агент → проверки → отчёт.

Агент подключается сменной функцией. По умолчанию — настоящий zagent внутри
песочницы, но стенд должен проверяться без сети и без моделей, поэтому есть и
заглушка, которая просто пишет файлы: на ней видно, что реестр проверок,
подсчёт баллов и отчёт работают, даже когда ни одна модель не отвечает.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from .checks import CheckResult, run_all
from .reporter import Reporter, RunReport
from .refbook import RefBook
from .sandbox import Sandbox
from .task import Task, load_task


class AgentRunner(Protocol):
    """Что стенд требует от агента."""

    async def __call__(self, sandbox: Sandbox, prompt: str,
                       timeout: float) -> dict[str, Any]:
        """Выполнить задание в песочнице и вернуть сведения о прогоне.

        Возвращаемый словарь обязан содержать ``ok`` (достиг ли агент цели),
        ``phase``, ``steps``, ``models_used`` и ``tokens`` — из них считается
        завершённость в метриках.
        """
        ...


@dataclass
class BenchConfig:
    """Настройки стенда."""

    tasks_dir: Path
    ref_dir: Path
    reports_dir: Path
    keep_sandboxes: bool = False
    offline: bool = False
    #: По умолчанию 2 (WRITE), а не 1 (READ). Стенд оценивает результат на
    #: диске, и при уровне «только чтение» агент физически не может создать
    #: файлы: прогон заведомо даёт ноль баллов и тратит токены впустую.
    access: int = 2
    max_steps: int = 40
    model: str = ""
    base_dir: Path | None = None

    def resolved_base(self) -> Path:
        return Path(self.base_dir) if self.base_dir else Path(__file__).resolve().parent.parent


# --------------------------------------------------------------- штрафы


def apply_penalties(task: Task, sandbox: Sandbox) -> list[dict[str, Any]]:
    """Штрафы за нарушения, которые не попали в acceptance.

    Без них агент может нагадить рядом с идеальным результатом и всё равно
    получить 100: штраф — про нарушения, а не про недобавленные файлы.
    """
    found: list[dict[str, Any]] = []
    for rule in task.penalties:
        points = int(rule.get("penalty", rule.get("points", 0)))
        if points >= 0:
            continue
        reason = str(rule.get("condition", rule.get("reason", "нарушение")))
        where = rule.get("file") or rule.get("glob")
        pattern = rule.get("pattern")
        if not pattern:
            continue
        targets = (
            [sandbox.root / str(where)] if rule.get("file")
            else [p for p in sandbox.root.rglob(str(where or "**/*")) if p.is_file()]
        )
        if rule.get("glob"):
            targets = [
                p for p in sandbox.root.rglob(str(rule["glob"]))
                if p.is_file() and not any(
                    part.startswith(".") for part in p.relative_to(sandbox.root).parts
                )
            ]
        hits = []
        for path in targets:
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(str(pattern), body, re.IGNORECASE):
                hits.append(path.relative_to(sandbox.root).as_posix())
        if hits:
            found.append({"points": points, "reason": reason, "files": hits[:5]})
    return found


# --------------------------------------------------------------- агент по умолчанию


#: Как выглядят причины отказа провайдера. Ключ — часть текста, значение —
#: что это значит и что делать. Порядок важен: первая подходящая причина
#: и есть ответ, остальные подробности модели потеряют.
FAILURE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Лимит запросов", "у провайдера кончился лимит запросов — подождите или "
                       "смените провайдера (--model)"),
    ("Tool choice is none", "модель вызвала инструмент, но вызов был запрещён — "
                            "эта модель не работает с инструментами, "
                            "выберите другую (--model)"),
    ("Не задан api key", "не задан ключ провайдера: zagent.bat connect"),
    ("401", "ключ отклонён провайдером: проверьте ключ (zagent.bat connect)"),
    ("429", "провайдер отвечает «слишком много запросов» — подождите"),
    ("503", "провайдер временно недоступен"),
    ("timeout", "модель не ответила за отведённое время"),
    ("connection", "нет связи с провайдером — проверьте VPN и интернет"),
)


def diagnose_failure(events: list[str]) -> str:
    """Объяснить пустой провал по тексту событий.

    Агент возвращает пустой ``last``, когда ни одна модель не ответила, и
    причина остаётся только в служебном тексте шага. Без этого разбора отчёт
    говорил «фаза failed» и молчал, а чинить было нечем.
    """
    joined = " ".join(events).lower()
    for needle, meaning in FAILURE_PATTERNS:
        if needle.lower() in joined:
            return f"модели не ответили: {meaning}"
    if "все модели недоступны" in joined:
        return "модели недоступны, подробностей нет — проверьте zagent.bat ping"
    return ""


def make_zagent_runner(config: BenchConfig) -> "AgentRunner":
    """Собрать раннер с настоящим агентом zagent.

    Импорты локальные и отложенные: стенд должен запускаться без сети и без
    ключей, поэтому отсутствие моделей — это ``{"ok": False, ...}``, а не
    ``ImportError`` на верхнем уровне.
    """

    

    async def run(sandbox: Sandbox, prompt: str, timeout: float) -> dict[str, Any]:
        import sys

        root = config.resolved_base()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            # selector_from_registry живёт в hub.agent, а не в hub.select:
            # прежняя версия импортировала его оттуда и падала ImportError на
            # каждом прогоне без сети.
            from hub.agent import (
                Agent,
                AgentConfig,
                make_guard,
                selector_from_registry,
            )
            from hub.autonomy import AccessLevel, Autonomy
            from hub.config import load_gateways
            from hub.registry import collect
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"не удалось импортировать агента: {exc}"}

        try:
            gateways = load_gateways(root, env={})
            registry = await collect(gateways, root=root)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"реестр моделей недоступен: {exc}"}

        try:
            selector = selector_from_registry(
                registry,
                mode="manual" if config.model else "auto",
                manual_ref=config.model,
                root=str(root),
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"селектор не собрался: {exc}"}
        if not getattr(selector, "states", None):
            return {"ok": False, "error": "реестр пуст: нет ни одной доступной модели"}

        # Песочница становится и рабочим каталогом, и физической границей:
        # make_guard берёт base_dir как корень воркспейса.
        agent_config = AgentConfig(
            access=AccessLevel(config.access),
            autonomy=Autonomy.NORMAL,
            base_dir=str(sandbox.root),
            max_steps=config.max_steps,
        )
        guard = make_guard(agent_config)
        events: list[str] = []

        def on_event(event: dict) -> None:
            kind = event.get("type")
            if kind == "step":
                step = event.get("step", {})
                mark = "ok" if step.get("ok") else "!!"
                line = f"[{mark}] {step.get('phase')}: {str(step.get('text', ''))[:160]}"
                # Ошибка шага живёт в отдельном поле, а не в тексте. Без неё
                # в журнале остаётся «[!!] thinking: » — пустая строка, по
                # которой нельзя понять, что именно ответил провайдер.
                problem = step.get("error")
                if problem:
                    line += f" — ОШИБКА: {str(problem)[:400]}"
                events.append(line)
            elif kind == "question":
                events.append(f"ВОПРОС: {event.get('question')}")

        agent = Agent(selector, guard, agent_config, on_event=on_event)
        try:
            result = await asyncio.wait_for(
                agent.run(prompt), timeout=max(60.0, timeout)
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"агент не уложился в {timeout:.0f} с",
                    "events": events[-60:]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"агент упал: {type(exc).__name__}: {exc}",
                    "events": events[-60:]}

        # Разбор причины неудачи. Без него отчёт писал «фаза failed» с пустым
        # текстом, и по такому прогону нельзя было понять, что именно сломалось:
        # лимит запросов у провайдера или несовместимость модели с вызовом
        # инструментов — это разные вещи с разными починками.
        if not result.get("ok") and not result.get("last"):
            diagnosis = diagnose_failure(events)
            if diagnosis:
                return {
                    "ok": False,
                    "phase": result.get("phase"),
                    "steps": result.get("steps"),
                    "duration_ms": result.get("duration_ms"),
                    "models_used": result.get("models_used"),
                    "tokens": result.get("tokens"),
                    "last": "",
                    "events": events[-60:],
                    "error": diagnosis,
                    "diagnosis": diagnosis,
                }

        return {
            "ok": bool(result.get("ok")),
            "phase": result.get("phase"),
            "steps": result.get("steps"),
            "duration_ms": result.get("duration_ms"),
            "models_used": result.get("models_used"),
            "tokens": result.get("tokens"),
            "pending_question": result.get("pending_question"),
            "last": (result.get("last") or "")[:2000],
            "events": events[-60:],
            "error": None if result.get("ok") else (result.get("last") or "")[:400],
        }

    return run


def make_echo_runner() -> "AgentRunner":
    """Заглушка: переписывает эталон под задачу, не вызывая моделей.

    Нужна, чтобы убедиться, что стенд рабочий, не тратя токены. Заглушка
    делает ровно то, что делал бы хороший агент: берёт эталон и адаптирует
    под свою задачу. Тогда прогон `--dry` должен быть зелёным — иначе
    невозможно отличить «проверки настроены неверно» от «агент не справился».
    """

    async def run(sandbox: Sandbox, prompt: str, timeout: float) -> dict[str, Any]:
        made: list[str] = []
        # Берём только ПЕРВЫЙ подложенный эталон: это primary из задания.
        # Подкладываются все подсказки, но разворачивать в корень нужно одну —
        # иначе файлы второго эталона перетирают первый (у waitlist другой
        # набор брейкпоинтов, и проверка адаптива врёт).
        for staged in sandbox.staged_refs[:1]:
            source = sandbox.root / staged
            for path in source.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {
                    ".html", ".css", ".js", ".py", ".md"
                }:
                    continue
                target = sandbox.root / path.relative_to(source)
                body = path.read_text(encoding="utf-8", errors="replace")
                # Небольшая правка — как адаптация, а не копипаст.
                body = body.replace("TaskFlow", "Задачи").replace(
                    "Демонстрационный пример", "Учебный проект"
                )
                sandbox.write(target.relative_to(sandbox.root).as_posix(), body)
                made.append(target.relative_to(sandbox.root).as_posix())

        if not made:
            # Эталона не было — пишем минимальный комплект с нуля.
            sandbox.write("index.html", (
                "<!doctype html><html lang=ru><head><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>Заглушка</title></head><body></body></html>\n"
            ))
            made.append("index.html")

        return {
            "ok": True, "phase": "done", "steps": 1, "models_used": [],
            "tokens": 0, "files": made,
            "events": ["заглушка: файлы созданы без обращения к моделям"],
        }

    return run


# --------------------------------------------------------------- прогон


@dataclass
class Bench:
    """Стенд целиком."""

    config: BenchConfig
    refbook: RefBook = field(init=False)
    reporter: Reporter = field(init=False)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.refbook = RefBook(self.config.ref_dir)
        self.reporter = Reporter(self.config.reports_dir)
        if self.refbook.load_errors:
            self.notes.extend(f"библиотека: {e}" for e in self.refbook.load_errors)
        for broken in self.refbook.broken():
            self.notes.append(
                f"эталон {broken.id}: папки {broken.path} нет, подложить нечего"
            )

    # ----------------------------------------------------------------- один прогон

    async def run_task(self, task: Task, *, stamp: str | None = None) -> RunReport:
        started = datetime.now().isoformat(timespec="seconds")
        clock = time.monotonic()

        sandbox = Sandbox.create(keep=self.config.keep_sandboxes)

        staged: list[Path] = []
        try:
            sandbox.stage_index(self.refbook.root / "INDEX.yaml")
            for hint in task.ref_hints:
                entry = self.refbook.resolve(hint)
                if entry is None:
                    self.notes.append(f"{task.task_id}: эталон {hint!r} не найден в индексе")
                    continue
                source = self.refbook.dir_of(entry)
                if source is None:
                    self.notes.append(f"{task.task_id}: папка эталона {entry.path} отсутствует")
                    continue
                if sandbox.stage_ref(source, name=entry.id, original_path=entry.path):
                    staged.append(source)

            ref_summary = self.refbook.summary(only=task.ref_hints)

            # Дизайн-система отдельной строкой в задании: палитра, шрифты и
            # правила из неё нужны не всем заданиям, а кодовый эталон из
            # библиотеки — не всем сайтам. Раньше описание стиля вообще не
            # доезжало до агента, и он подбирал цвета на глаз.
            design = None
            if task.design_hint:
                design = self.refbook.design_by_id(task.design_hint)
                if design is None:
                    self.notes.append(
                        f"{task.task_id}: дизайн-система {task.design_hint!r} "
                        "не найдена в библиотеке"
                    )
            design_summary = design.short_brief() if design else ""
            if design:
                # Полный файл кладём в песочницу: краткой выжимки не хватит,
                # когда понадобится сетка или радиусы.
                staged.append(self.refbook.root / design.path)

            prompt = task.prompt(ref_summary=ref_summary,
                                 design_summary=design_summary)

            if self.config.offline:
                info = await make_echo_runner()(sandbox, prompt, task.timeout_minutes * 60)
            else:
                info = await make_zagent_runner(self.config)(
                    sandbox, prompt, task.timeout_minutes * 60
                )

            artifacts = sandbox.artifacts()
            results = run_all(sandbox.root, task.checks)
            penalties = apply_penalties(task, sandbox)

            usage: dict[str, Any] = {}
            if staged:
                usage = self.refbook.usage_report(staged[0], artifacts)

            report = RunReport(
                task_id=task.task_id,
                started_at=started,
                duration_sec=time.monotonic() - clock,
                agent=info,
                checks=results,
                penalties=penalties,
                ref_usage=usage,
                artifacts=sorted(artifacts),
                tree=sandbox.tree(),
                staged_refs=sandbox.staged_refs,
                notes=[n for n in self.notes if task.task_id in n],
            )
            directory = self.reporter.run_dir(stamp)
            report_paths = self.reporter.save(report, directory)
            report.agent["report"] = str(report_paths["markdown"])
            return report
        finally:
            sandbox.cleanup()

    # ------------------------------------------------------------------- пачка

    async def run_all(self, tasks: list[Task], *, stamp: str | None = None) -> list[RunReport]:
        """Прогнать несколько заданий подряд.

        Одно падение не должно отменять остальные: иначе одна сломанная
        задача прячет результаты девяти нормальных.
        """
        reports: list[RunReport] = []
        for task in tasks:
            try:
                reports.append(await self.run_task(task, stamp=stamp))
            except Exception as exc:  # noqa: BLE001
                failed = RunReport(
                    task_id=task.task_id,
                    started_at=datetime.now().isoformat(timespec="seconds"),
                    duration_sec=0.0,
                    agent={"ok": False, "error": f"стенд упал: {type(exc).__name__}: {exc}"},
                    checks=[CheckResult(
                        id=c.id, kind=c.kind, passed=False, weight=c.weight,
                        message="проверка не выполнялась: прогон упал",
                    ) for c in task.checks],
                    notes=[f"исключение стенда: {exc}"],
                )
                reports.append(failed)
                self.notes.append(f"{task.task_id}: прогон упал — {exc}")
        return reports


def load_one(path: Path) -> Task:
    return load_task(Path(path))


#: Удобная сигнатура для внешних вызовов.
RunFn = Callable[[Sandbox, str, float], Awaitable[dict[str, Any]]]

__all__ = [
    "Bench", "BenchConfig", "make_zagent_runner", "make_echo_runner",
    "apply_penalties", "load_one", "RunFn",
]