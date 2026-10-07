"""zagent CLI — свой интерфейс в консоли к уже работающему серверу.

Зачем отдельная программа
--------------------------
Панель в браузере хороша, но консоль ближе к тому, как агентом
пользуются на самом деле: человек вводит задачу и смотрит поток. Здесь
тот же сервер (127.0.0.1:8783) и те же данные, но без вкладок, без
загрузки шрифтов и без лишних двухсот килобайт интерфейса.

Дизайн взят не с потолка: палитра и правила — из `ref/`. Тёмная панель,
один акцентный синий, рамки вместо теней, никакой анимации. Те же цвета,
что в темах веб-интерфейса (`--bg #0d1014`, `--panel #141922`,
`--edge #242c38`, `--accent #3b82f6`), чтобы консоль и браузер выглядели
как один продукт, а не как две разные программы.

Мгновенный старт
----------------
Программа не поднимает сервер и не проверяет окружение: она подключается к
тому, что уже работает. Поэтому запуск занимает время открытия сокета, а
не десятки секунд подготовки. Если сервер не отвечает — об этом говорится
сразу и по делу, с адресом, а не «ошибка сети».

Управление
----------
  введите текст и Enter    задать задачу агенту
  /status                   состояние сервера, задачи и моделей
  /models                   все модели: отвечает, отказала, на остывании
  /askall <вопрос>          спросить все модели разом (через мост)
  /deepen <текст>           размышление: развернуть запрос локальной моделью
  /quit                     выход (Ctrl+C тоже)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.protocol import (  # noqa: E402
    DONE_STATUSES,
    LIVE_STATUSES,
    Routes,
    Server as _Proto,
    events_url,
    is_live,
    live_tasks,
    task_number,
    task_payload,
)

# --------------------------------------------------------------- палитра

BG = "\x1b[48;2;13;16;20m"      # --bg   #0d1014
PANEL = "\x1b[48;2;20;25;34m"   # --panel #141922
EDGE = "\x1b[38;2;36;44;56m"    # --edge  #242c38
TEXT = "\x1b[38;2;228;232;239m"  # --text  #e4e8ef
MUTED = "\x1b[38;2;135;146;164m"  # --muted #8792a4
DIM = "\x1b[38;2;95;107;125m"   # --dim    #5f6b7d
ACCENT = "\x1b[38;2;59;130;246m"  # --accent #3b82f6
OK = "\x1b[38;2;34;197;94m"     # --ok     #22c55e
WARN = "\x1b[38;2;245;158;11m"  # --warn   #f59e0b
BAD = "\x1b[38;2;239;68;68m"    # --bad    #ef4444
BOLD = "\x1b[1m"
OFF = "\x1b[0m"

SERVER = _Proto.BASE

#: Состояния задач берём из протокола: иначе один клиент считал бы
#: задачу живой, а другой — нет.
LIVE = LIVE_STATUSES
DONE = DONE_STATUSES
PROMPT = f"{ACCENT}›{OFF} "
STATE_MARK = {"ok": f"{OK}●{OFF}", "local": f"{OK}●{OFF}",
              "fail": f"{BAD}●{OFF}", "cooling": f"{WARN}●{OFF}",
              "unknown": f"{DIM}○{OFF}"}


def _enable_vt() -> bool:
    """Разрешить ANSI на Windows 10/11.

    Без этого весь цвет превращается в мусор вида «[38;2;59;130;246m».
    Режим включается один раз на процессор; если не вышло — программа
    работает как обычный текст, просто без цвета.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32            # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-12)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        ok = kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return bool(ok)
    except Exception:  # noqa: BLE001 - цвет не должен мешать работе
        return False


COLOR = _enable_vt()


def c(code: str, text: str) -> str:
    return f"{code}{text}{OFF}" if COLOR else text


def visible(text: str) -> int:
    """Ширина строки без ANSI-последовательностей.

    Правый край рамки считается по «голому» тексту: иначе служебные
    символы цвета съедают колонки и рамка «едет».
    """
    out = 0
    inside = False
    for ch in text:
        if ch == "\x1b":
            inside = True
        elif inside:
            if ch == "m":
                inside = False
        else:
            out += 1
    return out


def width(default: int = 88) -> int:
    try:
        import shutil

        return max(52, min(shutil.get_terminal_size((default, 24)).columns, 110))
    except Exception:  # noqa: BLE001
        return default


# ------------------------------------------------------------------ сеть


def request(path: str, payload: dict[str, Any] | None = None,
            base: str = SERVER, timeout: float = 30.0) -> dict[str, Any]:
    """Один запрос к серверу. Ошибка приходит словами, а не исключением."""
    url = f"{base.rstrip('/')}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code}"}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return {"ok": False,
                "error": f"сервер не отвечает ({type(exc).__name__})"}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "плохой ответ сервера"}
    return parsed if isinstance(parsed, dict) else {"ok": False,
                                                     "error": "не объект"}


