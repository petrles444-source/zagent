"""Загрузка и проверка задания для стенда.

Задание — это YAML с блоками ``goal``, ``constraints``, ``deliverables`` и
``acceptance``. Проверки в ``acceptance`` объявлены **декларативно**: вид
``kind`` и параметры. Иначе каждое новое задание требовало бы правки кода
тестировщика, и стенд перестал бы быть переиспользуемым.

Пример проверки::

    - id: A2
      kind: contains
      file: index.html
      any_of: ['type="email"', 'pattern=', 'checkValidity']
      weight: 10
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Обязательные ключи верхнего уровня. Без них задание не запускаем: лучше
#: явная ошибка при чтении, чем «всё провалилось» на этапе проверки.
#:
#: ``acceptance`` обязателен не всегда: в интерфейсных заданиях проверки
#: выводятся из deliverables, и автору незачем выписывать их руками.
REQUIRED_KEYS = ("task_id", "goal")

#: Что обязательно для задания с интерфейсом. Через «или»: либо автор
#: описал acceptance руками, либо перечислил что сдать — тогда проверки
#: выводятся сами (см. derive_checks).
NEEDS_ACCEPTANCE = ("acceptance", "deliverables")

#: Поля, которые обязательны в каждой проверке.
REQUIRED_CHECKS = ("id", "kind", "weight")

#: Обязательный минимум в каждой проверке, если не задано `any_of`/`all_of`.
REQUIRED_ARGS = {
    "file_exists": ("path",),
    "no_files": ("glob",),
    "min_files": ("glob",),
    "max_files": ("glob",),
    "min_lines": ("file", "lines"),
    "max_lines": ("file", "lines"),
    "contains": ("file",),
    "not_contains": ("file", "glob", "patterns", "pattern", "any_of"),
    "total_loc": ("glob",),
    "max_loc_per_file": ("glob",),
    "html_images_have_alt": ("glob",),
    "html_has_media_query": ("glob",),
    "py_compiles": ("glob",),
    "tests_pass": (),
    "command_succeeds": ("command",),
    "sql_no_plaintext_password": ("glob",),
    "passwords_hashed": ("glob",),
}


class TaskError(Exception):
    """Задание повреждено: не проходит проверку формы."""


@dataclass
class Check:
    """Одна декларативная проверка из ``acceptance``."""

    id: str
    kind: str
    weight: int
    description: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any, index: int) -> "Check":
        if not isinstance(raw, dict):
            raise TaskError(f"acceptance[{index}] — не словарь: {raw!r}")
        for key in REQUIRED_CHECKS:
            if key not in raw:
                raise TaskError(f"acceptance[{index}] — нет обязательного ключа {key!r}")
        kind = str(raw["kind"])
        args = {k: v for k, v in raw.items() if k not in ("id", "kind", "weight", "description")}
        needed = REQUIRED_ARGS.get(kind)
        if needed and not any(key in args for key in needed):
            raise TaskError(
                f"проверка {raw['id']!r} вида {kind!r} требует одно из {needed}, "
                f"а есть только {sorted(args)}"
            )
        try:
            weight = int(raw["weight"])
        except (TypeError, ValueError) as exc:
            raise TaskError(f"проверка {raw['id']!r}: вес {raw['weight']!r} не число") from exc
        if weight < 0:
            raise TaskError(f"проверка {raw['id']!r}: отрицательный вес {weight}")
        return cls(
            id=str(raw["id"]),
            kind=kind,
            weight=weight,
            description=str(raw.get("description", "")),
            args=args,
        )


@dataclass
class Task:
    """Задание целиком."""

    task_id: str
    goal: str
    checks: list[Check]
    path: Path
    source: dict[str, Any] = field(default_factory=dict)

    # --- удобные чтения необязательных блоков --------------------------

    @property
    def constraints(self) -> list[str]:
        return list(self.source.get("constraints") or [])

    @property
    def deliverables(self) -> list[str]:
        return list(self.source.get("deliverables") or [])

    @property
    def traps(self) -> list[str]:
        return list(self.source.get("traps") or [])

    @property
    def design_hint(self) -> str:
        """Бренд дизайн-системы, стиль которой надо взять за образец.

        Отдельное поле, а не элемент ref_hint: кодовый эталон показывает, как
        устроен проект, а дизайн-система — как он должен выглядеть. Смешивать
        их в одном списке нельзя, иначе агент будет искать в папке с
        описаниями исполняемый код.
        """
        raw = self.source.get("design") or self.source.get("design_hint") or ""
        if isinstance(raw, dict):
            return str(raw.get("brand") or raw.get("id") or "")
        return str(raw).strip()

    @property
    def penalties(self) -> list[dict[str, Any]]:
        return list(self.source.get("penalties") or [])

    @property
    def timeout_minutes(self) -> float:
        return float(self.source.get("timeout_minutes", 15))

    @property
    def ref_hints(self) -> list[str]:
        """Пути референсов, которые нужно подложить агенту.

        Принимаем и список (``ref_hint: [a, b]``), и словарь с ``primary`` /
        ``fallback`` — так записаны задания из плана, и молчаливый разбор
        только одного варианта приводил бы к пустой библиотеке в стенде.
        """
        raw = self.source.get("ref_hint") or self.source.get("ref_hints") or []
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, dict):
            ordered = [raw.get("primary", ""), raw.get("fallback", "")]
            return [str(p) for p in ordered if p]
        return [str(p) for p in raw if p]

    @property
    def total_weight(self) -> int:
        return sum(check.weight for check in self.checks)

    def check(self, check_id: str) -> Check:
        for item in self.checks:
            if item.id == check_id:
                return item
        raise KeyError(check_id)

    def prompt(self, ref_summary: str = "",
               design_summary: str = "") -> str:
        """Текст задания для агента.

        Собирается здесь, а не в YAML, чтобы ограничения, референсы и ловушки
        доезжали до модели в одном сообщении и в одном порядке.
        """
        parts = [self.goal.strip()]
        if self.constraints:
            lines = "\n".join(f"- {c}" for c in self.constraints)
            parts.append(f"ОГРАНИЧЕНИЯ:\n{lines}")
        if self.deliverables:
            lines = "\n".join(f"- {d}" for d in self.deliverables)
            parts.append(f"ЧТО СДАТЬ:\n{lines}")
        if design_summary:
            # Заголовок один: выжимка бренда уже несёт свой
            # «ДИЗАЙН-СИСТЕМА: …», второй такой же только сбивал с толку.
            parts.append(
                "СТИЛЬ ВЗЯТ ИЗ ДИЗАЙН-СИСТЕМЫ (это описание, не код):\n"
                + design_summary.strip()
                + "\n\nБери отсюда цвета, шрифты, радиусы, сетку и правила. "
                  "Структуру страницы (что за блоки, какой текст) — из задачи."
            )
        if ref_summary:
            parts.append(
                "БИБЛИОТЕКА ЭТАЛОНОВ:\n"
                + ref_summary.strip()
                + "\n\nЕсли подходящий эталон есть — прочитай его и адаптируй "
                  "под задачу. Писать с нули, когда готовый образец рядом, "
                  "хуже: это и время, и качество. Эталон — образец, а не "
                  "ограничение: отступай, если он не подходит."
            )
        # Ловушки идут до требования о файлах. Прямой порядок «файлы → сделай»
        # модель исполняла буквально: читала «создай index.html», отвечала
        # кодом в сообщении и объявляла задачу выполненной, не создав файла.
        if self.traps:
            lines = "\n".join(f"- {t}" for t in self.traps)
            parts.append(
                "ОТДЕЛЬНЫЕ СЛУЧАИ, на которые обрати внимание:\n"
                + lines
                + "\nЭто не новые требования и не подсказки к решению. "
                  "Улучшить результат здесь — твоя инициатива."
            )
        parts.append(
            "КАК ЭТО БУДЕТ ПРОВЕРЯТЬСЯ:\n"
            "- Задание проверяется автоматически по файлам на диске. Код в "
            "ответе не считается результатом: проверяют то, что реально "
            "записано в файлы.\n"
            "- Не выводи код в блоке ``` в ответ: вызови инструмент записи.\n"
            "- Не объявляй задачу выполненной, пока файлы не созданы."
        )
        return "\n\n".join(parts)


#: Веса проверок, которые выводятся автоматически. Сумма равна 40 — столько
#: же, сколько весит набор проверок в задании, написанном руками.
DERIVED_WEIGHTS = {
    "file_exists": 10,
    "html_has_media_query": 8,
    "html_images_have_alt": 4,
    "min_lines": 8,
    "py_compiles": 10,
}


def derive_checks(deliverables: list[str]) -> list[dict[str, Any]]:
    """Проверки, выведенные из списка сдаваемых файлов.

    Задание «сверстай лендинг, сдай index.html, style.css, script.js»
    проверяется само собой: каждый файл должен существовать, HTML — быть
    адаптивным, Python — компилироваться. Автору не нужно выписывать это,
    иначе половина естественных заданий просто не запускается.
    """
    checks: list[dict[str, Any]] = []
    number = 1

    def add(kind: str, **args: Any) -> None:
        nonlocal number
        args.setdefault("description", DERIVED_DESCRIPTIONS.get(kind, ""))
        checks.append({"id": f"D{number}", "kind": kind,
                       "weight": DERIVED_WEIGHTS.get(kind, 5), **args})
        number += 1

    for name in deliverables:
        suffix = Path(str(name)).suffix.lower()
        if suffix in (".html", ".htm"):
            add("file_exists", path=str(name))
            # alt ищется в разметке, а медиазапросы — в CSS. Раньше проверка
            # адаптива смотрела в HTML-файл и всегда падала: @media там не
            # бывает, он в таблице стилей.
            add("html_images_have_alt", glob=str(name))
        elif suffix == ".css":
            add("file_exists", path=str(name))
            add("html_has_media_query", glob=str(name))
            add("min_lines", file=str(name), lines=30)
        elif suffix in (".js", ".ts", ".mjs"):
            add("file_exists", path=str(name))
            add("min_lines", file=str(name), lines=20)
        elif suffix == ".py":
            add("file_exists", path=str(name))
            add("py_compiles", glob=str(name))
        else:
            add("file_exists", path=str(name))

    return checks


#: Пояснения к автоматическим проверкам: в отчёте видно, что именно проверяется.
DERIVED_DESCRIPTIONS = {
    "file_exists": "файл сдан",
    "html_images_have_alt": "у картинок есть alt",
    "html_has_media_query": "есть адаптив",
    "min_lines": "файл не пустой",
    "py_compiles": "python синтаксически валиден",
}


def load_task(path: Path) -> Task:
    """Прочитать задание и проверить его форму."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskError(f"{path.name}: не разбирается как YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise TaskError(f"{path.name}: ожидался словарь, получено {type(raw).__name__}")

    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise TaskError(f"{path.name}: нет обязательных ключей {missing}")

    checks_raw = raw.get("acceptance")
    if checks_raw is None:
        # Проверок нет — значит их надо вывести из deliverables. Раньше это
        # было ошибкой чтения, и самое естественное задание («сверстай
        # лендинг, сдай index.html») нельзя было даже запустить.
        checks_raw = derive_checks(raw.get("deliverables") or [])
        if not checks_raw:
            raise TaskError(
                f"{path.name}: нет ни acceptance, ни deliverables — "
                "нечего проверять и нечего сдавать"
            )
    elif isinstance(checks_raw, dict):
        # Удобная форма: acceptance: {functional: [...], quality: [...]}.
        # Разворачиваем в один список, сохраняя порядок разделов.
        flattened: list[Any] = []
        for section in ("functional", "quality", "process", "security"):
            flattened.extend(checks_raw.get(section) or [])
        if not flattened:
            raise TaskError(f"{path.name}: в acceptance нет ни одной проверки")
        checks_raw = flattened
    if not isinstance(checks_raw, list) or not checks_raw:
        raise TaskError(f"{path.name}: acceptance должен быть непустым списком")

    checks = [Check.from_dict(item, index) for index, item in enumerate(checks_raw)]

    seen: set[str] = set()
    for check in checks:
        if check.id in seen:
            raise TaskError(f"{path.name}: две проверки с id {check.id!r}")
        seen.add(check.id)

    if not any(c.weight > 0 for c in checks):
        raise TaskError(f"{path.name}: ни у одной проверки нет положительного веса")

    return Task(
        task_id=str(raw["task_id"]),
        goal=str(raw["goal"]),
        checks=checks,
        path=path,
        source=raw,
    )


def load_tasks(tasks_dir: Path) -> list[Task]:
    """Все задания из папки, по имени файла — для предсказуемого порядка."""
    tasks_dir = Path(tasks_dir)
    if not tasks_dir.is_dir():
        return []
    loaded: list[Task] = []
    for path in sorted(tasks_dir.glob("*.yaml")):
        loaded.append(load_task(path))
    return loaded