"""Ядро агента: цикл «задача → план → шаги → результат» с переключением моделей.

Автономия и связка с пользователем:

    автономный режим   агент сам решает, пока не выполнит задачу или не упрётся
    режим questions    агент без остановки советуется с другими моделями
    связка с человеком  агент распознаёт, что не справляется, и спрашивает

Переключение моделей: каждый запрос идёт через AutoCaller, который при отказе
текущей модели берёт следующую по приоритету. Агент не знает, какая модель
ответит, — это и есть режим auto.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from hub.autonomy import AccessLevel, Autonomy, Escalation, Guard
from hub.failover import AutoCaller, FailoverError
from hub.keyring import gateway_key
from hub.select import Mode, Selector
from hub.tiers import TierBook
from hub.tools import (
    ToolResult,
    browser_url,
    run_tool,
    tool_arg_names,
    tool_catalog_for_prompt,
)

#: Разделитель системного промпта.
SYSTEM_HEADER = "Ты — автономный агент для работы с файлами."

#: Пример вызова инструмента, который показывается модели в промпте.
TOOL_CALL_EXAMPLE = '{"tool": "read_file", "args": {"path": "src/main.py"}}'

#: Абсолютный путь в тексте модели: «C:\Users\...\file.txt» или «C:/Users/...».
#: Ищем, чтобы понять, о каком именно файле агент говорит, когда сам
#: отказывается работать.
_PATH_IN_TEXT = re.compile(r"[A-Za-z]:[\\/][^\s\"'`|<>,\)\]]+")

#: Признаки того, что модель упёрлась в границу воркспейса и отказалась
#: действовать, вместо того чтобы вызвать инструмент. Без этого блока агент
#: пишет «мне нужен доступ к C:\...», но запрос в интерфейсе не появляется:
#: система спрашивает только когда инструмент реально вызвали.
_BOUNDARY_BLOCK_MARKERS = (
    "нужен доступ",
    "нужно разрешение",
    "нужны разрешения",
    "требуется доступ",
    "требуется разрешение",
    "запросить разрешение",
    "спросить разрешение",
    "не могу изменить",
    "не могу записать",
    "не могу получить доступ",
    "не могу работать с",
    "не получилось изменить",
    "не удалось изменить",
    "не удалось получить доступ",
    "вне рабочей директории",
    "за пределами рабочей",
    "вне воркспейса",
    "за пределами воркспейса",
    "outside the working directory",
    "outside the workspace",
    "need permission",
    "needs permission",
    "need access",
    "requires permission",
    "require permission",
)

#: Сколько раз можно повторить агенту требование «вызови инструмент»,
#: прежде чем попросить пользователя. Две попытки: первая обычно исправляет
#: поведение, вторая нужна упрямым моделям.
MAX_BOUNDARY_NUDGES = 2


def mentions_boundary_block(text: str) -> bool:
    """Модель говорит, что упёрлась в границу, вместо вызова инструмента."""
    low = str(text or "").lower().replace("ё", "е")
    return any(marker in low for marker in _BOUNDARY_BLOCK_MARKERS)


def _outside_root(path: Path, base: str) -> bool:
    """Путь не внутри base (сравнение по компонентам, а не по префиксу)."""
    target = str(path).replace("\\", "/").rstrip("/").lower()
    root = base.replace("\\", "/").rstrip("/").lower()
    return not (target == root or target.startswith(root + "/"))


def paths_outside(text: str, root: str | Path | None) -> list[str]:
    """Абсолютные пути из текста модели, которые лежат вне папки root.

    Нужны, чтобы превратить слова «нужен доступ к C:\\... » в настоящий
    запрос разрешения с конкретным путём, а не в тишину.
    """
    if not root:
        return []
    try:
        base = str(Path(root).expanduser().resolve())
    except (OSError, RuntimeError):
        return []
    found: list[str] = []
    for match in _PATH_IN_TEXT.finditer(str(text or "")):
        raw = match.group(0).rstrip(".,;:!?)]}\"'")
        try:
            resolved = Path(raw).resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if _outside_root(resolved, base):
            found.append(str(resolved))
    return found


class Phase(str, Enum):
    """Стадия цикла агента."""

    IDLE = "idle"
    THINKING = "thinking"
    USING_TOOL = "tool"
    ASKING_USER = "asking"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Step:
    """Один шаг цикла."""

    index: int
    phase: str
    text: str
    model: str | None = None
    tool: str | None = None
    duration_ms: int = 0
    ok: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "phase": self.phase,
            "text": self.text,
            "model": self.model,
            "tool": self.tool,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "error": self.error,
        }


@dataclass
class AgentConfig:
    """Настройки агента."""

    access: AccessLevel = AccessLevel.WRITE
    autonomy: Autonomy = Autonomy.NORMAL
    escalation: Escalation = Escalation.AUTO
    base_dir: str = "."
    max_steps: int = 40
    step_timeout: float = 120.0
    question_rounds: int = 3          # для режима questions
    require_vision: bool = False       # для задач со скриншотами
    max_tokens: int = 4096
    temperature: float = 0.2
    #: Бюджет токенов на задачу. 0 — не ограничен (бесплатные квоты малы,
    #: поэтому предупреждение полезнее, чем жёсткий обрыв).
    token_budget: int = 60_000
    #: Проверять ли записанное после write_file / edit_file.
    verify_writes: bool = True
    #: Запускать тесты проекта после записи, если он на Python.
    run_project_tests: bool = False
    #: Максимум сообщений в промпте: история обрезается по необходимости.
    max_history: int = 24

    def to_dict(self) -> dict[str, Any]:
        return {
            "access": int(self.access),
            "autonomy": self.autonomy.value,
            "escalation": self.escalation.value,
            "base_dir": self.base_dir,
            "max_steps": self.max_steps,
            "question_rounds": self.question_rounds,
            "require_vision": self.require_vision,
            "token_budget": self.token_budget,
            "verify_writes": self.verify_writes,
            "run_project_tests": self.run_project_tests,
        }


#: Блок ```json ... ``` в ответе модели.
_FENCE_RE = re.compile(r"```(?:json|tool|javascript)?\s*(.+?)```", re.S | re.I)


def _scan_json_objects(text: str) -> list[str]:
    """Найти в тексте все JSON-объекты верхнего уровня по балансу скобок.

    Регулярное выражение здесь не годится: модели часто вставляют внутрь args
    многострочные строки с фигурными скобками и вложенные объекты, и ленивый
    квантификатор обрывается на первой же внутренней скобке.
    """
    found: list[str] = []
    index = 0
    length = len(text)

    while index < length:
        if text[index] != "{":
            index += 1
            continue

        depth = 0
        in_string = False
        quote = ""
        escaped = False
        cursor = index

        while cursor < length:
            char = text[cursor]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    in_string = False
            else:
                if char in ('"', "'"):
                    in_string = True
                    quote = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        found.append(text[index : cursor + 1])
                        index = cursor + 1
                        break
            cursor += 1
        else:
            # Скобки не закрылись — это не JSON, идём дальше с текущего места.
            index += 1
            continue

    return found


#: Как выглядит почти-вызов инструмента. Модели пишут его регулярно: с
#: одинарными кавычками, по-питоновски или с висячей запятой. Такой текст
#: раньше молча превращался в «вызовов нет», задача завершалась как успешная,
#: и агент не сделал ровно ничего.
_LOOSE_CALL = re.compile(
    r"['\"]tool['\"]\s*[:=]\s*['\"](\w+)['\"]",
    re.IGNORECASE,
)

#: Метка порядка байтов: файлы, записанные в Windows, начинаются с неё, и она
#: не является содержимым. ast.parse и json считают её ошибкой.
BOM = "\ufeff"

#: Сколько раз подряд можно вернуть модели требование строгого формата.
#: Больше — она не поймёт, и задача зависнет; значит, пора честно остановиться.
FORMAT_NUDGE_LIMIT = 2

#: Сколько записей в следе работы агента. След нужен для разбора того, что
#: пошло не так, а не для архива: двадцати последних достаточно, а полная
#: история на пятидесятом шаге — это мегабайты текста в браузере.
TRACE_LIMIT = 120


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    """Достать JSON-вызовы инструментов из ответа модели.

    Обрабатываются: блок ```json, голый JSON и одиночный объект. Внутри args
    допускаются вложенные объекты и многострочные строки.
    """
    return _parse_calls(text)[0]


def looks_like_tool_call(text: str) -> bool:
    """Похоже ли, что модель хотела вызвать инструмент, но формат испортила."""
    if not text:
        return False
    return bool(_LOOSE_CALL.search(text))


def _parse_calls(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Вызовы инструментов и список испорченных фрагментов.

    Второе значение нужно, чтобы отличать «модель ответила словами» от
    «модель ответила почти-вызовом». Разница огромна: в первом случае ответ
    завершает задачу, во втором надо вернуть модели требование формата.
    """
    if not text:
        return [], []

    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    broken: list[str] = []

    for candidate in _scan_json_objects(text):
        parsed, error = _safe_loads(candidate)
        if error:
            broken.append(error)
            continue
        for call in parsed:
            # Модель может повторить один и тот же вызов в тексте и в блоке.
            fingerprint = f"{call['tool']}:{json.dumps(call['args'], sort_keys=True, ensure_ascii=False)}"
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            calls.append(call)

    return calls, broken


def _safe_loads(raw: str) -> tuple[list[dict[str, Any]], str]:
    """Разобрать один JSON-фрагмент.

    Возвращает вызовы и описание ошибки. Пустое описание — разобралось.
    Ошибка нужна вызывающему, чтобы отличить испорченный формат от обычного
    текста: раньше оба случая выглядели одинаково — как «вызовов нет».
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Питоновский словарь — самая частая форма поломки, и она лечится
        # простым разбором литерала.
        repaired = _try_python_literal(raw)
        if repaired is not None:
            data, error = repaired, ""
        else:
            return [], _json_error(raw, exc)
    else:
        error = ""

    if isinstance(data, dict) and data.get("tool"):
        args = data.get("args")
        if not isinstance(args, dict):
            args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        return [{"tool": str(data["tool"]), "args": args}], error

    if isinstance(data, list):
        calls = []
        for item in data:
            if not isinstance(item, dict) or not item.get("tool"):
                continue
            args = item.get("args")
            if not isinstance(args, dict):
                args = {}
            calls.append({"tool": str(item["tool"]), "args": args})
        return calls, error
    return [], error


def _try_python_literal(raw: str) -> Any:
    """Разобрать фрагмент как Python-литерал.

    Модели регулярно пишут `{'tool': 'read_file', 'args': {...}}` — с
    одинарными кавычками и без JSON-кавычек. Для человека это тот же JSON,
    и ``ast.literal_eval`` берёт его без всякого исполнения кода: он разбирает
    только литералы. Ничего небезопасного тут быть не может.
    """
    # Одинарные кавычки — главная причина провала json.loads. Приводим их к
    # двойным, но только снаружи строк: внутри неё одинарная кавычка может быть
    # частью содержимого.
    patched = _single_to_double_quotes(raw)
    for candidate in (raw, patched):
        try:
            return ast.literal_eval(candidate)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
    return None


def _single_to_double_quotes(raw: str) -> str:
    """Заменить одинарные кавычки строк на двойные, не трогая содержимое.

    Одинарная строка ``{'a': 'don\\'t'}`` превращается в ``{"a": "don't"}``:
    экранированный апостроф внутри становится обычным символом, потому что
    внутри двойных кавычек экранировать его не надо. Замена границ строк
    обязательна с обеих сторон — иначе результат перестаёт быть JSON.
    """
    out: list[str] = []
    in_string = False
    escaped = False

    for char in raw:
        if escaped:
            # Обратный слэш перед апострофом убираем: внутри двойных кавычек
            # экранировать его не нужно, а ``\'`` для JSON — недопустимая
            # последовательность. Остальные экранирования сохраняем как есть.
            if char != "'":
                out.append("\\")
            out.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'":
            # Граница строки: одинарная превращается в двойную.
            in_string = not in_string
            out.append('"')
            continue
        if char == '"':
            # Двойная кавычка внутри одинарной строки — обычный символ,
            # её нужно экранировать, иначе JSON развалится.
            out.append('\\"' if in_string else '"')
            continue
        out.append(char)
    return "".join(out)


def _json_error(raw: str, exc: json.JSONDecodeError) -> str:
    """Человеческое описание того, что не так с фрагментом."""
    snippet = " ".join(raw.split())[:120]
    return f"{exc.msg} в позиции {exc.pos}: {snippet}"


def build_system_prompt(guard: Guard, config: AgentConfig, *, workspace: str,
                        self_edit: bool = False, web_research: bool = False) -> str:
    """Системный промпт агента."""
    parts = [
        SYSTEM_HEADER,
        f"Рабочая директория: {workspace}",
        f"Уровень доступа: {guard.access.label}.",
        f"Режим автономии: {guard.autonomy.label}.",
    ]

    if guard.autonomy is Autonomy.PLAN:
        parts.append(
            "Сначала составь план: перечисли файлы, которые создашь или изменишь, "
            "и объясни зачем. Не начинай правки до одобрения плана."
        )
    else:
        parts.append("Работай итеративно: читай нужные файлы, вноси правки, проверяй результат.")

    parts.append(
        "\n".join([
            "",
            "Правила:",
            "- Чтобы вызвать инструмент, ответь ТОЛЬКО JSON в блоке ```json: "
            + TOOL_CALL_EXAMPLE + " — и больше ничего.",
            "- Пути указывай относительно рабочей директории, например "
            "tests/test_probe.py, а не абсолютный путь через C:.",
            "- Шаг за шагом: сначала прочитай нужные файлы, потом правь. "
            "Не выдумывай содержимое файлов.",
            "- Правь минимально, сохраняй стиль файла.",
            "- Когда задача выполнена — ответь словами, без JSON.",
            "- Если задача невыполнима без вмешательства человека (вход в аккаунт, "
            "капча, закрытый доступ) — задай короткий вопрос и остановись.",
        ])
    )

    if guard.escalation is Escalation.OFF:
        parts.append("\nТы не можешь спрашивать пользователя. Решай сам или сообщи о неудаче.")
    elif guard.escalation is Escalation.AUTO:
        parts.append("\nСпрашивай пользователя только когда иначе невозможно.")
    else:
        parts.append("\nСомневаешься — спрашивай пользователя.")

    # Граница воркспейса. Без этого блока модель заранее отказывается
    # работать с путём снаружи и не доходит до запроса разрешения.
    if guard.workspace_root and guard.access is AccessLevel.FULL and guard.soft_boundary:
        parts.append(
            "\n".join([
                "",
                "Граница рабочей директории:",
                f"- У тебя полный доступ, поэтому за пределами {guard.workspace_root} "
                "ты можешь работать без спроса.",
                "- Не отказывайся из-за того, что путь снаружи, и не переноси "
                "файлы внутрь: просто работай по нужному пути.",
            ])
        )
    elif guard.workspace_root and guard.soft_boundary:
        parts.append(
            "\n".join([
                "",
                "Граница рабочей директории:",
                f"- За пределами {guard.workspace_root} писать нельзя без спроса. "
                "Но иногда задача требует именно этого (соседний проект, файл "
                "рядом, общая папка).",
                "- В таком случае НЕ отказывай сразу и не переноси файл внутрь. "
                "Просто вызови инструмент с этим путём: система сама спросит "
                "у пользователя разрешение и покажет окно с кнопками.",
                "- Если пользователь разрешит — операция выполнится, "
                "ответ в диалоге подтвердит это, и ты продолжишь ту же задачу.",
                "- Если откажет — получишь сообщение об отказе. Тогда ищи способ "
                "обойтись без этого пути и скажи пользователю, что не вышло.",
            ])
        )
    elif guard.workspace_root:
        parts.append(
            f"\nРаботай только внутри {guard.workspace_root}. Файлы за его "
            "пределами недоступны, не пытайся к ним обращаться."
        )

    if self_edit:
        # Режим разработки. Отдельным блоком и явно: в обычном режиме модель
        # не должна даже думать о правке кода программы, в которой сама
        # работает, — иначе она начинает «улучшать» соседние файлы по пути.
        parts.append(
            "\n".join([
                "",
                "РЕЖИМ РАЗРАБОТКИ САМОГО СОФТА:",
                f"- Ты работаешь в исходниках zagent ({workspace}). Это код "
                "программы, внутри которой ты сейчас запущен, и её правка "
                "влияет на следующий запуск.",
                "- Меняй только то, что относится к задаче. Не приводи в "
                "порядок соседние файлы, не переименовывай то, о чём не "
                "просили, не меняй публичные имена без нужды.",
                "- Перед правкой прочитай файл целиком и найди, где именно "
                "живёт нужное поведение.",
                "- После правки проверь результат: тесты — "
                "`.venv\\Scripts\\python.exe -m pytest -q`, интерфейс — "
                "`.venv\\Scripts\\python.exe tools\\check_ui.py`. Обе команды "
                "должны быть зелёными.",
                "- В конце напиши, что именно изменилось и почему, и "
                "предупреди, если правка требует перезапуска.",
            ])
        )

    if web_research:
        # Блок объясняет порядок работы, а не перечисляет инструменты: без
        # него модель ищет один раз, берёт первый заголовок из выдачи и
        # пишет ответ по памяти. Ссылки в отчёте без чтения страниц —
        # это ровно тот обман, которого мы хотели избежать.
        parts.append(
            "\n".join([
                "",
                "ВЕБ-РАЗВЕДКА:",
                "- Про то, что вышло после твоей подготовки, ты не знаешь. "
                "Отвечай по памяти только если уверен, что тема не менялась.",
                "- Найдено — ещё не прочитано. Прежде чем писать в ответ, "
                "открой найденные ссылки через web_fetch и опирайся на их текст.",
                "- В конце укажи источники: адрес страницы рядом с тем, "
                "что из неё взято.",
                "- Страница отдаёт около 4000 символов. Не хватило — ищи "
                "другие источники или читай по ссылкам дальше.",
                "- Если сайт не открылся (закрыт для ботов, требует входа), "
                "не выдумывай его содержимое. Скажи об этом и возьми другой "
                "источник.",
                "- Внутренние адреса (localhost, 127.0.0.1, адреса сети) "
                "инструменты не читают — это не ошибка, так и задумано.",
            ])
        )

    parts.append("\n" + tool_catalog_for_prompt(guard, web=web_research))
    return "\n".join(parts)