def events(since: int = 0, base: str = SERVER) -> Iterator[dict[str, Any]]:
    """Поток событий задачи — тот же SSE, что слушает браузер."""
    url = f"{base.rstrip('/')}{events_url(since)}"
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    try:
        resp = urllib.request.urlopen(req, timeout=120.0)
    except (urllib.error.URLError, OSError):
        return
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                return
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                yield parsed


def thinking_stream(text: str, base: str = SERVER) -> Iterator[dict[str, Any]]:
    """Размышление по словам — поток от сервера, печатаем на лету."""
    url = f"{base.rstrip('/')}{Routes.THINKING}"
    data = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
        method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=600.0)
    except (urllib.error.URLError, OSError) as exc:
        yield {"error": f"сервер недоступен ({type(exc).__name__})"}
        return
    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                return
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                yield parsed


# ------------------------------------------------------------------ вывод


class Screen:
    """Перерисовка «шапки» без мигания.

    Обычный print на каждом событии оставляет за собой сотни строк: в
    консоли это не поток мысли, а простыня. Здесь событие обновляет одну
    строку статуса, а текст ответа дописывается вниз — как в живой
    переписке.
    """

    def __init__(self) -> None:
        self.last = 0
        self.model = ""
        self.phase = ""
        self.steps = ""
        self._drawn = ""
        self._lock = threading.Lock()

    def header(self) -> None:
        w = width()
        line = f"{ACCENT}zagent{OFF} {DIM}cli{OFF}  {EDGE}{'─' * (w - 14)}{OFF}"
        print(line)

    def status_line(self) -> None:
        with self._lock:
            text = (f" модель {self.model or DIM + 'выбирается' + OFF}"
                    f"{DIM} · {OFF}фаза {self.phase or '-'}"
                    f"{DIM} · {OFF}шаги {self.steps or '-'}")
            # Раньше строка перерисовывалась на каждом событии, даже если
            # текст не менялся: в терминале это мерцание, в перенаправленном
            # выводе — тысячи escape-последовательностей в одной строке.
            if text == self._drawn:
                return
            self._drawn = text
            sys.stdout.write("\x1b[1A\x1b[2K" + c(DIM, text))
            sys.stdout.flush()

    def line(self, text: str = "") -> None:
        print(text)


# ------------------------------------------------------------------ команды


def cmd_status(scr: Screen) -> None:
    data = request(Routes.STATE, timeout=10.0)
    if not data.get("ok") and data.get("error"):
        scr.line(c(BAD, f"  сервер: {data['error']}"))
        return
    tasks = data.get("tasks") or []
    # Живые задачи считает протокол: иначе консоль и браузер считают
    # разные наборы и показывают разное «что сейчас работает».
    running = live_tasks(data)
    current = running[0] if running else None
    scr.line(c(MUTED, "  сервер      отвечает"))
    scr.line(c(MUTED, f"  моделей     {len(data.get('candidates') or [])}"))
    scr.line(c(MUTED, f"  задач       {len(tasks)}"))
    if current:
        scr.line(c(MUTED, f"  сейчас      #{current.get('id')}"
                          f" {str(current.get('status'))}"))


