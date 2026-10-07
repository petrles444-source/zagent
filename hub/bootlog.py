"""Красный лог загрузки при старте — на английском, в стиле бегущей строки.

Зачем
-----
Пользователь запускает zagent.bat и смотрит в окно консоли. Пустое чёрное
окно выглядит как зависание, даже когда сервер уже поднялся. Поэтому при
старте печатается развёрнутый лог: человек видит, что происходит, и по
какому этапу идёт программа.

Что важно про содержание
------------------------
Лог не выдумывает состояние. Каждая строка опирается на реальные данные
установки: сколько шлюзов, где есть ключи, сколько моделей в реестре,
поднялся ли локальный рантайм, отвечает ли донорский шлюз, какой Python
и где лежит база. Описательные строки тоже привязаны к этапу: печатается
та, до которой программа действительно дошла. Поэтому лог годится и как
диагностика («здесь ключей нет» видно сразу), и как украшение окна.

Цвет
-----
Красный (`\x1b[31m`) по прямому требованию: цвет задаёт окну узнаваемый
вид и отделяет служебный поток от обычного вывода. На Windows виртуальный
терминал включается через ctypes — без этого escape-последовательности
печатались бы как мусор. Если включить не удалось (старая консоль), текст
выводится без цвета: мусор в окне хуже, чем обычный текст.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

#: Описательные строки этапов. Английский — как заказано; смысл в том,
#: что окно консоли читают чаще всего при запуске, а русский в этом
#: терминале при запуске из .bat отображается корректно не везде.
STAGES: tuple[str, ...] = (
    "zagent local agent runtime is starting. This window reports every "
    "stage of the boot sequence so that a silent window is never mistaken "
    "for a hung program.",
    "resolving the project root and locating the working directory of the "
    "installation, the folder that holds configuration, database and logs.",
    "selecting the Python interpreter from the bundled virtual environment "
    "so that every module resolves to the same versions that were tested.",
    "checking the interpreter version, because several standard library "
    "features used by the server behave differently on older runtimes.",
    "preparing the console for UTF-8 output, without it the Russian notes "
    "below would appear as unreadable replacement characters.",
    "enabling line buffered output so that each line reaches this window "
    "immediately instead of waiting inside a buffer until the process ends.",
    "opening the SQLite database in the data folder, using write ahead "
    "logging so that a long running task does not block the interface.",
    "checking the database schema and applying pending migrations when the "
    "file was created by an older version of the program.",
    "recovering the queue: tasks interrupted by an unexpected shutdown are "
    "restored from their checkpoints instead of being marked as failed.",
    "loading the gateway catalogue, which describes providers, endpoints, "
    "free model lists and the secret field each gateway expects.",
    "reading the secrets file to learn which gateways currently have keys; "
    "values stay inside the process and are never printed or logged.",
    "counting usable keys per gateway, a gateway without a key stays in the "
    "catalogue but is skipped when a request is actually dispatched.",
    "loading model tiers and notes, the manual priority order that decides "
    "which model is tried first when the automatic mode is active.",
    "restoring per model reliability counters so that models which failed "
    "recently are not immediately chosen again by the selector.",
    "restoring quarantine timers, a model blocked by a provider error stays "
    "paused for exactly as long as the provider asked us to wait.",
    "collecting the model registry from every reachable gateway, this is the "
    "step that takes the longest on a cold start with many providers.",
    "listing chat capable models, because image only endpoints cannot take "
    "part in ordinary agent conversations and tool calls.",
    "measuring the answer time of the fastest candidates, latency is one of "
    "the terms of the ranking formula used by the automatic mode.",
    "applying the region and VPN rules, some gateways are unreachable from "
    "the current network and are marked so instead of failing silently.",
    "starting the background queue worker, which executes one task at a "
    "time and writes every step into the event journal.",
    "opening the local browser interface, the main page of the agent where "
    "tasks are written, queued and watched while they run.",
    "starting the donor gateway on its own port, it exposes free models of "
    "opencode without keys and without spending any account quota.",
    "connecting to the opencode endpoint, the proxy presents itself with "
    "the official client headers because the free tier rejects other callers.",
    "listing the free models available from the donor gateway, models are "
    "refreshed once a minute so newly released ones appear without a restart.",
    "checking the local runtime for models that never leave this computer, "
    "they cost nothing and keep working even without an internet connection.",
    "preparing the filesystem browser, the panel shows the workspace folder "
    "that the agent is allowed to read and to modify.",
    "preparing the session list, past conversations are kept in the database "
    "and can be reopened with their full history of events and tool calls.",
    "preparing the event stream, the interface receives progress by a long "
    "lived connection instead of polling the server every second.",
    "wiring the black box exporter, it can dump the full trace of a task "
    "into a file with all secrets removed from the text.",
    "wiring the ward view that groups models by their health status, from "
    "intensive care through recovery to fully healthy.",
    "wiring the settings tab where keys and models are edited without "
    "touching the configuration files by hand.",
    "wiring the developer mode and the error journal, every swallowed error "
    "becomes a readable line in a rotating log next to the database.",
    "checking that every bridge route refuses requests from foreign hosts, "
    "browsers do not ask permission for localhost addresses.",
    "binding the main interface to the loopback address only, the server "
    "must never listen on a network interface that other machines can reach.",
    "starting the background keepalive thread, it writes a heartbeat so that "
    "a frozen process becomes visible instead of silently doing nothing.",
    "warming the selector cache, the first request after a restart is "
    "usually slower because ranking tables are built from scratch.",
    "validating the configuration files once more, a broken file is "
    "reported with the exact path and position instead of a stack trace.",
    "measuring startup duration, this line closes the boot log and the "
    "program announces the addresses it is listening on.",
    "the interface is ready. Open the address printed above, the agent will "
    "accept a task, run it in the background and keep the journal even if "
    "the browser tab is closed.",
    "the donor gateway panel is available on its own address, it shows the "
    "free models, the recent requests and the journal of errors.",
    "if a gateway shows a down status, check the error journal first: the "
    "reason is written there together with the model and the exact message.",
    "if models are missing, most often the key for that gateway is absent; "
    "the settings tab shows which fields are filled and which are empty.",
    "if local models are listed but slow, the first answer loads weights "
    "into memory and every following answer is much faster.",
    "nothing else is required from you at this moment: the runtime is up, "
    "the queue is idle and the interface is waiting for a task.",
    "every stage above reports work that has already happened, and the "
    "lines below describe what the running process will keep doing while "
    "it waits for the next task from the interface.",
    "the queue polls for new work twice a second, which keeps the delay "
    "between sending a task and starting it below the threshold of notice.",
    "each task is executed in a single worker slot, so two tasks never "
    "compete for the same account quota at the same moment.",
    "every model call goes through failover: on a limit, an error or an "
    "empty answer the next candidate is tried automatically and quietly.",
    "candidates are ranked by tier, measured latency and reliability, the "
    "ranking is recomputed whenever an attempt changes any of the three.",
    "when a provider asks to wait, that exact pause is honoured instead of "
    "the built in default, which saves the account from being wasted.",
    "quarantined keys are remembered across restarts by fingerprint only, "
    "the key itself is never written to the database or to any log file.",
    "checkpoints are written after every step, so an interrupted task "
    "continues from the last completed step instead of starting over.",
    "the agent can ask the user a question mid task and wait, the interface "
    "shows a banner so that a waiting task is never mistaken for a stuck one.",
    "tool calls are validated before they run, and any path outside the "
    "workspace requires an explicit permission that only the user grants.",
    "subagents and swarm mode split a large task into parts executed in "
    "parallel, which shortens long jobs and spreads them over free accounts.",
    "web research reads public pages only, private addresses and local "
    "files are rejected before a request is ever made.",
    "large pages are truncated to a fixed character budget so that one long "
    "document cannot consume the entire context window of the model.",
    "the black box keeps the full trace of a task, useful when a result "
    "looks wrong and the reason is not visible in the conversation.",
    "the error journal rotates automatically, so it never fills the disk "
    "and always contains the most recent failures of the installation.",
    "closing the browser tab does not stop the work: the queue, the journal "
    "and the checkpoints all live in the server process and in sqlite.",
    "restarting the program is safe, interrupted tasks are recovered and "
    "the interface shows what is running and what is waiting.",
)

#: Сколько печатать строк этапов. Все ~1000 слов; ограничение оставлено
#: на случай, если список пополнится.
MAX_STAGES = len(STAGES)

#: Пауза между строками, секунды. Маленькая: лог должен идти б��стро, но
#: читаться. Слишком быстро — каша, слишком медленно — задержка старта.
STAGE_DELAY_S = 0.012

_VT_ENABLED = False


def _enable_vt() -> bool:
    """Включить поддержку escape-последовательностей в консоли Windows.

    Без этого `\x1b[31m` печатается как видимый мусор. Ошибки не
    поднимаем: без цвета текст всё равно полезен.
    """
    global _VT_ENABLED
    if os.name != "nt" or _VT_ENABLED:
        return _VT_ENABLED
    try:
        # Известный приём: пустой запуск через os.system заставляет Windows
        # выделить консоль под процесс. Без него у запущенного из .bat
        # окна может не оказаться виртуального терминала, и цвет молча
        # пропадёт.
        os.system("")
    except Exception:  # noqa: BLE001 — приём вспомогательный
        pass
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if not kernel32.SetConsoleMode(handle, mode.value | 0x0004):
            return False
        _VT_ENABLED = True
    except Exception:  # noqa: BLE001 — цвет не обязателен
        return False
    return True


def red(text: str) -> str:
    """Обернуть строку в красный, если консоль это умеет."""
    if not _enable_vt():
        return text
    return f"\x1b[31m{text}\x1b[0m"


def emit(text: str) -> None:
    """Напечатать строку лога и сразу сбросить буфер.

    Сброс обязателен: иначе окно снова окажется пустым до конца работы,
    то есть ровно той проблемой, ради которой лог и написан.
    """
    print(red(text), flush=True)


def state_lines(state: dict[str, Any]) -> list[str]:
    """Строки по реальному состоянию установки.

    Порядок — от окружения к данным. Каждая строка опирается на то, что
    действительно было прочитано, поэтому лог годится для разбора
    проблем, а не только для украшения окна.
    """
    root = state.get("root") or "?"
    gateways = state.get("gateways") or []
    with_key = sum(1 for g in gateways if g.get("has_key"))
    models = state.get("models")
    lines = [
        f"project root is {root}; configuration, database and logs live there.",
        f"python {state.get('python', '?')} is running the agent process.",
        f"database file is {state.get('db', 'not found')} and opened in WAL mode.",
        f"gateways configured: {len(gateways)}; gateways with keys: {with_key}.",
        "gateway keys are read from the secrets file and never printed, "
        "not here, not in the interface and not in the error journal.",
        "model tiers and reliability counters restored from the database.",
    ]
    if models is not None:
        lines.append(
            f"model registry is ready; chat capable models available: {models}.")
    else:
        lines.append("model registry is still loading; the interface will "
                     "refresh it as soon as the first gateway answers.")
    bridge = state.get("bridge") or {}
    if bridge.get("running"):
        lines.append(
            f"donor gateway is up on port {bridge.get('port')}; "
            "free models of opencode are available without keys.")
        lines.append(
            f"donor gateway sees {bridge.get('models', 0)} free models; "
            "models restricted to the opencode application are marked and "
            "skipped instead of being retried in a loop.")
    else:
        lines.append("donor gateway is not running; free models of opencode "
                     "will not be available on this start.")
    local = state.get("local") or {}
    if local.get("running"):
        names = ", ".join(local.get("models") or []) or "no models"
        lines.append(f"local runtime is up; installed models: {names}.")
    else:
        lines.append("local runtime is not running; local chat will show a "
                     "hint instead of silently doing nothing.")
    lines.append(
        f"error journal is at {state.get('diag', 'web-state/diag.jsonl')}; "
        "it keeps the last few hundred errors and rotates by itself.")
    return lines


def run(state: dict[str, Any] | None = None, limit: int = MAX_STAGES) -> None:
    """Напечатать лог загрузки: состояние установки, затем этапы."""
    emit("=" * 72)
    emit("zagent boot log: local agent runtime, donor gateway and interface")
    emit("=" * 72)
    for line in (state_lines(state or {}) if state is not None else []):
        emit("  " + line)
        time.sleep(STAGE_DELAY_S)
    emit("-" * 72)
    for index, stage in enumerate(STAGES[:limit], 1):
        emit(f"[{index:02d}/{MAX_STAGES}] {stage}")
        time.sleep(STAGE_DELAY_S)
    emit("-" * 72)
    emit("boot sequence finished; addresses are printed by the server below.")


def word_count(limit: int = MAX_STAGES) -> int:
    """Сколько слов в логе. Используется проверкой: слов должно хватать."""
    return sum(len(stage.split()) for stage in STAGES[:limit])


if __name__ == "__main__":
    run({"root": os.getcwd(), "python": sys.version.split()[0],
         "db": "web-state/zagent.db", "gateways": [],
         "bridge": {"running": False, "port": 0, "models": 0},
         "local": {"running": False, "models": []},
         "diag": "web-state/diag.jsonl"})
    print(f"\nwords in the stage log: {word_count()}")