class Agent:
    """Агент: держит состояние, выполняет шаги, переключает модели."""

    def __init__(
        self,
        selector: Selector,
        guard: Guard,
        config: AgentConfig | None = None,
        *,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
        caller: Any | None = None,
    ) -> None:
        self.selector = selector
        self.guard = guard
        self.config = config or AgentConfig()
        self.on_event = on_event
        # caller можно подставить: стенду и тестам нужен предсказуемый ответ
        # модели, а реальный AutoCaller ходит в сеть.
        self.caller = caller or AutoCaller(
            selector,
            timeout=self.config.step_timeout,
            # Провайдеры часто отдают пустой content на reasoning-моделях и
            # жёстко ограничивают длину промпта. Больший запас токенов на ответ
            # и повтор при пустом ответе — то, что отличает «работает» от «молчит».
            empty_retries=2,
        )

        self.workspace = Path(self.config.base_dir).resolve()
        self.messages: list[dict[str, Any]] = []
        self.steps: list[Step] = []
        self.phase = Phase.IDLE
        self.pending_question: str | None = None
        self.plan: str | None = None
        self.plan_approved = False
        self.finished = False
        #: Диалог для восстановления после падения или вопроса пользователя.
        self.checkpoint: dict[str, Any] = {}
        #: Ожидающий запрос на выход за границу воркспейса (None — не ждём).
        self.pending_permission: dict[str, Any] | None = None
        #: Сколько раз мы требовали от модели вызвать инструмент вместо отказа.
        self.boundary_nudges: int = 0
        #: Сколько раз возвращали модели требование формата вызова.
        self.format_retries: int = 0
        #: Учёт токенов по задаче: {"tokens": int, "warnings": list[str]}
        self.step_budget: dict[str, Any] = {"tokens": 0, "warnings": []}
        #: Проверки после записи: {"path": str, "ok": bool, "detail": str}
        self.verifications: list[dict[str, Any]] = []
        #: Что агент создал за задачу: пути относительно рабочей директории.
        #: Нужны, чтобы в ответе показать готовые ссылки, а не просто текст
        #: с путями, по которым ещё надо куда-то идти.
        self.artifacts: list[dict[str, Any]] = []
        #: Правка собственного кода zagent. По умолчанию выключено: агент
        #: работает с результатом работы, а не с программой, которая его
        #: запускает. Включается вручную на одну задачу.
        self.self_edit = False
        #: Веб-ресёрч: поиск и чтение страниц. Живёт в задаче, а не в
        #: настройках, потому что это решение человека под конкретный вопрос.
        self.web_research = False
        #: На сколько частей дробить задачу. 0 — работаем целиком одни.
        self.subagents = 0
        #: След работы: что уходило модели и что она отвечала. Пустой список
        #: выключает запись — обычная задача не должна платить за то, что
        #: её никто не смотрит.
        self.trace: list[dict[str, Any]] = []
        self.trace_on = False
        #: Имя части, если это субагент. Попадает во все события, чтобы
        #: интерфейс знал, чей это шаг и чей вызов инструмента.
        self.part: str = ""
        self._prompt_rebuilt = False

    # ------------------------------------------------------------- события

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        result = self.on_event(event)
        if asyncio.iscoroutine(result):
            await result

    async def _step(self, phase: Phase, text: str, **kw: Any) -> Step:
        step = Step(index=len(self.steps) + 1, phase=phase.value, text=text, **kw)
        self.steps.append(step)
        # `sub` во всех шагах: по журналу должно быть видно, чей это шаг.
        # Без этого шаги субагента и главного агента неразличимы, а они
        # выполняются одновременно.
        await self._emit({"type": "step", "step": step.to_dict(), "sub": self.part})
        return step

    # -------------------------------------------------------------- запуск

    def set_task(self, task: str) -> None:
        """Поставить задачу и сбросить состояние цикла."""
        self.messages = [
            {"role": "system", "content": build_system_prompt(
                self.guard, self.config, workspace=str(self.workspace),
                self_edit=self.self_edit,
                web_research=self.web_research,
            )},
            {"role": "user", "content": task},
        ]
        self.checkpoint = {
            "messages": [dict(m) for m in self.messages],
            "step": 0,
        }
        self._reset_cycle()

    def rebuild_system_prompt(self) -> None:
        """Пересобрать системный промпт под текущий режим.

        Нужно, когда режим включается после постановки задачи: воркер создаёт
        агента и вызывает set_task, а флаг правки своего кода ставит следом.
        Без пересборки модель работала бы в обычном режиме, молча считая
        правку кода запрещённой.
        """
        if not self.messages or self.messages[0].get("role") != "system":
            return
        self.messages[0] = {
            "role": "system",
            "content": build_system_prompt(
                self.guard, self.config, workspace=str(self.workspace),
                self_edit=self.self_edit,
                web_research=self.web_research,
            ),
        }

    def _reset_cycle(self) -> None:
        self.steps = []
        self.phase = Phase.IDLE
        self.pending_question = None
        self.pending_permission = None
        self.boundary_nudges = 0
        self.format_retries = 0
        self.plan = None
        self.plan_approved = False
        self.finished = False
        self.step_budget = {"tokens": 0, "warnings": []}
        # Проверки относятся к текущему циклу: оставшиеся от прошлого прохода
        # значения делали одну плохую запись причиной провала всей задачи.
        self.verifications = []
        self.artifacts = []

    # ------------------------------------------------------------ чекпоинты

    def save_checkpoint(self) -> None:
        """Сохранить диалог и позицию цикла.

        Нужно, чтобы задачу можно было продолжить после падения или после
        вопроса пользователя: агент не начинает с нуля, а берёт контекст.
        """
        self.checkpoint = {
            "messages": [dict(m) for m in self.messages],
            "step": len(self.steps),
            "plan": self.plan,
            "plan_approved": self.plan_approved,
            # Неотвеченный вопрос — часть состояния, а не временная метка.
            # Без него восстановление теряло вопрос, и answer_question()
            # выходил сразу: пользователь отвечал, а ответ никуда не попадал.
            "pending_question": self.pending_question,
        }

    def restore_checkpoint(self, data: dict[str, Any]) -> bool:
        """Восстановить диалог из чекпоинта. False — если он непригоден."""
        if not isinstance(data, dict):
            return False
        messages = data.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            return False

        self.messages = [dict(m) for m in messages]
        self.plan = data.get("plan")
        self.plan_approved = bool(data.get("plan_approved"))
        self._reset_cycle()
        self.plan = data.get("plan")
        self.plan_approved = bool(data.get("plan_approved"))
        # Вопрос восстанавливается после сброса цикла: _reset_cycle()
        # обнуляет его, и ответ пользователя впоследствии просто игнорировался.
        # Значение может быть None — так и должно быть, если вопроса не было.
        pending = data.get("pending_question")
        self.pending_question = pending if isinstance(pending, str) and pending else None
        return True

    def answer_question(self, answer: str) -> None:
        """Ответ пользователя на вопрос агента."""
        if self.pending_question is None:
            return
        self.messages.append({
            "role": "user",
            "content": f"Ответ пользователя: {answer}\nПродолжай работу над задачей.",
        })
        self.pending_question = None

    async def _retry_format(self, raw: str, broken: list[str],
                            model: str | None, duration: int) -> str:
        """Вернуть модели требование строгого формата вызова инструмента.

        Раньше такой ответ считался финальным текстом: агент писал в журнал
        `done`, задача завершалась успехом, и по журналу казалось, что работа
        сделана. На деле не был прочитан ни один файл и не записан ни один.

        Повторов ограничено намеренно: если модель второй раз отвечает тем же,
        разбираться с её форматом бессмысленно — честнее остановиться и сказать
        об этом в ошибке, чем крутить цикл до лимита шагов.
        """
        self.format_retries += 1
        if self.format_retries > FORMAT_NUDGE_LIMIT:
            await self._step(
                Phase.THINKING,
                "Модель не смогла вызвать инструмент в нужном формате",
                model=model, duration_ms=duration, ok=False,
                error="неверный формат вызова инструмента",
            )
            self.finished = False
            await self._emit({
                "type": "failed",
                "reason": (
                    "Модель ответила вызовом инструмента, но не в JSON. "
                    "Требование формата повторялось — не помогло."
                ),
                "model": model,
            })
            return "stop"

        detail = ""
        if broken:
            detail = " Что именно не разобралось: " + broken[0][:200]
        await self._step(
            Phase.THINKING,
            f"Формат вызова неверен, требую JSON ещё раз (попытка "
            f"{self.format_retries} из {FORMAT_NUDGE_LIMIT + 1}){detail}",
            model=model, duration_ms=duration, ok=False,
            error="неверный формат вызова инструмента",
        )
        self.messages.append({"role": "assistant", "content": raw})
        self.messages.append({
            "role": "user",
            "content": (
                "Вызов инструмента не распознан. Повтори ровно в этом формате, "
                "без пояснений вокруг:\n" + TOOL_CALL_EXAMPLE + "\n"
                "Ключи в двойных кавычках, после последнего поля запятая не "
                "ставится, ничего кроме JSON не пиши."
            ),
        })
        return "continue"

    async def run(self, task: str | None = None) -> dict[str, Any]:
        """Прогнать цикл до завершения, отказа или лимита шагов."""
        if task is not None:
            self.set_task(task)
        elif not self.messages:
            return {"ok": False, "error": "Нет задачи"}

        started = time.perf_counter()
        self.phase = Phase.THINKING
        cancelled = False

        while len(self.steps) < self.config.max_steps and not self.finished:
            if self.should_cancel():
                cancelled = True
                break
            if self.guard.autonomy is Autonomy.PLAN and not self.plan_approved:
                result = await self._make_plan(started)
                self.save_checkpoint()
                return result

            outcome = await self._one_step()
            self.save_checkpoint()
            if outcome == "stop":
                break

        elapsed = int((time.perf_counter() - started) * 1000)
        if cancelled:
            self.phase = Phase.FAILED
        else:
            self.phase = Phase.DONE if self.finished else Phase.FAILED

        return {
            "ok": self.finished and not cancelled,
            "phase": self.phase.value,
            "steps": len(self.steps),
            "duration_ms": elapsed,
            "models_used": sorted({s.model for s in self.steps if s.model}),
            "pending_question": self.pending_question,
            "pending_permission": self.pending_permission,
            "last": self.steps[-1].text if self.steps else "",
            "cancelled": cancelled,
            "tokens": self.step_budget.get("tokens", 0),
            "budget_warnings": self.step_budget.get("warnings", []),
            "verifications": list(self.verifications),
            "checkpoint": self.checkpoint,
            "selector": self.selector.stats(),
            # След работы и созданное — субагенту это нужно отдать главному
            # агенту, а человеку — показать в интерфейсе.
            "trace": list(self.trace),
            "artifacts": list(self.artifacts),
            "part": self.part,
        }

    def should_cancel(self) -> bool:
        """Проверить флаг отмены. Воркер выставляет его между шагами."""
        return bool(getattr(self, "cancel_requested", False))

    def request_cancel(self) -> None:
        self.cancel_requested = True

    async def _make_plan(self, started: float) -> dict[str, Any]:
        """Режим plan: показать план и дождаться одобрения."""
        self.messages.append({
            "role": "user",
            "content": "Составь план действий. Ничего не выполняй, только перечисли шаги.",
        })
        result = await self._complete()
        if result.get("error"):
            self.phase = Phase.FAILED
            return {"ok": False, "error": result["error"]}

        self.plan = result["text"]
        self.messages.append({"role": "assistant", "content": self.plan})
        self.phase = Phase.ASKING_USER
        self.pending_question = "План готов. Выполнять?"
        await self._step(Phase.THINKING, self.plan, model=result.get("model"),
                         duration_ms=result.get("duration_ms", 0))
        await self._emit({"type": "plan", "plan": self.plan})

        return {
            "ok": False,
            "phase": Phase.ASKING_USER.value,
            "pending_question": self.pending_question,
            "plan": self.plan,
            "steps": len(self.steps),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "selector": self.selector.stats(),
        }

    def approve_plan(self) -> None:
        self.plan_approved = True
        self.pending_question = None
        self.messages.append({"role": "user", "content": "План одобрен. Выполняй."})

    # ---------------------------------------------------------------- шаг

    async def _handle_boundary_refusal(self, text: str) -> bool:
        """Модель сказала, что ей нужен доступ наружу, но ничего не сделала.

        Возвращает True, если ситуация обработана: либо мы потребовали от
        модели вызвать инструмент (и цикл продолжается), либо подняли запрос
        разрешения сами, и агент ждёт ответа пользователя.
        """
        guard = self.guard
        # При полном доступе вопросов быть не должно вовсе, при жёсткой границе
        # — и подавно. Проверяем, чтобы не чинить невозможное.
        if guard.access is AccessLevel.FULL or not guard.soft_boundary:
            return False
        if not guard.workspace_root:
            return False
        if not mentions_boundary_block(text):
            return False

        outside = paths_outside(text, guard.workspace_root)
        if not outside:
            # Отказ без конкретного пути: попросить нечего. Модель сама
            # выдумала причину или имеет в виду что-то другое.
            return False

        path = outside[0]

        if self.boundary_nudges < MAX_BOUNDARY_NUDGES:
            self.boundary_nudges += 1
            self.messages.append({
                "role": "user",
                "content": (
                    "Ты ответил словами, но инструмент не вызвал, поэтому "
                    "система не знает, о чём просить пользователя. "
                    f"Сделай ровно то, о чём говоришь: вызови инструмент с "
                    f"путём {path}. Доступ за его пределами запрашивается "
                    "автоматически — пользователю покажут окно, и после его "
                    "ответа операция выполнится. Не переноси файл внутрь и "
                    "не отказывайся."
                ),
            })
            await self._emit({
                "type": "nudge",
                "reason": "boundary_refusal",
                "path": path,
                "attempt": self.boundary_nudges,
            })
            return True

        # Модель уперлась. Раз она назвала конкретный путь — поднимаем запрос
        # сами: лучше лишний вопрос с понятным путём, чем молчание.
        self.pending_permission = {
            "operation": "write_file",
            "path": path,
            "args": {},
            "question": (
                "Мне нужно выйти за пределы воркспейса.\n"
                f"Путь вне воркспейса «{guard.workspace_id or guard.workspace_root}»: "
                f"{path}\n"
                "Разрешить?"
            ),
        }
        self.pending_question = self.pending_permission["question"]
        self.phase = Phase.ASKING_USER
        await self._emit({
            "type": "permission",
            "operation": self.pending_permission["operation"],
            "path": path,
            "question": self.pending_permission["question"],
        })
        return True

    async def _one_step(self) -> str:
        result = await self._complete()
        if result.get("error"):
            await self._step(Phase.THINKING, "", ok=False, error=result["error"])
            return "stop"

        # Reasoning-модели (gpt-oss, nemotron, glm-flash) часто кладут полезный
        # текст в отдельное поле reasoning, а content оставляют пустым.
        # Для разбора вызовов инструментов берём оба поля.
        text = str(result.get("text") or "")
        reasoning = str(result.get("reasoning") or "")
        combined = f"{text}\n{reasoning}".strip() if reasoning and reasoning not in text else text
        model = result.get("model")
        duration = result.get("duration_ms", 0)

        calls, broken = _parse_calls(combined)

        if not calls and result.get("error"):
            # Провайдер прямо сказал «попробуйте позже» — это 429 или перегрузка.
            await self._step(Phase.THINKING, "", model=model, duration_ms=duration,
                             ok=False, error=str(result["error"]))
            return "stop"

        if not calls:
            # Модель хотела вызвать инструмент, но испортила формат. Завершать
            # такую задачу успехом нельзя: она выглядит сделанной, а на самом
            # деле ничего не выполнено. Возвращаем требование формата и
            # пробуем ещё раз — но не бесконечно.
            if broken or looks_like_tool_call(combined):
                return await self._retry_format(combined, broken, model, duration)

            final = text.strip() or reasoning.strip()
            if not final:
                # Пустой ответ: failover уже повторил с увеличенным бюджетом.
                # Значит, модель молчит — не крутим цикл, а честно останавливаемся.
                await self._step(
                    Phase.THINKING,
                    "Модель вернула пустой ответ даже с увеличенным лимитом токенов",
                    model=model, duration_ms=duration, ok=False, error="пустой ответ",
                )
                self.finished = False
                await self._emit({
                    "type": "failed",
                    "reason": "пустой ответ модели",
                    "model": model,
                })
                return "stop"

            self.messages.append({"role": "assistant", "content": final})

            # Модель отказалась действовать словами: «нужен доступ к C:\x».
            # Пока инструмент не вызван, система не знает, о каком пути речь,
            # и запрос в интерфейсе не появляется. Сначала требуем от модели
            # реального действия, а если она упирается — поднимаем запрос сами.
            handled = await self._handle_boundary_refusal(final)
            if handled:
                return "stop" if self.pending_permission is not None else "continue"

            await self._step(Phase.THINKING, final, model=model, duration_ms=duration)
            self.finished = True
            await self._emit({
                "type": "done",
                "text": final,
                "model": model,
                # Что удалось создать. Интерфейс показывает по этому
                # списку ссылки, чтобы результат открывался в один клик,
                # а не искался вручную среди папок.
                "artifacts": list(self.artifacts),
            })
            return "stop"

        self.messages.append({"role": "assistant", "content": combined})

        # Группируем вызовы по файлам, чтобы проверять каждый файл один раз.
        touched: set[str] = set()
        for call in calls:
            if self.pending_question is not None:
                return "stop"
            written = await self._run_tool(call, model)
            for path in written:
                touched.add(path)

        if self.pending_question is not None:
            return "stop"

        if touched and self.config.verify_writes:
            await self._verify_all(touched)

        if self.verifications and any(not v["ok"] for v in self.verifications):
            # Не отдаём управление модели, пока записанное не подтверждено.
            self.messages.append({
                "role": "user",
                "content": "Проверка записи не прошла. Исправь проблему и сообщи результат.",
            })
            return "continue"

        self._trim_history()
        self.messages.append({
            "role": "user",
            "content": "Инструменты выполнены. Продолжай: следующий шаг или итоговый ответ.",
        })
        return "continue"

    def _trim_history(self) -> None:
        """Обрезать историю, оставив системный промпт и хвост диалога.

        Бесплатные модели деградируют на длинном контексте, поэтому старые
        сообщения уходят, а начало с задачей остаётся.
        """
        limit = self.config.max_history
        if limit <= 0 or len(self.messages) <= limit + 1:
            return

        system = self.messages[0]
        task = self.messages[1] if len(self.messages) > 1 else None
        tail = self.messages[-(limit - 2):]

        rebuilt = [system]
        if task is not None:
            rebuilt.append(task)
        rebuilt.append({
            "role": "user",
            "content": f"[{len(self.messages) - len(rebuilt) - 1} ранних сообщений "
                       "свёрнуто для экономии контекста]",
        })
        rebuilt.extend(tail)
        self.messages = rebuilt

    async def _verify_all(self, paths: set[str]) -> None:
        """Проверить все записанные файлы раз за шаг."""
        for path in sorted(paths):
            if not path or not Path(path).exists():
                continue
            report = await asyncio.get_running_loop().run_in_executor(
                None, verify_file, path
            )
            self.verifications.append(report)
            await self._step(
                Phase.THINKING,
                f"Проверка {Path(path).name}: {report['detail']}",
                ok=report["ok"],
                error=None if report["ok"] else report["detail"],
            )
            await self._emit({"type": "verify", "verification": report})

    async def _run_tool(self, call: dict[str, Any], model: str | None) -> list[str]:
        """Выполнить инструмент. Возвращает пути, которые нужно проверить."""
        name = call["tool"]
        args = call.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        self.phase = Phase.USING_TOOL
        # Инструменты синхронные, а мы внутри event loop воркера. Прямой вызов
        # блокировал цикл на всё время команды: `run_shell` живёт до 120 секунд,
        # и всё это время /api/ask, отмена задачи и ответы на вопросы висели в
        # очереди — интерфейс выглядел замершим. Уводим работу в поток.
        loop = asyncio.get_running_loop()
        # `base` не пропускается через `**args`. Модель отвечает за произвольный
        # JSON и может прислать лишний аргумент: `run_tool(name, guard,
        # base=self.workspace, **{"base": "."})` падает TypeError **до** входа в
        # тело `run_tool`, то есть мимо всех проверок внутри и наружу — до
        # `_execute`, где такая ошибка помечала задачу сломанной без шага,
        # без события и без результата. Здесь лишние имена отбрасываются, а
        # неожиданное исключение становится обычным отказом инструмента.
        allowed = tool_arg_names(name)
        call_args = ({k: v for k, v in args.items() if k in allowed}
                     if allowed else dict(args))
        try:
            result = await loop.run_in_executor(
                None,
                lambda: run_tool(name, self.guard,
                                 base=self.workspace, **call_args),
            )
        except Exception as exc:  # noqa: BLE001
            result = ToolResult(
                False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=0,
            )

        await self._step(
            Phase.USING_TOOL,
            self._describe_tool(name, args, result),
            model=model,
            tool=name,
            duration_ms=result.duration_ms,
            ok=result.ok,
            error=result.error,
        )
        await self._emit({"type": "tool", "tool": name, "args": args,
                          "result": _tool_result_brief(result),
                          "sub": self.part})
        self._trace_tool(name, args, _tool_result_brief(result))

        checked = self._paths_to_verify(name, args, result)
        self._note_artifact(name, args, result)

        # Выход за границу воркспейса — это вопрос с однозначным ответом,
        # а не общий вопрос о помощи. Его обрабатываем отдельно: воркер
        # должен показать диалог с кнопками «Разрешить / Отклонить».
        if result.needs_permission:
            self.pending_permission = {
                "operation": name,
                "path": (result.meta or {}).get("path", ""),
                "args": args,
                "question": result.question or result.error or "",
            }
            self.pending_question = self.pending_permission["question"]
            self.phase = Phase.ASKING_USER
            await self._emit({
                "type": "permission",
                "operation": name,
                "path": self.pending_permission["path"],
                "question": self.pending_permission["question"],
            })
            return checked

        if (result.needs_user
                # YOLO — это ровно «делай, не спрашивая». Условие стояло
                # только на `escalation`, и автономия в нём не участвовала:
                # при полном доступе и «делай всё» агент всё равно вставал и
                # ждал ответа. Проверка `escalation` отвечает на другой
                # вопрос — можно ли выходить за папку, — и подменяла собой
                # этот.
                and self.guard.autonomy is not Autonomy.YOLO
                and self.guard.escalation is not Escalation.OFF):
            self.pending_question = result.question or (
                f"Инструмент «{name}» не сработал: {result.error}. Продолжать?"
            )
            self.phase = Phase.ASKING_USER
            self.messages.append({
                "role": "user",
                "content": f"Инструмент «{name}» требует помощи: {result.error}",
            })
            await self._emit({"type": "question", "question": self.pending_question})
            return checked

        self.messages.append({
            "role": "user",
            "content": f"Результат {name}: {_tool_result_brief(result)}",
        })
        return checked

    async def grant_permission(self, path: str) -> None:
        """Пользователь разрешил выход за границу воркспейса на этот путь."""
        self.guard.grant_path(path)
        self.pending_permission = None
        self.pending_question = None
        self.phase = Phase.THINKING
        self.messages.append({
            "role": "user",
            "content": (
                f"Пользователь разрешил доступ к {path}. "
                "Продолжай ту же операцию."
            ),
        })
        await self._emit({"type": "permission_granted", "path": path})

    async def deny_permission(self, path: str) -> None:
        """Пользователь отказал в доступе.

        Отказ — это ответ, а не новый вопрос: агент должен искать другой
        способ и не просить этот путь снова.
        """
        self.guard.deny_path(path)
        self.pending_permission = None
        self.pending_question = None
        self.phase = Phase.THINKING
        self.messages.append({
            "role": "user",
            "content": (
                f"Пользователь запретил доступ к {path}. Не пытайся снова "
                "обратиться к этому пути: повторно спрашивать не буду. "
                "Найди способ выполнить задачу без него или честно скажи, "
                "что это невозможно, и что именно мешает."
            ),
        })
        await self._emit({"type": "permission_denied", "path": path})

    def _paths_to_verify(self, name: str, args: dict[str, Any],
                         result: ToolResult) -> list[str]:
        """Какие файлы проверять после инструмента.

        Только запись и правка: read_file и list_dir проверять нечего,
        а delete_path — нечего проверять, файла уже нет.
        """
        if not result.ok or name not in ("write_file", "edit_file"):
            return []

        path = args.get("path")
        if not path:
            return []
        # Путь из результата уже разрешён относительно рабочей директории.
        reported = (result.data or {}).get("path") if isinstance(result.data, dict) else None
        target = self.workspace / str(reported or path)
        return [str(target.resolve())]

    def _note_artifact(self, name: str, args: dict[str, Any],
                       result: ToolResult) -> None:
        """Запомнить созданный или изменённый файл.

        Ответ агента состоит из текста с путями в обратных кавычках. Сам по
        себе он бесполезен: чтобы посмотреть результат, надо вручную найти папку
        и открыть файл. Список созданного позволяет показать в ответе готовые
        ссылки — и на просмотр, и на открытие в браузере.
        """
        if not result.ok or name not in ("write_file", "edit_file", "mkdir"):
            return

        reported = (result.data or {}).get("path") if isinstance(result.data, dict) else None
        rel = str(reported or args.get("path") or args.get("output") or "").strip()
        if not rel:
            return
        rel = rel.replace("\\", "/").lstrip("./")
        if not rel:
            return

        # Каталог из mkdir — не результат сам по себе, но полезно знать:
        # ответ «всё в папке calculator/» становится ссылкой на неё.
        entry = {
            "path": rel,
            "kind": "dir" if name == "mkdir" else "file",
            "open": browser_url(self.workspace / rel),
        }
        for row in self.artifacts:
            if row["path"] == rel:
                return
        self.artifacts.append(entry)

    def _describe_tool(self, name: str, args: dict[str, Any], result: ToolResult) -> str:
        target = args.get("path") or args.get("output") or args.get("command") or ""
        verb = {"read_file": "Прочитал", "write_file": "Записал", "edit_file": "Изменил",
                "delete_path": "Удалил", "list_dir": "Показал", "search_text": "Искал",
                "run_shell": "Выполнил", "capture_screen": "Снял экран"}.get(name, name)
        if name == "web_search":
            target = str(args.get("query") or "")
            verb = "Искал в интернете"
        elif name == "web_fetch":
            target = str(args.get("url") or "")
            verb = "Открыл страницу"
        tail = f" {target}" if target else ""
        if result.ok:
            return f"{verb}{tail}"
        return f"{verb}{tail} — ошибка: {result.error}"

    async def _complete(self) -> dict[str, Any]:
        """Один вызов модели с переключением при отказе."""
        images = self._vision_images()
        outgoing = len(self.messages)
        try:
            result = await self.caller.ask(
                self.messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                images=images or None,
            )
        except FailoverError as exc:
            await self._trace_call(outgoing, None, error=str(exc))
            return {"error": str(exc)}
        await self._trace_call(outgoing, result)

        self._account_tokens(result)
        return result

    # ---------------------------------------------------------------- след

    async def _trace_call(self, sent: int, result: dict[str, Any] | None, *,
                          error: str = "") -> None:
        """Записать в след, что ушло модели и что она вернула.

        Зачем это видно: по журналу шагов нельзя понять, что именно было
        сказано модели. А когда агент отвечает не по делу или зависает,
        первым делом хотят посмотреть промпт и сырой ответ — и их негде
        взять.

        Записываются только новые сообщения, а не весь диалог: полная история
        на двадцатом шаге раздувает след до мегабайтов, а интересует хвост.
        """
        if not self.trace_on:
            return
        outgoing = [dict(m) for m in self.messages[sent:]]
        incoming: dict[str, Any] = {}
        if result is not None:
            incoming = {
                "model": str(result.get("model") or ""),
                "text": str(result.get("text") or ""),
                "reasoning": str(result.get("reasoning") or ""),
                "tokens_in": int(result.get("tokens_in") or 0),
                "tokens_out": int(result.get("tokens_out") or 0),
                "duration_ms": int(result.get("duration_ms") or 0),
            }
        record = {
            "n": len(self.trace),
            "sent": outgoing,
            "got": incoming,
            "error": error,
        }
        self.trace.append(record)
        # Обрезаем хвост: след нужен для разбора, а не для архива.
        if len(self.trace) > TRACE_LIMIT:
            del self.trace[: len(self.trace) - TRACE_LIMIT]
        await self._emit({
            "type": "model_call",
            "sub": self.part,
            "n": record["n"],
            "sent": outgoing,
            "got": incoming,
            "error": error,
        })

    def _trace_tool(self, name: str, args: dict[str, Any],
                    result: dict[str, Any]) -> None:
        """Отметить в следе вызов инструмента с аргументами и итогом."""
        if not self.trace_on:
            return
        self.trace.append({
            "n": len(self.trace),
            "tool": name,
            "args": args,
            "result": result,
        })
        if len(self.trace) > TRACE_LIMIT:
            del self.trace[: len(self.trace) - TRACE_LIMIT]

    def _account_tokens(self, result: dict[str, Any]) -> None:
        """Учесть потраченные токены и предупредить о перерасходе."""
        used = int(result.get("tokens_in") or 0) + int(result.get("tokens_out") or 0)
        budget = self.step_budget
        budget["tokens"] = int(budget.get("tokens", 0)) + used

        limit = self.config.token_budget
        if limit and budget["tokens"] > limit:
            warning = (f"превышен бюджет задачи: {budget['tokens']} из {limit} токенов "
                       f"({result.get('model')})")
            if warning not in budget["warnings"]:
                budget["warnings"].append(warning)
                self._emit_sync({"type": "budget", "tokens": budget["tokens"],
                                 "limit": limit, "warning": warning})

        used_models: dict[str, int] = budget.setdefault("per_gateway", {})
        model = str(result.get("model") or "")
        if model:
            used_models[model] = used_models.get(model, 0) + used

    def _emit_sync(self, event: dict[str, Any]) -> None:
        """Отправить событие без await (вызывается из синхронного кода учёта)."""
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:
            pass

    def _vision_images(self) -> list[str]:
        """Картинки из последнего сообщения, если режим их требует."""
        if not self.config.require_vision:
            return []
        for message in reversed(self.messages):
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, list):
                return [
                    part["image_url"]["url"]
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "image_url"
                ]
        return []

    # ------------------------------------------------- режим бесконечных вопросов

    async def consult(self, question: str, *, models: int = 3,
                      max_tokens: int = 1500) -> list[dict[str, Any]]:
        """Спросить несколько моделей и собрать их мнения (режим questions).

        Используется, когда агент сомневается: ответы разных моделей сравниваются
        между собой, а не с эталоном.
        """
        self.phase = Phase.THINKING
        exclude: set[str] = set()
        opinions: list[dict[str, Any]] = []

        for _ in range(models):
            ref = self.selector.next_model(exclude=exclude)
            if ref is None:
                break
            exclude.add(ref)

            state = self.selector.states[ref]
            gateway = next(
                (g for g in self.selector.registry.gateways if g["id"] == state.gateway), None
            )
            if gateway is None:
                continue

            from providers.openai_compat import OpenAICompatProvider
            import httpx

            client = httpx.AsyncClient(follow_redirects=True)
            try:
                # Консультация спрашивает несколько моделей подряд, поэтому
                # ключ берётся по кругу: иначе все вопросы уйдут на один
                # аккаунт и выбьют его лимит за один вызов.
                consult_key = gateway_key(gateway)
                provider = OpenAICompatProvider(
                    state.gateway, gateway["resolved_url"], consult_key,
                    timeout=self.config.step_timeout, client=client,
                )
                result = await provider.chat(
                    state.model,
                    [{"role": "user", "content": question}],
                    temperature=self.config.temperature,
                    max_tokens=max_tokens,
                )
            finally:
                await client.aclose()

            duration = int(result.get("duration_ms") or 0)
            status = "ok" if result.get("error") is None else "down"
            self.selector.record(ref, status, error=result.get("error"), duration_ms=duration)
            opinions.append({
                "ref": ref,
                "text": result.get("text") or result.get("reasoning") or "",
                "error": result.get("error"),
                "duration_ms": duration,
            })

        await self._emit({"type": "consult", "opinions": opinions})
        self.phase = Phase.IDLE
        return opinions