def cmd_models(scr: Screen) -> None:
    data = request(Routes.MODELS_STATUS, timeout=40.0)
    if data.get("error"):
        scr.line(c(BAD, f"  {data['error']}"))
        return
    bridge = data.get("bridge") or {}
    scr.line(c(MUTED, "  мост        "
                      + ("отвечает" if bridge.get("ok") else "не отвечает")))
    rows = data.get("models") or []
    if not rows:
        scr.line(c(WARN, "  моделей в таблице нет — мост выключен?"))
        return
    w = width()
    for row in rows:
        mark = STATE_MARK.get(str(row.get("state")), STATE_MARK["unknown"])
        name = str(row.get("id") or "?")
        extra = ""
        if row.get("cooldown_left_s"):
            extra = c(DIM, f" ещё {row['cooldown_left_s']} с")
        elif row.get("last_ms"):
            extra = c(DIM, f" {row['last_ms']} мс")
        pad = max(1, w - visible(name) - visible(extra) - 14)
        scr.line(f"  {mark} {c(TEXT, name)}{' ' * pad}{extra}")
        if row.get("reason"):
            scr.line(f"      {c(DIM, str(row['reason'])[:100])}")


def cmd_askall(scr: Screen, question: str) -> None:
    if not question.strip():
        scr.line(c(WARN, "  вопрос пустой"))
        return
    scr.line(c(MUTED, f"  спрашиваю все модели: {question}"))
    data = request(Routes.ASK_ALL, {"text": question}, timeout=240.0)
    if data.get("ok") is False:
        scr.line(c(BAD, f"  {data.get('error') or 'мост не ответил'}"))
        return
    results = data.get("results") or []
    for item in results:
        if item.get("ok"):
            head = c(OK, "ответила")
            answer = str(item.get("answer") or "")
        else:
            head = c(BAD, "отказ")
            answer = str(item.get("error") or "")
        scr.line(f"  {c(TEXT, str(item.get('id')))} {head} "
                 f"{c(DIM, str(item.get('ms')) + ' мс')}")
        for chunk in answer.splitlines()[:6]:
            scr.line(f"      {c(MUTED, chunk[:100])}")


def cmd_deepen(scr: Screen, text: str) -> None:
    if not text.strip():
        scr.line(c(WARN, "  текст пустой"))
        return
    shown = 0
    for piece in thinking_stream(text):
        if piece.get("error"):
            scr.line(c(BAD, f"  {piece['error']}"))
            return
        if piece.get("start"):
            scr.line(c(MUTED, f"  размышляет {piece.get('model') or ''}"))
            continue
        chunk = str(piece.get("text") or "")
        if chunk:
            sys.stdout.write(c(TEXT, chunk))
            sys.stdout.flush()
            shown += 1
    if shown:
        sys.stdout.write("\n")
    else:
        scr.line(c(WARN, "  пустой ответ"))


def _active_from(state: dict[str, Any]) -> set[int]:
    """Задачи, за которыми следим: те, что идут на сервере сейчас."""
    return {n for n in (task_number(t) for t in live_tasks(state))
            if n is not None}


HELP = [
    ("ввод + Enter", "задать задачу агенту"),
    ("/status", "состояние сервера и задач"),
    ("/models", "все модели и их статус"),
    ("/askall <вопрос>", "спросить все модели разом"),
    ("/deepen <текст>", "развернуть запрос локальной моделью"),
    ("/quit", "выйти"),
]


def cmd_help(scr: Screen) -> None:
    for key, desc in HELP:
        scr.line(f"  {c(ACCENT, key.ljust(16))} {c(MUTED, desc)}")


# ------------------------------------------------------------------ поток


