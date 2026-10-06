"""Субагенты: главный агент делит задачу и запускает части параллельно.

Зачем: одна модель уверенно делает одну страницу и с трудом делает десять.
Разбивая работу на части и выполняя их одновременно на разных моделях, мы
экономим время и обходим лимиты по аккаунтам — каждый субагент занимает свой.

Четыре требования, из-за которых модуль устроен так, а не иначе:

* **части не должны перетирать друг друга.** Каждой отдаётся свой отрезок
  файлов, а пути остальных частей кладутся в запрет. Иначе две модели
  одновременно пишут в один `style.css`, и результат зависит от того, кто
  успел последним, — то есть не зависит ни от чего.
* **видно всё.** Промты, ответы, вызовы инструментов и написанный код
  показываются в интерфейсе по каждой части. Агент, который двадцать минут
  что-то делает в молчании, выглядит сломанным, даже когда он работает.
* **часть не должна утащить за собой задачу.** Ошибка одной части не
  останавливает остальные: она просто приходит пустой, и главный агент
  решает, что с этим делать.
* **дешёво.** Разбиение — один запрос. Дальше каждая часть работает сама.
"""

from __future__ import annotations

import asyncio
import ast
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Сколько частей просим у модели. Больше шести — уже не параллельная
#: работа, а очередь: запросы выстраиваются в линию и ждут аккаунт.
MAX_PARTS = 6

#: Минимум для разбиения. Две части — это уже параллельность, одна —
#: это обычный режим с лишним запросом к модели.
MIN_PARTS = 2

#: Сколько символов промпта части показывать в интерфейсе целиком.
BRIEF_CHARS = 1200

#: Требование к разбиению. Короткое намеренно: разбиение — один запрос на
#: всю задачу, и подробная инструкция съедала бы больше, чем сама работа.
SPLIT_SYSTEM = (
    "Ты разбиваешь задачу на независимые части для нескольких агентов. "
    "Ответь ТОЛЬКО JSON, без пояснений и без блока ```json:\n"
    '{"parts": [{"title": "короткое имя", "brief": "что именно сделать", '
    '"files": ["путь/папка"]}]}\n'
    "\n"
    "Правила:\n"
    "- Частей столько, сколько реально нужно. Одна часть, если задача "
    "простая: дробить нечего.\n"
    "- Части не должны трогать одни и те же файлы. У каждой свои files.\n"
    "- files — это то, что агент создаёт или правит: папка, файл или "
    "маска вида src/*.js. Читать можно всё, писать — только своё.\n"
    "- brief — задание для агента целиком: что сделать, каким должен быть "
    "результат. Пиши как заказчик, а не как программист.\n"
    "- Не разбивай то, что дешевле сделать целиком: чтение одного файла, "
    "правку одной строки, ответ на вопрос."
)

#: Ключи, которые модель может назвать вместо ожидаемых.
_TITLE_KEYS = ("title", "name", "название", "имя", "заголовок")
_BRIEF_KEYS = ("brief", "task", "description", "prompt", "задача", "описание")
_FILES_KEYS = ("files", "paths", "path", "scope", "файлы", "пути")


@dataclass
class Part:
    """Одна часть работы."""

    title: str
    brief: str
    files: list[str] = field(default_factory=list)
    #: Имя для событий: «часть 1», «часть 2». Читаемо в журнале.
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "brief": self.brief,
                "files": list(self.files), "name": self.name or self.title}


@dataclass
class PartResult:
    """Что сделала одна часть."""

    part: Part
    ok: bool = False
    summary: str = ""
    error: str = ""
    model: str = ""
    steps: int = 0
    duration_ms: int = 0
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.part.to_dict(),
            "ok": self.ok,
            "summary": self.summary,
            "error": self.error,
            "model": self.model,
            "steps": self.steps,
            "duration_ms": self.duration_ms,
            "artifacts": list(self.artifacts),
            "tokens": self.tokens,
        }


