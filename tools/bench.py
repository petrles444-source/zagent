#!/usr/bin/env python
"""Стенд проверки агента: прогнать задания и показать отчёт.

    python tools/bench.py list                 список заданий
    python tools/bench.py check                проверить задания, моделей не трогая
    python tools/bench.py refs                 показать библиотеку эталонов
    python tools/bench.py kinds                список видов проверок
    python tools/bench.py run LANDING-001      прогнать одно задание
    python tools/bench.py run all              прогнать все
    python tools/bench.py run all --dry        прогнать на заглушке, без сети

``--dry`` прогоняет настоящий стенд — проверки, веса, штрафы, отчёт, сходство с
эталоном, — но вместо агента копирует эталон с небольшой правкой. Нужен, чтобы
убедиться, что стенд рабочий, не тратя токены: зелёный прогон означает, что
проверки настроены верно, и красный на живом прогоне будет виной агента.

Полезные флаги:
    --stamp ИМЯ       папка отчётов с именем (для сравнения прогонов)
    --keep            не удалять песочницы
    --access 1|2|3    уровень доступа агента (по умолчанию 2 — запись)
    -v                показать ход агента по шагам
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench import (  # noqa: E402
    Bench,
    BenchConfig,
    RefBook,
    TaskError,
    collect,
    known_kinds,
    load_tasks,
    to_summary_markdown,
    trend,
)
from bench.metrics import save as save_metrics  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

#: Консоль Windows не печатает часть Unicode; без этого вывод падает.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _tasks_dir(args: argparse.Namespace) -> Path:
    return Path(args.tasks) if args.tasks else ROOT / "tasks"


def _ref_dir(args: argparse.Namespace) -> Path:
    return Path(args.refs) if args.refs else ROOT / "ref"


def _config(args: argparse.Namespace) -> BenchConfig:
    return BenchConfig(
        tasks_dir=_tasks_dir(args),
        ref_dir=_ref_dir(args),
        reports_dir=Path(args.reports) if args.reports else ROOT / "reports",
        keep_sandboxes=args.keep,
        offline=args.dry,
        access=args.access,
        max_steps=args.max_steps,
        model=args.model or "",
    )


# --------------------------------------------------------------------- команды


def cmd_list(args: argparse.Namespace) -> int:
    try:
        tasks = load_tasks(_tasks_dir(args))
    except TaskError as exc:
        print(f"Задание не читается: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not tasks:
        print(f"Заданий нет в {_tasks_dir(args)}")
        return EXIT_ERROR
    print(f"Заданий: {len(tasks)}\n")
    for task in tasks:
        print(f"  {task.task_id:16} баллов {task.total_weight:4}  "
              f"проверок {len(task.checks):2}  {task.goal.strip().splitlines()[0][:60]}")
        if task.ref_hints:
            print(f"  {'':16} эталоны: {', '.join(task.ref_hints)}")
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    """Проверить форму заданий и индекс, ничего не выполняя."""
    problems = 0
    try:
        tasks = load_tasks(_tasks_dir(args))
    except TaskError as exc:
        print(f"✘ {exc}")
        return EXIT_ERROR
    if not tasks:
        print(f"✘ заданий нет в {_tasks_dir(args)}")
        problems += 1
    for task in tasks:
        known = known_kinds()
        bad = [c.id for c in task.checks if c.kind not in known]
        print(f"{'✘' if bad else '✔'} {task.task_id}: проверок {len(task.checks)}, "
              f"баллов {task.total_weight}")
        for check in bad:
            print(f"    неизвестный вид проверки {check.kind!r} в {check.id!r}")
            print(f"    есть: {known}")
            problems += 1

    book = RefBook(_ref_dir(args))
    print(f"\n{'✘' if book.load_errors else '✔'} эталонов: {len(book)}")
    for error in book.load_errors:
        print(f"    {error}")
        problems += 1
    for broken in book.broken():
        print(f"    ✘ {broken.id}: папки {broken.path} нет")
        problems += 1

    print("\nЗаданий принято без замечаний." if not problems
          else f"\nЗамечаний: {problems}")
    return EXIT_OK if not problems else EXIT_FAIL


def cmd_refs(args: argparse.Namespace) -> int:
    book = RefBook(_ref_dir(args))
    for error in book.load_errors:
        print(f"! {error}")
    if not len(book):
        print("Библиотека пуста")
        return EXIT_FAIL
    print(f"Эталонов: {len(book)}\n")
    for entry in book:
        state = "на месте" if book.dir_of(entry) else "ПАПКИ НЕТ"
        print(f"  {entry.id:20} [{state:8}] сложность {entry.complexity}  {entry.path}")
        if entry.use_when:
            print(f"  {'':20} когда:  {entry.use_when}")
        if entry.avoid_when:
            print(f"  {'':20} НЕ когда: {entry.avoid_when}")
    return EXIT_OK


def cmd_kinds(args: argparse.Namespace) -> int:
    print("Виды проверок в acceptance:\n")
    for kind in known_kinds():
        print(f"  {kind}")
    print("\nПример в YAML:\n")
    print("""acceptance:
  - id: A1
    kind: contains
    file: index.html
    any_of: ['type="email"', 'checkValidity']
    weight: 10
    description: форма проверяет почту
  - id: B1
    kind: html_images_have_alt
    glob: "**/*.html"
    weight: 5""")
    return EXIT_OK


async def _run(args: argparse.Namespace) -> int:
    try:
        tasks = load_tasks(_tasks_dir(args))
    except TaskError as exc:
        print(f"Задание не читается: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not tasks:
        print(f"Заданий нет в {_tasks_dir(args)}")
        return EXIT_ERROR

    ids = args.task or ["all"]
    if ids == ["all"]:
        wanted = list(tasks)
    else:
        # Отображаем id в задания: иначе дальше по коду идёт строка.
        by_id = {t.task_id: t for t in tasks}
        wanted = [by_id[i] for i in ids if i in by_id]
        unknown = [i for i in ids if i not in by_id]
        for i in unknown:
            print(f"Нет задания {i}")
        if not wanted:
            print(f"Есть: {', '.join(t.task_id for t in tasks)}")
            return EXIT_ERROR

    bench = Bench(_config(args))
    if args.dry:
        print("Режим --dry: вместо агента работает заглушка, сеть не трогается.\n")
    for entry in bench.refbook.load_errors:
        print(f"! библиотека: {entry}")

    # Штамп задаётся один раз и до прогона: иначе каждый отчёт уедет в свою
    # папку по времени, а сводка — в третью, и их невозможно сопоставить.
    stamp = args.stamp or datetime.now().strftime("%Y-%m-%d_%H%M")
    directory = bench.reporter.run_dir(stamp)
    print(f"Отчёты: {directory}\n")

    reports = await bench.run_all(wanted, stamp=stamp)
    for report in reports:
        _print_report(report, verbose=args.verbose)

    bench.reporter.save_summary(reports, directory)
    metrics = collect(reports)
    paths = save_metrics(metrics, reports, directory)

    print("\n" + "=" * 62)
    print(to_summary_markdown(reports))
    move = trend(reports)
    print("Тренд:", move)
    print(f"\nОтчёты: {directory}")
    print(f"Метрики: {paths['markdown'].name}")

    failed = [r for r in reports if not r.ok]
    return EXIT_FAIL if failed else EXIT_OK


def _print_report(report, *, verbose: bool = False) -> None:
    mark = "✔" if report.ok else "✘"
    print("=" * 62)
    print(f"{mark} {report.task_id}  {report.earned}/{report.total_weight} "
          f"({report.percent}%)  {report.duration_sec:.0f} с")
    info = report.agent
    print(f"  агент: фаза {info.get('phase', '?')}, шагов {info.get('steps', '?')}, "
          f"моделей {len(info.get('models_used') or [])}, "
          f"токенов {info.get('tokens', 0)}")
    # Причина важнее сообщения агента: пустой текст при «фаза failed» означает,
    # что ни одна модель не ответила, и без разбора чинить нечего.
    diagnosis = info.get("diagnosis") or info.get("error")
    if diagnosis:
        print(f"  причина: {str(diagnosis)[:400]}")
    elif info.get("error"):
        print(f"  ошибка: {str(info['error'])[:200]}")
    if info.get("pending_question"):
        print(f"  вопрос: {info['pending_question']}")
    for check in report.checks:
        flag = "✔" if check.passed else "✘"
        weight = "" if check.passed else f"  (-{check.weight})"
        print(f"  {flag} {check.id:4} {check.message[:88]}{weight}")
    for penalty in report.penalties:
        print(f"  ! штраф {penalty['points']:+d}: {penalty['reason']}")
    if report.ref_usage:
        usage = report.ref_usage
        print(f"  эталон: {'использован' if not usage['reinvented_wheel'] else 'НЕ использован'}"
              f" (сходство {usage['similarity']}, порог {usage['threshold']})")
    if verbose:
        print("  последнее сообщение агента:")
        for line in str(info.get("last") or "")[:1200].splitlines():
            print(f"    {line}")
        for event in (info.get("events") or [])[-12:]:
            print(f"    · {event}")


# --------------------------------------------------------------------- разбор


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tools/bench.py",
        description="Стенд проверки агента: задания, эталоны, отчёты, метрики.",
    )
    parser.add_argument("--tasks", help="папка с заданиями (по умолчанию ./tasks)")
    parser.add_argument("--refs", help="папка библиотеки эталонов (по умолчанию ./ref)")
    parser.add_argument("--reports", help="куда класть отчёты (по умолчанию ./reports)")
    parser.add_argument("--stamp", help="имя папки прогона (по умолчанию — дата и время)")

    subs = parser.add_subparsers(dest="command")

    subs.add_parser("list", help="показать задания").set_defaults(func=cmd_list)
    subs.add_parser("check", help="проверить форму заданий и индекса").set_defaults(func=cmd_check)
    subs.add_parser("refs", help="показать библиотеку эталонов").set_defaults(func=cmd_refs)
    subs.add_parser("kinds", help="список видов проверок").set_defaults(func=cmd_kinds)

    run = subs.add_parser("run", help="прогнать задания")
    run.add_argument("task", nargs="*", default=None,
                     help="id задания или all (по умолчанию — все)")
    run.add_argument("--dry", action="store_true",
                     help="заглушка вместо агента: стенд проверяется без сети")
    run.add_argument("--keep", action="store_true",
                     help="не удалять песочницы после прогона")
    run.add_argument("--access", type=int, default=2, choices=(1, 2, 3),
                     help="уровень доступа агента: 1 — чтение, "
                          "2 — чтение и запись, 3 — полный "
                          "(по умолчанию 2)")
    run.add_argument("--max-steps", type=int, default=40, help="лимит шагов")
    run.add_argument("--model", help="зафиксировать модель (иначе — авто-выбор)")
    run.add_argument("-v", "--verbose", action="store_true", help="показать ход агента")
    run.set_defaults(func=lambda a: asyncio.run(_run(a)))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_ERROR
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nПрервано.", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())