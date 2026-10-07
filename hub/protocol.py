"""Общий протокол клиентов: браузер и консоль обязаны говорить одно и то же.

Проблема, которую это решает
---------------------------
Было два клиента, у каждого свои строки маршрутов: браузер писал
`/api/tasks`, консоль — тоже, но по своей копии строки. Сегодня это
работает. Завтра кто-то добавит действие в веб и забудет про консоль —
и два интерфейса разойдутся: в браузере кнопка появится, в консоли нет,
или наоборот. Человек не сможет доверять ни одному из них.

Поэтому маршруты, единицы ответа и правила отображения объявлены здесь
одним списком. Консоль работает только через него, а тест сравнивает
этот список с литералами, которые на самом деле встречаются в
`hub/ui.py`. Расхождение роняет тест, а не обнаруживается через полгода
в чужой задаче.

Правило одно: состояние живёт на сервере. Клиент не хранит «своё
правда» версию задач, полосы прогресса и списка моделей — он читает
снимок и слушает поток событий. Изменение в любом клиенте уходит тем же
маршрутом и тем же телом, поэтому второй клиент увидит результат по
потоку событий, без отдельной синхронизации.
"""

from __future__ import annotations

from typing import Any, Final

#: Базовый адрес сервера. Оба клиента берут его отсюда.
SERVER: Final[str] = "http://127.0.0.1:8783"

#: Порт моста (донорский шлюз): через него идут все модели и их статус.
BRIDGE_SERVER: Final[str] = "http://127.0.0.1:8784"


class Routes:
    """Маршруты сервера. Список исчерпывающий и общий для обоих клиентов.

    Имена в верхнем регистре — потому что это константы, а не методы:
    опечатка в таком имени должна ломать импорт, а не молча уводить
    запрос на несуществующий маршрут.
    """

    # ---------------------------------------------------------- чтение
    STATE: Final[str] = "/api/state"
    EVENTS: Final[str] = "/api/events"
    TASKS: Final[str] = "/api/tasks"
    TASK_BY_ID: Final[str] = "/api/tasks/"
    SETTINGS: Final[str] = "/api/settings"
    MODELS_STATUS: Final[str] = "/api/models/status"
    DIAG: Final[str] = "/api/diag"
    LOCAL_MODELS: Final[str] = "/api/local/models"
    SESSIONS: Final[str] = "/api/sessions"
    PERMISSIONS: Final[str] = "/api/permissions"

    # --------------------------------------------------------- действия
    SEND_TASK: Final[str] = "/api/tasks"
    CANCEL_TASK: Final[str] = "/api/tasks/cancel"
    ANSWER_QUESTION: Final[str] = "/api/tasks/answer"
    PAUSE: Final[str] = "/api/pause"
    SET_MODE: Final[str] = "/api/mode"
    SET_CONFIG: Final[str] = "/api/config"
    SAVE_KEY: Final[str] = "/api/keys"
    ADD_MODEL: Final[str] = "/api/models"
    ASK_ALL: Final[str] = "/api/models/ask_all"
    THINKING: Final[str] = "/api/thinking"
    THINKING_STATE: Final[str] = "/api/thinking/state"
    LOCAL_CHAT: Final[str] = "/api/local/chat"

    #: Действия, которые оба клиента обязаны уметь отправлять. Набор
    #: закрытый: добавление нового маршрута сюда заставляет определить,
    #: как он выглядит в вебе и в консоли, иначе тест разойдётся.
    SHARED_ACTIONS: Final[tuple[str, ...]] = (
        SEND_TASK, CANCEL_TASK, ANSWER_QUESTION, PAUSE,
        SET_MODE, SET_CONFIG, SAVE_KEY, ADD_MODEL,
        ASK_ALL, THINKING, LOCAL_CHAT,
    )


class Server:
    """Адреса серверов. Общие для обоих клиентов."""

    BASE: Final[str] = "http://127.0.0.1:8783"
    BRIDGE: Final[str] = "http://127.0.0.1:8784"


def task_payload(text: str, **extra: Any) -> dict[str, Any]:
    """Тело отправки задачи — одно для браузера и консоли.

    Раньше браузер слал ещё флажки режимов (plan_only, auto_mode,
    subagents, web_research, herd, self_edit), а консоль — только текст.
    Отсюда и расхождение: задача из консоли всегда шла в автоматическом
    режиме без субагентов, и человек об этом узнавал по итогу. Теперь
    режим по умолчанию объявлен здесь и используется обоими клиентами,
    а неявное отличие исчезло.
    """
    payload: dict[str, Any] = {
        "task": str(text),
        "auto_mode": True,
        "plan_only": False,
        "subagents": 0,
        "web_research": False,
        "herd": False,
        "self_edit": False,
        # Размышление локальной моделью перед началом работы. Общее поле
        # обоих клиентов: иначе задача, отправленная из консоли, шла бы
        # без плана, а из браузера — с планом, и разница была бы невидима.
        "deepen": False,
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


#: Статусы задачи, при которых она ещё не закончилась. Клиенты показывают
#: «работает» только для них — иначе прогресс-бар висит на задаче,
#: которая давно завершена.
LIVE_STATUSES: Final[frozenset[str]] = frozenset(
    {"running", "queued", "asking", "paused"})

#: Статусы, при которых задача окончательно закрыта.
DONE_STATUSES: Final[frozenset[str]] = frozenset(
    {"done", "failed", "cancelled", "expired"})


def is_live(task: dict[str, Any]) -> bool:
    """Идёт ли задача прямо сейчас."""
    return str(task.get("status") or "") in LIVE_STATUSES


def is_done(task: dict[str, Any]) -> bool:
    """Закончилась ли задача — любой из закрывающих статусов."""
    return str(task.get("status") or "") in DONE_STATUSES


def task_number(task: dict[str, Any]) -> int | None:
    """Номер задачи или None, если он не число."""
    try:
        return int(task.get("id"))
    except (TypeError, ValueError):
        return None


def live_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Задачи, которые сейчас идут, — одинаково для обоих клиентов."""
    out: list[dict[str, Any]] = []
    for item in state.get("tasks") or []:
        if isinstance(item, dict) and is_live(item):
            out.append(item)
    return out


def model_state_mark(state: str) -> str:
    """Общее имя состояния модели.

    Клиенты по-разному изображают состояние (цвет в браузере, точка в
    консоли), но классифицируют его одинаково — иначе один из них
    покажет «отвечает» там, где другой показывает «на остывании».
    """
    value = str(state or "")
    return value if value in MODEL_STATES else "unknown"


#: Состояния, которые клиенты обязаны трактовать одинаково.
MODEL_STATES: Final[frozenset[str]] = frozenset(
    {"ok", "local", "fail", "cooling", "unknown"})


def events_url(since: int = 0) -> str:
    """Адрес потока событий с курсором.

    Оба клиента читают один и тот же поток. Курсор нужен, чтобы не
    перерисовывать историю, но идёт он по тому же адресу, что и раньше:
    расхождение формата здесь означало бы «в браузере события есть, в
    консоли нет».
    """
    return f"{Routes.EVENTS}?since={int(since)}"