# ------------------------------------------------------------------ утилиты


def verify_file(path: str | Path) -> dict[str, Any]:
    """Проверить записанный файл: существование и синтаксис по расширению.

    Главный источник тихих поломок — агент записал файл и решил, что всё.
    Для .py это ast.parse, для .json — json.loads, для .yaml — без проверки.
    """
    target = Path(path)
    result: dict[str, Any] = {"path": str(target), "ok": False, "detail": "", "kind": "existence"}

    if not target.is_file():
        result["detail"] = "файл не найден"
        return result

    size = target.stat().st_size
    result["size"] = size
    if size == 0:
        result["detail"] = "файл пустой"
        return result

    suffix = target.suffix.lower()
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        result["detail"] = f"не читается как текст: {exc}"
        return result

    # BOM — метка кодировки, а не содержимое файла. Windows记事ски и часть
    # редакторов пишут её автоматически, и без удаления ast.parse ругается на
    # «invalid non-printable character U+FEFF», а json — на «Unexpected UTF-8
    # BOM». Файл при этом совершенно рабочий: помечать его сломанным значит
    # заставить агента «чинить» то, что не сломано.
    if text.startswith(BOM):
        text = text.lstrip(BOM)

    if suffix == ".py":
        result["kind"] = "syntax"
        try:
            ast.parse(text, filename=str(target))
        except SyntaxError as exc:
            result["detail"] = f"синтаксическая ошибка в строке {exc.lineno}: {exc.msg}"
            return result
        result["detail"] = f"синтаксис в порядке ({len(text.splitlines())} строк)"
    elif suffix == ".json":
        result["kind"] = "json"
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            result["detail"] = f"невалидный JSON: {exc.msg} (позиция {exc.pos})"
            return result
        result["detail"] = "валидный JSON"
    elif suffix in (".md", ".txt", ".cfg", ".ini", ".toml", ".yml", ".yaml"):
        result["kind"] = "text"
        result["detail"] = f"{len(text.splitlines())} строк"
    else:
        result["kind"] = "existence"
        result["detail"] = f"{size} байт"

    result["ok"] = True
    return result


