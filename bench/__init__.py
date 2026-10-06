"""Стенд для проверки агента.

Устройство: задание (``tasks/*.yaml``) выполняется в изолированной папке,
результат проверяется декларативными проверками из самого задания, рядом
кладётся отчёт и метрики. Библиотека эталонов (``ref/INDEX.yaml``)
подкладывается в песочницу, и по сходству результата с эталоном определяется,
изобрёл агент своё или взял готовое.

Импорты лёгкие: ``bench`` можно импортировать ради ``Metrics`` без сети и без
моделей. Модули с реальным запуском агента импортируются по месту.
"""

from __future__ import annotations

from .checks import CheckResult, known_kinds, run_all, run_check
from .metrics import Metrics, collect, trend
from .refbook import RefBook, RefEntry
from .reporter import Reporter, RunReport, to_markdown, to_summary_markdown
from .runner import Bench, BenchConfig, apply_penalties, make_echo_runner, make_zagent_runner
from .sandbox import Sandbox
from .task import Check, Task, TaskError, load_task, load_tasks

__version__ = "1.0.0"

__all__ = [
    # задание
    "Task", "Check", "TaskError", "load_task", "load_tasks",
    # проверки
    "CheckResult", "run_check", "run_all", "known_kinds",
    # песочница и эталоны
    "Sandbox", "RefBook", "RefEntry",
    # прогон
    "Bench", "BenchConfig", "make_zagent_runner", "make_echo_runner", "apply_penalties",
    # отчёт и метрики
    "RunReport", "Reporter", "to_markdown", "to_summary_markdown",
    "Metrics", "collect", "trend",
]