def parse_parts(text: str, *, limit: int = MAX_PARTS) -> list[Part]:
    """Разобрать ответ модели о разбиении. Пустой список — не пригоден.

    Разбор мягкий по той же причине, что и везде: модель вставляет ```json,
    ставит запятые не везде и называет ключи по-своему. Строгий разбор отверг
    бы половину пригодных ответов, а непригодный ответ — это работа,
    сделанная одной моделью вместо нескольких.
    """
    raw = str(text or "")
    for candidate in _candidates(raw):
        data = _loads(candidate)
        if not isinstance(data, dict):
            continue
        items = data.get("parts")
        if items is None:
            items = data.get("части") or data.get("plan") or data.get("tasks")
        if not isinstance(items, list) or not items:
            continue
        parts: list[Part] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            brief = _first(item, _BRIEF_KEYS)
            if not brief:
                continue
            files = _first(item, _FILES_KEYS) or []
            if isinstance(files, str):
                files = [files]
            parts.append(Part(
                title=str(_first(item, _TITLE_KEYS) or f"часть {len(parts) + 1}"),
                brief=str(brief).strip()[:BRIEF_CHARS],
                files=[str(f).strip() for f in files if str(f).strip()],
            ))
        if parts:
            for number, part in enumerate(parts[:limit], 1):
                part.name = f"часть {number}"
            return parts[:limit]
    return []


def _candidates(text: str) -> list[str]:
    blocks = re.findall(r"```(?:json)?\s*(.+?)```", text, re.S)
    blocks.append(text.strip())
    start, end = text.find("["), text.rfind("]")
    if 0 <= start < end:
        blocks.append(text[start:end + 1])
    start, end = text.find("{"), text.rfind("}")
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