def _tool_result_brief(result: ToolResult) -> str:
    """Короткое описание результата инструмента для контекста модели."""
    if not result.ok:
        return f"ОШИБКА: {result.error}"
    data = result.data
    if isinstance(data, dict):
        if "content" in data:
            content = str(data["content"])
            head = content[:4000]
            tail = f"\n... [{len(content) - 4000} символов скрыто]" if len(content) > 4000 else ""
            return f"{head}{tail}"
        if "stdout" in data:
            return (data.get("stdout") or "")[:4000] or "(пустой вывод)"
        if "hits" in data:
            return json.dumps(data["hits"][:50], ensure_ascii=False)
        if "path" in data:
            return json.dumps(data, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False)[:4000] if data is not None else "ок"


def selector_from_registry(
    registry: Any,
    *,
    mode: str = "auto",
    manual_ref: str | None = None,
    prefer_speed: bool = False,
    require_vision: bool = False,
    root: str | None = None,
) -> Selector:
    """Собрать селектор с tiers.json."""
    return Selector(
        registry,
        TierBook.load(root),
        mode=Mode(mode),
        manual_ref=manual_ref,
        prefer_speed=prefer_speed,
        require_vision=require_vision,
    )


def make_guard(config: AgentConfig) -> Guard:
    """Собрать Guard из конфига агента.

    Рабочая директория становится одновременно write_root и границей воркспейса:
    агент физически не может писать за её пределами, даже с полным доступом.
    """
    root = str(Path(config.base_dir).resolve())
    guard = Guard(
        access=config.access,
        autonomy=config.autonomy,
        escalation=config.escalation,
        write_roots=[root],
    )
    guard.set_workspace(root)
    return guard


@dataclass
class AgentReport:
    """Итог сессии агента для журнала."""

    task: str
    ok: bool
    steps: int
    duration_ms: int
    models: list[str]
    phase: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task[:500],
            "ok": self.ok,
            "steps": self.steps,
            "duration_ms": self.duration_ms,
            "models": self.models,
            "phase": self.phase,
        }


__all__ = [
    "Agent", "AgentConfig", "AgentReport", "Phase", "Step",
    "parse_tool_calls", "build_system_prompt", "selector_from_registry",
    "make_guard", "consult_models",
]


#: Асинхронный помощник для режима questions на уровне модуля.
async def consult_models(agent: Agent, question: str, *, models: int = 3) -> list[dict[str, Any]]:
    return await agent.consult(question, models=models)