def follow(scr: Screen, last: int, stop: threading.Event,
           active: set[int]) -> int:
    """Печатает события той задачи, которая идёт сейчас.

    События чужих задач пропускаются целиком. Без этого на запуске CLI
    выводил «задача закончена» по завершениям, случившимся до его старта,
    а счётчик событий уезжал вперёд по всей истории.
    """
    for event in events(since=last):
        if stop.is_set():
            break
        task_id = event.get("task_id")
        # Пустой active — смотреть нечего: молчание честнее вывода по
        # чужим завершениям, которое и выглядело как «задача закончена».
        if not isinstance(task_id, int) or task_id not in active:
            last = max(last, int(event.get("id") or last))
            continue
        kind = str(event.get("type") or "")
        if kind == "step":
            scr.model = str(event.get("model") or scr.model)
            scr.phase = str(event.get("phase") or scr.phase)
            scr.steps = f"{event.get('index', 0)}/{event.get('total', '?')}"
            scr.status_line()
        elif kind in {"assistant", "message", "final", "answer"}:
            text = str(event.get("text") or event.get("content") or "")
            if text:
                for chunk in text.splitlines() or [""]:
                    scr.line(f"  {c(TEXT, chunk)}")
        elif kind in {"finished", "done"}:
            scr.line(c(OK, "  задача закончена"))
        elif kind in {"error", "failed"}:
            scr.line(c(BAD, f"  ошибка: {event.get('error') or event.get('message') or ''}"))
        elif kind == "question":
            scr.line(c(WARN, f"  вопрос: {event.get('text') or ''}"))
        last = max(last, int(event.get("id") or last))
    return last


# -------------------------------------------------------------------- main


def main() -> int:
    scr = Screen()
    scr.header()
    scr.line("")
    hello = request(Routes.STATE, timeout=8.0)
    if hello.get("error"):
        scr.line(c(BAD, f"  {hello['error']}"))
        scr.line(c(MUTED, f"  жду {SERVER} — сервер поднимается через "
                          "zagent.bat (двойной клик по файлу)"))
    else:
        scr.line(c(OK, f"  на связи с {SERVER}"))
    scr.line(c(DIM, "  /help — команды, Ctrl+C — выход"))
    scr.line("")

    stop = threading.Event()
    # Поток событий отдаёт всю историю сервера, а курсора в /api/state нет:
    # в `session` лежит имя сессии, а не номер события. Поэтому печатаем
    # только события задачи, которая сейчас идёт, — и той, что человек
    # отправил из консоли.
    last = 0
    active = _active_from(hello)
    # Поток событий: консоль остаётся отзывчивой, пока агент работает.
    def pump() -> None:
        nonlocal last
        while not stop.is_set():
            try:
                last = follow(scr, last, stop, active)
            except Exception:  # noqa: BLE001 - поток не должен ронять программу
                time.sleep(2.0)
    thread = threading.Thread(target=pump, daemon=True)
    thread.start()

    # Русский текст из консоли приходит в кодировке консоли (cp1251/cp866),
    # а программа читала utf-8: первое же русское слово роняло программу
    # ошибкой декодирования, то есть отправка задачи была невозможна.
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        while True:
            try:
                text = input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                break
            text = text.strip()
            if not text:
                continue
            if text in {"/quit", "/exit", "/q"}:
                break
            if text == "/help":
                cmd_help(scr)
            elif text == "/status":
                cmd_status(scr)
            elif text == "/models":
                cmd_models(scr)
            elif text.startswith("/askall"):
                cmd_askall(scr, text[len("/askall"):].strip())
            elif text.startswith("/deepen"):
                cmd_deepen(scr, text[len("/deepen"):].strip())
            else:
                scr.line(c(DIM, "  ставлю в очередь…"))
                answer = request(Routes.SEND_TASK, task_payload(text),
                                 timeout=30.0)
                if answer.get("ok"):
                    try:
                        active.add(int(answer.get("task_id")))
                    except (TypeError, ValueError):
                        pass
                    scr.line(c(OK, f"  задача #{answer.get('task_id')} принята"))
                else:
                    scr.line(c(BAD, f"  {answer.get('error') or 'отказ'}"))
            scr.line("")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    scr.line(c(MUTED, "  пока"))
    return 0


if __name__ == "__main__":
    sys.exit(main())