def _first(data: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


# --------------------------------------------------------------- разбиение


async def split_task(task: str, caller: Any, *, limit: int = MAX_PARTS) -> list[Part]:
    """Попросить модель разбить задачу. Пустой список — разбить не вышло."""
    try:
        result = await caller.ask(
            [{"role": "system", "content": SPLIT_SYSTEM},
             {"role": "user", "content": task}],
            temperature=0.0,
            max_tokens=1500,
        )
    except Exception:
        return []
    if result.get("error"):
        return []
    return parse_parts(str(result.get("text") or ""), limit=limit)


# --------------------------------------------------------------- блокировки


def scope_paths(files: list[str], base: Path) -> list[str]:
    """Развернуть заявленные файлы в пути для проверки границы.

    Маска `src/*.js` не является путём, но проверять её надо: иначе часть
    объявит маску и получит право писать куда угодно внутри `src/`.
    """
    out: list[str] = []
    for raw in files:
        text = str(raw or "").strip()
        if not text:
            continue
        if any(ch in text for ch in "*?"):
            # Маска: её корень и есть область записи.
            root = re.split(r"[*?]", text)[0].rstrip("\\/ ")
            if not root:
                continue
            out.append(str((base / root).resolve()))
            continue
        try:
            out.append(str((base / text).resolve()))
        except (OSError, ValueError):
            continue
    return out


def denied_for(part: Part, parts: list[Part], base: Path) -> list[str]:
    """Пути, которые часть не имеет права трогать: области остальных."""
    mine = set(scope_paths(part.files, base))
    denied: list[str] = []
    for other in parts:
        if other is part:
            continue
        for path in scope_paths(other.files, base):
            if path in mine:
                # Области пересеклись: это ошибка модели, а не повод
                # отдать обеим. Общую часть оставляем обеим — пересечение
                # разбирает главный агент, у которого есть все результаты.
                continue
            denied.append(path)
    return list(dict.fromkeys(denied))


def denied_globs_for(part: Part, parts: list[Part]) -> list[str]:
    """Маски, которые часть не имеет права трогать.

    Отдельно от обычных путей, потому что маску нельзя свести к папке.
    Часть со стилями объявляет `assets/*.css`, а часть со скриптами —
    `assets/app.js`. Если маску развернуть в папку `assets`, то вторая
    часть получит запрет на собственную работу: её файл лежит внутри
    запрещённой папки. Маска должна запрещать ровно то, что описала.
    """
    mine = {str(f).strip().lower().replace("\\", "/") for f in part.files}
    globs: list[str] = []
    for other in parts:
        if other is part:
            continue
        for raw in other.files:
            text = str(raw or "").strip().replace("\\", "/").lower()
            if not text or any(ch in text for ch in "*?") is False:
                continue
            if text in mine:
                continue
            globs.append(text)
    return list(dict.fromkeys(globs))


# ----------------------------------------------------------------- запуск


def denied_for_all(parts: list[Part], base: Path) -> list[list[str]]:
    """Запреты для каждой части. Индексы совпадают с индексом в parts."""
    return [denied_for(part, parts, base) for part in parts]


def globs_for_all(parts: list[Part]) -> list[list[str]]:
    """Маски в запрете для каждой части. Индексы совпадают с parts."""
    return [denied_globs_for(part, parts) for part in parts]


async def run_parts(
    parts: list[Part],
    *,
    base: Path,
    make_agent: Any,
    on_event: Any = None,
    limit: int = MAX_PARTS,
    task_context: str = "",
) -> list[PartResult]:
    """Запустить части параллельно и собрать результаты.

    `make_agent(part) -> Agent` — фабрика: у каждой части свой агент со своим
    набором запретов. Фабрикой, а не готовым агентом, потому что все части
    должны быть разными объектами с общим состоянием селектора.

    Часть, которая упала, не роняет остальные: её результат приходит с
    `ok=False` и текстом ошибки, а главный агент решает, что с этим делать.
    """
    results: list[PartResult] = [PartResult(part=part) for part in parts]
    if not parts:
        return results

    semaphore = asyncio.Semaphore(max(1, min(limit, len(parts))))
    started = time.perf_counter()

    async def one(index: int, part: Part) -> None:
        async with semaphore:
            slot = results[index]
            started_at = time.perf_counter()
            if on_event:
                await on_event({"type": "part_started", "sub": part.name,
                                "part": slot.to_dict()})
            try:
                agent = make_agent(part)
                agent.part = part.name
                agent.trace_on = True
                # Задание части — это исходная задача целиком плюс
                # конкретный заказ. Без исходной задачи агент не знает, что
                # он делает часть общей работы, и выдаёт узкий кусок,
                # не согласующийся с остальными.
                task = (task_context + "\n\n" + part.brief) if task_context \
                    else part.brief
                agent.set_task(task)
                outcome = await agent.run()
                slot.ok = bool(outcome.get("ok"))
                slot.summary = str(outcome.get("last") or "")[:2000]
                slot.error = str(outcome.get("error") or "")
                slot.model = ", ".join(outcome.get("models_used") or [])
                slot.steps = int(outcome.get("steps") or 0)
                slot.tokens = int(outcome.get("tokens") or 0)
                slot.artifacts = list(outcome.get("artifacts") or [])
                slot.trace = list(outcome.get("trace") or [])
            except Exception as exc:  # noqa: BLE001
                # Одна часть не должна утащить за собой остальные. Ошибка
                # попадает в её результат, а главный агент увидит её в
                # сводке и решит, доделывать самому или спросить человека.
                slot.ok = False
                slot.error = f"{type(exc).__name__}: {exc}"
            finally:
                slot.duration_ms = int((time.perf_counter() - started_at) * 1000)
            if on_event:
                await on_event({"type": "part_done", "sub": part.name,
                                "part": slot.to_dict(),
                                "elapsed_ms": int((time.perf_counter() - started) * 1000)})

    await asyncio.gather(*(one(i, part) for i, part in enumerate(parts)))
    return results


# ------------------------------------------------------------------ сводка


def summary_for(results: list[PartResult], base: Path) -> str:
    """Текст для главного агента: что сделала каждая часть.

    Пишется в промпт главного агента целиком. Скрывать от него результаты
    частей бессмысленно: без них он не сможет ни собрать результат, ни
    честно сказать, что не получилось.
    """
    lines: list[str] = []
    for slot in results:
        head = f"### {slot.part.name}: {slot.part.title}"
        if not slot.ok:
            lines.append(head + "\nНЕ ВЫПОЛНЕНО: " + (slot.error or "без причины"))
            continue
        body = slot.summary.strip() or "(агент не описал результат)"
        lines.append(head + "\n" + body[:2000])
        files = [str(a.get("path")) for a in slot.artifacts if a.get("path")]
        if files:
            lines.append("Создано: " + ", ".join(files[:20]))
    return "\n\n".join(lines)


#: Что показывать человеку про часть: её собственный след целиком.
def part_brief_for_ui(slot: PartResult) -> dict[str, Any]:
    """Готовая карточка части для интерфейса."""
    data = slot.to_dict()
    data["trail"] = [
        {
            "n": item.get("n"),
            "tool": item.get("tool"),
            "args": item.get("args"),
            "result": item.get("result"),
            "sent": item.get("sent"),
            "got": item.get("got"),
        }
        for item in slot.trace[-40:]
    ]
    return data