"""Фоновый воркер агента: очередь задач, отдельный поток, поток событий.

Зачем это нужно: агент больше не привязан к одному HTTP-запросу. Задача
ставится в очередь, воркер выполняет её в своём потоке, а интерфейс читает
журнал через SSE. Закрыл вкладку — работа продолжается.

Остановка: pause/resume/cancel на уровне задачи, целиком воркер не убивается —
иначе теряется уже сделанное.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from hub.agent import Agent, AgentConfig, Phase, make_guard, selector_from_registry
from hub.autonomy import AccessLevel, Autonomy, Escalation
from hub.config import load_gateways, project_root
from hub.failover import AutoCaller
from hub.keyring import REGISTRY as KEY_RING
from hub.keyring import gateway_key, note_gateway_error, note_gateway_ok
from hub.registry import collect, probe_models
from hub.regions import (
    MODE_DIRECT,
    MODE_VPN,
    RegionBook,
    summarize as region_summary,
)


def mode_is_direct(mode: str | None) -> bool:
    return mode == MODE_DIRECT
from hub.report import build_snapshot
from hub.select import Selector
from hub.store import Store
from hub.workspace import WorkspaceManager, projects_dir

#: Конвертеры для значений из конфига воркспейса: неизвестное значение
#: не должно ломать запуск, поэтому заменяем на безопасный вариант.
_ACCESS = {
    1: AccessLevel.READ,
    2: AccessLevel.WRITE,
    3: AccessLevel.FULL,
}
_AUTONOMY = {
    "yolo": Autonomy.YOLO,
    "normal": Autonomy.NORMAL,
    "strict": Autonomy.STRICT,
    "plan": Autonomy.PLAN,
}
_ESCALATION = {
    "off": Escalation.OFF,
    "auto": Escalation.AUTO,
    "on": Escalation.ON,
}


def _access_level(value: Any) -> AccessLevel:
    try:
        return _ACCESS.get(int(value), AccessLevel.WRITE)
    except (TypeError, ValueError):
        return AccessLevel.WRITE


def _autonomy(value: Any) -> Autonomy:
    return _AUTONOMY.get(str(value), Autonomy.NORMAL)


def _escalation(value: Any) -> Escalation:
    return _ESCALATION.get(str(value), Escalation.AUTO)

#: Как часто воркер проверяет очередь, сек.
POLL_INTERVAL = 0.5

#: Потолок одной задачи в секундах. Задача не может идти бесконечно: сорок
#: шагов по паре минут — уже сорок минут, а если модель подвисла, она съест
#: очередь целиком. По превышении задача помечается сбойной, а не остаётся
#: висеть в статусе running до перезапуска.
AGENT_TIMEOUT_S = 1800

#: Меньше двух частей дробить бессмысленно: одна часть — это обычный режим с
#: лишним запросом к модели на разбиение и сборку.
MIN_SWARM_PARTS = 2

#: Фоновый пинг: как часто и по каким моделям.
#:
#: Раньше состояние моделей обновлялось только по нажатию «Пинг», поэтому
#: модель могла ожидать по 15 минут после сброса лимита, и на неё даже не
#: смотрели. Бесплатные модели живут в режиме «лимит кончился → через минуту
#: отпустило», поэтому проверка должна быть сама.
#:
#: Период 12 минут, а не меньше: лимиты считаются на аккаунт, и частый пинг
#: сам съедает квоту, из-за которой модель становится недоступной.
PING_INTERVAL = 12 * 60.0

#: Какие модели проверять по таймеру. Все подряд — дорого; достаточно тех, что
#: сейчас недоступны или не проверены: именно они могут «ожить».
PING_MAX_BACKGROUND = 12

#: Пробный запрос должен быть коротким: иначе пинг сам съедает токены.
PING_PROMPT = "Ответь одним словом: ok"
PING_MAX_TOKENS = 64


@dataclass
class WorkerConfig:
    """Настройки воркера, сохраняются вместе с состоянием."""

    access: AccessLevel = AccessLevel.WRITE
    autonomy: Autonomy = Autonomy.NORMAL
    escalation: Escalation = Escalation.AUTO
    base_dir: str = ""
    max_steps: int = 40
    prefer_speed: bool = False
    require_vision: bool = False
    #: Понижать приоритет моделям, которым из России нужен VPN.
    avoid_vpn: bool = False

    def to_agent_config(self) -> AgentConfig:
        return AgentConfig(
            access=self.access,
            autonomy=self.autonomy,
            escalation=self.escalation,
            base_dir=self.base_dir or str(project_root()),
            max_steps=self.max_steps,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "access": int(self.access),
            "autonomy": self.autonomy.value,
            "escalation": self.escalation.value,
            "base_dir": self.base_dir,
            "max_steps": int(self.max_steps),
            "prefer_speed": bool(self.prefer_speed),
            "require_vision": bool(self.require_vision),
            "avoid_vpn": bool(self.avoid_vpn),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorkerConfig":
        data = data or {}
        config = cls()
        if "access" in data:
            config.access = AccessLevel(int(data["access"]))
        if "autonomy" in data:
            config.autonomy = Autonomy(str(data["autonomy"]))
        if "escalation" in data:
            config.escalation = Escalation(str(data["escalation"]))
        for key in ("base_dir",):
            if key in data and data[key]:
                setattr(config, key, str(data[key]))
        if "max_steps" in data:
            config.max_steps = int(data["max_steps"])
        if "prefer_speed" in data:
            config.prefer_speed = bool(data["prefer_speed"])
        if "require_vision" in data:
            config.require_vision = bool(data["require_vision"])
        if "avoid_vpn" in data:
            config.avoid_vpn = bool(data["avoid_vpn"])
        return config


class Worker:
    """Владеет селектором, реестром и очередью задач.

    Живёт в своём asyncio-цикле в фоновом потоке. Публичные методы синхронные:
    вызывающий код (HTTP-обработчики) не должен знать про event loop воркера.
    """

    def __init__(self, root: str | Path | None = None, store: Store | None = None) -> None:
        self.root = Path(root) if root is not None else project_root()
        self.store = store or Store(self.root)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None

        self.config = WorkerConfig.from_dict(self.store.get_meta("config"))
        if not self.config.base_dir:
            # Пусто в конфиге — значит папка ещё ни разу не выбиралась.
            # Тогда берём projects/, а не корень: результаты работы агента
            # не должны лежать рядом с кодом zagent.
            self.config.base_dir = str(projects_dir(self.root))

        self.gateways: list[dict[str, Any]] = []
        self.registry: Any = None
        self.selector: Selector | None = None
        self.snapshot: dict[str, Any] = {}

        self.probes: dict[str, dict[str, Any]] = self.store.load_probes()
        self.sanity: dict[str, dict[str, Any]] = self.store.load_sanity()
        self.workspaces = WorkspaceManager(self.root)
        #: Доступность моделей из России: заполняется командой `zagent geo`
        #: или кнопками в интерфейсе.
        self.regions = RegionBook.load(self.root)
        #: Идёт ли сейчас замер доступности и в каком режиме.
        self.geo_running = False
        self.geo_mode: str | None = None
        self.geo_progress: dict[str, Any] = {
            "done": 0, "total": 0, "current": "", "phase": "",
        }
        self.geo_log: list[str] = []

        self.paused = False
        self.current_task_id: int | None = None
        self.last_error: str | None = None
        #: Мягкая граница воркспейса: агент спрашивает перед выходом.
        self.soft_boundary: bool = bool(self.store.get_meta("soft_boundary", True))
        #: Сигнал, что event loop воркера создан и им можно пользоваться.
        self._loop_ready = threading.Event()
        #: Сигнал, что первичная загрузка завершилась (успехом или ошибкой).
        self._ready = threading.Event()
        #: Активный агент — нужен, чтобы доставить отмену и вопрос.
        self._agent: Agent | None = None
        #: Задачи, отменённые до появления агента. Отмена приходит в момент,
        #: когда задача ещё собирает guard, и до `self._agent` не доходит.
        self._cancel_requested: set[int] = set()
        #: Синхронизация для _cancel_requested: cancel() зовут из HTTP-потока.
        self._lock = threading.Lock()
        #: Подписчики событий для SSE (потоки веб-сервера).
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        #: Фоновый пинг: идёт ли сейчас, когда был последний раз, что проверили.
        self.ping_running = False
        self.ping_last: float = 0.0
        self.ping_history: list[dict[str, Any]] = []
        #: Сколько раз модель становилась доступной после недоступности.
        #: Это и есть сигнал, ради которого пинг нужен вообще.
        self.recovered: dict[str, int] = {}

    # ------------------------------------------------------------ жизненный цикл

    def start(self, *, timeout: float = 240.0) -> None:
        """Поднять фоновый поток и дождаться первичной загрузки реестра.

        Гонка, которую нужно закрыть: поток создаёт self.loop, но main может
        подойти к run_coroutine_threadsafe раньше, чем присваивание выполнится.
        Поэтому ждём на событии, а не на self.loop.
        """
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run_loop, name="zagent-worker", daemon=True)
        self.thread.start()

        if not self._loop_ready.wait(timeout=15.0):
            raise RuntimeError("Не удалось запустить event loop воркера")

        future = asyncio.run_coroutine_threadsafe(self._bootstrap(), self.loop)
        future.result(timeout=timeout)

    def stop(self) -> None:
        if self.loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop).result(timeout=15)
        except Exception:
            pass

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Присваиваем до сигнала: вызывающий поток ждёт именно событие,
        # а не проверяет поле, которое может быть ещё None.
        self.loop = loop
        self._loop_ready.set()
        loop.run_forever()

    async def _shutdown(self) -> None:
        self._persist()
        self.loop.stop()

    async def _bootstrap(self) -> None:
        """Первичная загрузка: конфиг, реестр, восстановление состояния."""
        try:
            self.gateways = load_gateways(self.root, env={})
            self.registry = await collect(self.gateways, root=self.root)
            # Лимиты из конфига — до первого запроса. Иначе остаток аккаунта
            # станет известен лишь после того, как агент упрётся в лимит, а
            # к тому моменту часть работы уже потеряна.
            KEY_RING.apply_limits(self.gateways)
            self.selector = selector_from_registry(
                self.registry,
                mode=self.store.get_meta("mode", "auto"),
                manual_ref=self.store.get_meta("manual_ref"),
                prefer_speed=self.config.prefer_speed,
                require_vision=self.config.require_vision,
                root=str(self.root),
            )
            self._apply_vpn_preference()
            self._restore_model_state()
            self._refresh_snapshot()
            # Задачи, оставшиеся в running после падения, больше не выполняются.
            for task in self.store.list_tasks(status="running", limit=100):
                self.store.update_task(
                    task["id"], status="failed",
                    error="прервано при перезапуске",
                    finished_at=time.time(),
                )
            # Запросы на выход за воркспейс намеренно переживают перезапуск:
            # на них можно ответить и позже, а по ответу задача вернётся в
            # очередь и восстановится из чекпоинта.
            # А вот задачи, ждущие запрос, которого уже нет, нельзя
            # разблокировать никогда — их честно помечаем невыполненными.
            stranded = self.store.stranded_permission_tasks()
            for task in stranded:
                self.store.update_task(
                    task["id"], status="failed",
                    error="запрос на доступ за воркспейс потерян",
                    finished_at=time.time(),
                )
            if stranded:
                self.emit({"type": "stranded", "count": len(stranded)})
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            # Сессия должна быть всегда, даже если реестр не загрузился: с
            # битым config/gateways.json интерфейс всё равно нужен, чтобы
            # показать ошибку и дать починить. Ставим вне try — иначе первая же
            # ошибка загрузки оставила бы интерфейс без единой сессии.
            try:
                # Именно set_active_session, а не ensure_session: тот только
                # находит или создаёт сессию, но выбирать активной должен
                # вызывающий.
                self.store.set_active_session(
                    self.store.ensure_session(self.workspaces.active_id)
                )
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._ready.set()

    def _apply_vpn_preference(self) -> None:
        """Передать селектору список моделей, которым нужен VPN."""
        if self.selector is None:
            return
        self.selector.avoid_vpn = self.config.avoid_vpn
        self.selector.vpn_only = self.regions.needs_vpn()

    def _restore_model_state(self) -> None:
        """Поднять карантины и оценки, сохранённые в прошлой сессии."""
        if self.selector is None:
            return
        saved = self.store.load_models()
        for ref, state in saved.items():
            target = self.selector.states.get(ref)
            if target is None:
                continue
            target.last_status = str(state.get("status") or "unknown")
            target.last_error = state.get("error")
            target.cooldown_until = float(state.get("cooldown_until") or 0)
            target.fails = int(state.get("fails") or 0)
            target.ok_count = int(state.get("ok_count") or 0)
            target.avg_ms = float(state.get("avg_ms") or 0)

        # Пинги старше 6 часов не показываем как актуальные.
        self.probes = self.store.load_probes(max_age=6 * 3600)

    def _refresh_snapshot(self) -> None:
        if self.registry is None:
            return
        self.snapshot = build_snapshot(self.registry, self.probes)

    def _persist(self) -> None:
        if self.selector is not None:
            self.store.save_models(self.selector.states)
        self.store.save_probes(self.probes)
        self.store.save_sanity(self.sanity)
        self.store.set_meta("config", self.config.to_dict())
        if self.selector is not None:
            self.store.set_meta("mode", self.selector.mode.value)
            self.store.set_meta("manual_ref", self.selector.manual_ref)
        self.store.trim_events()

    # ----------------------------------------------------------------- сессии

    def session_history(self, session_id: str, *, limit: int = 300) -> dict[str, Any]:
        """Задачи сессии и события по ним — чтобы переписку можно было восстановить.

        Отдельный метод, а не фильтр в SSE: переключение сессии — разовое
        действие, и тащить ради него фильтрацию в горячий поток незачем.
        """
        record = self.store.get_session(session_id)
        if record is None:
            return {"ok": False, "error": "Сессия не найдена"}
        tasks = self.store.list_tasks(limit=100, session_id=session_id)
        events: list[dict[str, Any]] = []
        for task in tasks:
            events.extend(self.store.events_since(0, limit=limit, task_id=task["id"]))
        events.sort(key=lambda item: item.get("id") or 0)
        return {
            "ok": True,
            "session": record,
            "tasks": tasks,
            "events": events[-limit:],
        }

    def sessions(self) -> dict[str, Any]:
        """Сессии активного воркспейса и id активной сессии."""
        workspace_id = self.workspaces.active_id
        return {
            "ok": True,
            "workspace_id": workspace_id,
            "active": self.store.active_session_id(),
            "sessions": self.store.list_sessions(workspace_id),
        }

    def new_session(self, name: str = "", *, workspace_id: str | None = None,
                    activate_workspace: bool = True) -> dict[str, Any]:
        """Новая сессия: та же папка, чистая переписка.

        Это и есть ответ на «начать с нуля, не теряя воркспейс»: файлы, права
        и настройки остаются, а история задач и диалога начинается заново.
        """
        target = workspace_id or self.workspaces.active_id
        if self.workspaces.get(target) is None:
            return {"ok": False, "error": f"Воркспейс не найден: {target}"}
        if activate_workspace and target != self.workspaces.active_id:
            self.workspaces.activate(target)

        session_id = self.store.add_session(target, name)
        self.store.set_active_session(session_id)
        self.emit({
            "type": "session", "action": "new",
            "session_id": session_id, "workspace_id": target,
        })
        return {
            "ok": True,
            "session_id": session_id,
            "workspace_id": target,
            "sessions": self.store.list_sessions(target),
        }

    def switch_session(self, session_id: str) -> dict[str, Any]:
        """Переключиться на другую сессию.

        Воркспейс переключается вместе с сессией: сессия живёт в папке, и
        оставить активной другую папку значило бы показывать историю не
        оттуда, откуда агент будет работать.
        """
        record = self.store.get_session(session_id)
        if record is None:
            return {"ok": False, "error": "Сессия не найдена"}
        workspace_id = str(record["workspace_id"])
        if self.workspaces.get(workspace_id) is None:
            return {
                "ok": False,
                "error": f"Папка воркспейса пропала: {workspace_id}",
            }
        self.workspaces.activate(workspace_id)
        self.store.set_active_session(session_id)
        self.emit({
            "type": "session", "action": "switch",
            "session_id": session_id, "workspace_id": workspace_id,
        })
        return {
            "ok": True,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "sessions": self.store.list_sessions(workspace_id),
        }

    def rename_session(self, session_id: str, name: str) -> dict[str, Any]:
        record = self.store.rename_session(session_id, name)
        if record is None:
            return {"ok": False, "error": "Сессия не найдена"}
        return {"ok": True, "session": record}

    def remove_session(self, session_id: str) -> dict[str, Any]:
        """Удалить сессию. Активной станет другая из того же воркспейса.

        Хранилище не даёт удалить последнюю сессию папки, поэтому список
        непустой. Но если база всё же осталась без сессий (правка руками,
        неудачное восстановление), создаём новую — пустой переписке не на что
        опираться.
        """
        workspace_id = str(self.workspaces.active_id)
        if not self.store.remove_session(session_id):
            return {"ok": False, "error": "Нельзя удалить последнюю сессию воркспейса"}
        if session_id == self.store.active_session_id():
            remaining = self.store.list_sessions(workspace_id)
            self.store.set_active_session(
                str(remaining[0]["id"]) if remaining
                else self.store.add_session(workspace_id)
            )
        self.emit({"type": "session", "action": "remove", "session_id": session_id})
        return {
            "ok": True,
            "active": self.store.active_session_id(),
            "sessions": self.store.list_sessions(workspace_id),
        }

    # ----------------------------------------------------------------- очередь

    def enqueue(self, task: str, *, priority: int = 5,
                payload: dict[str, Any] | None = None,
                session_id: str | None = None) -> dict[str, Any]:
        """Поставить задачу в очередь активной сессии."""
        target = session_id or self.store.active_session_id()
        task_id = self.store.add_task(task, priority=priority, payload=payload,
                                      session_id=target)
        self.store.touch_session(target)
        self.emit({"type": "queued", "task": task, "task_id": task_id,
                   "session_id": target})
        return {"ok": True, "task_id": task_id, "session_id": target}

    def cancel(self, task_id: int) -> dict[str, Any]:
        ok = self.store.cancel_task(task_id)
        # Запрос на выход за воркспейс отменённой задачи больше никто не
        # answered — иначе в интерфейсе навсегда висло бы окно с кнопками
        # для задачи, которая уже не запустится.
        self.store.drop_permissions(task_id=task_id, reason="задача отменена")
        # Флаг запоминаем всегда, даже если агента ещё нет. `cancel` приходит
        # в тот момент, когда задача как раз собирает guard и агента, и флаг
        # через `self._agent` доходил до кого-то одного на пять — задача
        # доигрывала до конца, хотя интерфейс отчитался об отмене.
        with self._lock:
            self._cancel_requested.add(task_id)
        # Действующему агенту отмену доставляем сразу: он проверяет флаг между
        # шагами, а не посреди запроса к модели — прервать сеть нечем.
        if self.current_task_id == task_id and self._agent is not None:
            self._agent.request_cancel()
        self.emit({"type": "cancel_requested", "task_id": task_id})
        return {"ok": ok, "task_id": task_id}

    def _take_cancel(self, task_id: int) -> bool:
        """Забрать отметку об отмене задачи."""
        with self._lock:
            return task_id in self._cancel_requested

    def pause(self) -> dict[str, Any]:
        self.paused = True
        self.emit({"type": "paused"})
        return {"ok": True, "paused": True}

    def resume(self) -> dict[str, Any]:
        self.paused = False
        self.emit({"type": "resumed"})
        return {"ok": True, "paused": False}

    def loop_forever(self) -> None:
        """Основной цикл воркера: разбирает очередь, пока не остановят."""
        while True:
            if self.paused or self.current_task_id is not None:
                time.sleep(POLL_INTERVAL)
                continue

            task = self.store.next_queued_task()
            if task is None:
                time.sleep(POLL_INTERVAL)
                continue

            try:
                self.store.claim_task(task["id"])
            except RuntimeError:
                continue  # уже взяли (другой поток или повторный запуск)

            self.current_task_id = task["id"]
            try:
                self._execute(task)
            except Exception as exc:
                self.store.update_task(
                    task["id"], status="failed", error=f"{type(exc).__name__}: {exc}",
                    finished_at=time.time(),
                )
            finally:
                self.current_task_id = None
                self._agent = None
                # Отметка об отмене больше не нужна: задача сошла. Без сброса
                # её id остался бы в множестве навсегда, и при повторном
                # использовании номера задача отменилась бы сама.
                with self._lock:
                    self._cancel_requested.discard(int(task["id"]))
                self._persist()

    def _execute(self, task: dict[str, Any]) -> None:
        """Выполнить одну задачу из очереди."""
        if self.selector is None:
            self.store.update_task(task["id"], status="failed", error="реестр не загружен",
                                   finished_at=time.time())
            return

        payload = task.get("payload") or {}
        # Вне воркспейса берём защиту из его собственных настроек: иначе
        # задача без workspace_id работала бы с дефолтом и не видела
        # пользовательского списка.
        protected: list[str] = list(self.workspaces.active.protected)

        # Воркспейс задачи важнее глобальной настройки: агент не должен
        # выйти за пределы папки, которую выбрали для этой задачи.
        workspace_id = payload.get("workspace_id")
        config = self.config.to_agent_config()
        if workspace_id:
            workspace = self.workspaces.get(workspace_id)
            if workspace is None or not workspace.exists():
                self.store.update_task(
                    task["id"], status="failed",
                    error=f"Воркспейс недоступен: {workspace_id}",
                    finished_at=time.time(),
                )
                return
            config.base_dir = str(workspace.resolved())
            config.access = _access_level(workspace.access)
            config.autonomy = _autonomy(workspace.autonomy)
            config.escalation = _escalation(workspace.escalation)
            config.max_steps = workspace.max_steps
            # Список защищённых имён живёт в воркспейсе, но guard его не видел:
            # объявление «`.env` защищён» было обещанием без исполнения, и агент
            # читал и писал секреты внутри своего же воркспейса.
            protected = list(workspace.protected)

        # «Только план» выставляем до make_guard: тот копирует autonomy в
        # guard по значению, и опоздавшая правка config уже ничего не меняла.
        # Агент смотрит именно на guard.autonomy, поэтому галочка молча
        # не работала: агент выполнял инструменты вместо плана на одобрение.
        if payload.get("plan_only"):
            config.autonomy = Autonomy.PLAN

        guard = make_guard(config)
        if protected:
            guard.protected = protected
        if workspace_id:
            # Граница воркспейса не зависит от уровня доступа. Мягкая по
            # умолчанию: за её пределами агент не пишет молча, а спрашивает.
            guard.set_workspace(
                config.base_dir, workspace_id,
                granted=self.store.granted_paths(task_id=task["id"]),
                denied=self.store.denied_paths(task_id=task["id"]),
                soft_boundary=bool(payload.get("soft_boundary", self.soft_boundary)),
            )

        agent = Agent(
            self.selector, guard, config,
            on_event=lambda event: self._on_agent_event(task["id"], event),
        )
        agent.set_task(task["task"])
        self._agent = agent

        if payload.get("images"):
            self._attach_images(agent, payload["images"])
        if payload.get("plan_only"):
            agent.config.autonomy = Autonomy.PLAN

        # Режим работы решается до сборки агента: от него зависит и промпт,
        # и набор инструментов, а они собираются в set_task.
        web_research = bool(payload.get("web_research"))
        subagents = int(payload.get("subagents") or 0)
        if payload.get("auto_mode"):
            decision = run(self.loop, self._choose_mode(task["task"]))
            web_research = decision.web_research
            subagents = decision.subagents
            self.emit({
                "type": "mode_chosen",
                "task_id": task["id"],
                **decision.to_dict(),
            })

        # Правка собственного кода zagent. Флаг живёт в задаче, а не во
        # воркспейсе: включается на одну задачу и умирает вместе с ней.
        # Иначе «режим разработки» однажды остался бы включённым навсегда, и
        # агент правил бы программу без спроса — ровно то, чего мы избегаем.
        if payload.get("self_edit"):
            agent.self_edit = True
            # Системный промпт уже собран в set_task, а флаг включили позже —
            # без пересборки модель не узнала бы, что ей разрешено трогать код.
            agent.rebuild_system_prompt()
            self.emit({
                "type": "self_edit_on",
                "task_id": task["id"],
                "workspace": config.base_dir,
                "note": "Агент будет менять код zagent",
            })

        # Веб-разведка: поиск и чтение страниц. Флаг тоже живёт в задаче.
        # Инструменты появляются в каталоге только вместе с ним: в обычной
        # задаче поиск в интернете не нужен и только тратит токены.
        if web_research:
            agent.web_research = True
            agent.rebuild_system_prompt()
        if subagents:
            agent.subagents = subagents
            # След работы включаем только для субагентов: там человек
            # смотрит, что именно делает каждая часть. В обычной задаче
            # следа нет, и в журнал уходит меньше данных.
            agent.trace_on = True

        # Продолжение после вопроса пользователя: восстанавливаем диалог
        # из чекпоинта, а не начинаем задачу заново.
        resumed = False
        checkpoint = payload.get("checkpoint")
        if checkpoint and agent.restore_checkpoint(checkpoint):
            resumed = True
        if payload.get("approve_plan") and agent.plan:
            agent.approve_plan()
        elif payload.get("resume_answer"):
            agent.answer_question(str(payload["resume_answer"]))
        if payload.get("grant_path"):
            # Разрешение пользователя на выход за воркспейс: расширяем
            # границу до конкретного пути и просим агента повторить операцию.
            # Агент живёт в loop воркера, поэтому корутину уходит туда же.
            run(self.loop, agent.grant_permission(str(payload["grant_path"])))
        if payload.get("deny_path"):
            # Отказ: запоминаем путь как запрещённый, чтобы агент не спросил
            # его повторно, и говорим ему искать другой способ.
            run(self.loop, agent.deny_permission(str(payload["deny_path"])))
        if payload.get("cancel") or self._take_cancel(task["id"]):
            # Отмена могла прийти, пока задача собиралась. Флаг из БД к этому
            # моменту уже сброшен, поэтому берём и его, и свою отметку.
            agent.request_cancel()

        started = time.perf_counter()
        # В колонку идёт метка времени, а не монотонный счётчик: `claim_task`
        # и `finished_at` пишут `time.time()`, и две колонки в разных единицах
        # ломали любую сортировку по началу задачи и подсчёт длительности.
        self.store.update_task(task["id"], started_at=time.time())
        self.emit({"type": "started", "task_id": task["id"], "task": task["task"],
                   "resumed": resumed, "subagents": subagents})

        # Субагенты: сначала главный агент делит задачу, потом части идут
        # параллельно, потом главный собирает результат. Разбиение и сборка —
        # по одному запросу; остальное делают части.
        #
        # Результат кладётся в тот же `result`, что и у обычного цикла:
        # хвост задачи (статус, чекпоинт, событие finished) не должен
        # разъезжаться между двумя путями, иначе по одному из них
        # задача осталась бы в статусе running навсегда.
        if subagents:
            result = run(self.loop, self._run_swarm(
                task, agent, config, subagents, payload.get("images")))
            duration = int((time.perf_counter() - started) * 1000)
        else:
            # Потолок одной задачи. Раньше TimeoutError отсюда уходил в общий
            # обработчик, а задача оставалась в статусе running навсегда: до
            # перезапуска программы. Теперь она честно помечается сбойной.
            #
            # Задача с картинками требует модель, которая их видит, и фильтр
            # vision ставится на время задачи. Общий `require_vision` из
            # настроек трогать нельзя: он живёт до перезапуска, и все
            # следующие задачи поедут по vision-моделям, а те медленнее —
            # задача без картинок станет ждать того же тридцатисекундного
            # ответа зря. Тесты подставляют вместо селектора заглушку,
            # поэтому проверка на сам факт объекта: у настоящего селектора
            # поле есть всегда, и молча пропустить его — значит забыть про
            # vision.
            selector = self.selector
            can_switch = selector is not None and hasattr(selector, "require_vision")
            had_vision = bool(selector.require_vision) if can_switch else False
            if payload.get("images") and not had_vision and can_switch:
                selector.require_vision = True
            try:
                future = asyncio.run_coroutine_threadsafe(agent.run(), self.loop)
                try:
                    result = future.result(timeout=AGENT_TIMEOUT_S)
                except concurrent.futures.TimeoutError:
                    future.cancel()
                    agent.request_cancel()
                    self.store.update_task(
                        task["id"],
                        status="failed",
                        error=(
                            f"Задача не уложилась в {AGENT_TIMEOUT_S // 60} минут "
                            "и была остановлена"
                        ),
                        finished_at=time.time(),
                    )
                    self.store.drop_permissions(
                        task_id=task["id"], reason="задача превысила время")
                    self.emit({
                        "type": "finished", "task_id": task["id"], "status": "failed",
                        "result": {"ok": False,
                                   "last": f"Задача превысила время ({AGENT_TIMEOUT_S} с)"},
                        "artifacts": list(getattr(agent, "artifacts", []) or []),
                        "workspace": str(config.base_dir),
                    })
                    return
            finally:
                if can_switch:
                    selector.require_vision = had_vision
            duration = int((time.perf_counter() - started) * 1000)

        # Запрос на выход за воркспейс: сохраняем его отдельно, чтобы
        # интерфейс показал диалог с кнопками и ждал ответа.
        permission_id = None
        pending = result.get("pending_permission")
        if pending:
            permission_id = self.store.add_permission(
                operation=str(pending.get("operation") or ""),
                path=str(pending.get("path") or ""),
                workspace=str(config.base_dir),
                reason=str(pending.get("question") or ""),
                task_id=task["id"],
            )
            self.emit({
                "type": "permission_requested",
                "task_id": task["id"],
                "permission_id": permission_id,
                "path": pending.get("path"),
                "operation": pending.get("operation"),
                "question": pending.get("question"),
            })

        if result.get("cancelled"):
            status = "cancelled"
        elif result.get("ok"):
            status = "done"
        elif permission_id is not None:
            status = "waiting_permission"
        elif result.get("pending_question"):
            status = "asking"
        else:
            status = "failed"

        # Чекпоинт сохраняем в payload, чтобы следующий вопрос продолжил ту же
        # сессию, а не новую.
        next_payload = dict(payload)
        next_payload.pop("resume_answer", None)
        next_payload.pop("approve_plan", None)
        next_payload.pop("grant_path", None)
        next_payload.pop("deny_path", None)
        next_payload["cancel"] = False
        if status in ("asking", "waiting_permission"):
            next_payload["checkpoint"] = result.get("checkpoint") or agent.checkpoint
        if permission_id is not None:
            next_payload["permission_id"] = permission_id

        self.store.update_task(
            task["id"],
            status=status,
            finished_at=time.time(),
            steps=int(result.get("steps") or 0),
            duration_ms=duration,
            models=",".join(result.get("models_used") or []),
            result=result,
            payload=next_payload,
            error=None if status in ("done", "asking", "waiting_permission")
            else (result.get("last") or None),
        )
        self.emit({
            "type": "finished",
            "task_id": task["id"],
            "status": status,
            "result": result,
            # Созданные файлы — с ними интерфейс показывает готовые ссылки
            # в ответе агента, и результат открывается в один клик.
            "artifacts": list(getattr(agent, "artifacts", []) or []),
            "workspace": str(config.base_dir),
        })

    def _attach_images(self, agent: Agent, images: list[Any]) -> None:
        """Прикрепить картинки к задаче."""
        urls = [
            item["data_url"] for item in images
            if isinstance(item, dict) and item.get("data_url")
        ]
        if not urls:
            return
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": "Выполни задачу с учётом изображения:"}
        ]
        for url in urls:
            parts.append({"type": "image_url", "image_url": {"url": url}})
        agent.config.require_vision = True
        agent.messages.append({"role": "user", "content": parts})

    def _on_agent_event(self, task_id: int, event: dict[str, Any]) -> None:
        """Событие агента: пишем в журнал и обновляем состояние моделей."""
        # Проставляем session_id: без него SSE-поток не может отфильтровать
        # чужие события, и перезагрузка вкладки дописывала в переписку шаги
        # из прошлых сессий.
        event = {**event, "task_id": task_id, "at": time.time()}
        if "session_id" not in event:
            event["session_id"] = self._session_of_task(task_id)
        self.emit(event)

        if event.get("type") == "step":
            step = event.get("step") or {}
            if step.get("model") and self.selector is not None:
                state = self.selector.states.get(step["model"])
                if state is not None and state.last_status != "unknown":
                    self.store.touch_models(
                        step["model"], state.last_status, error=state.last_error,
                        cooldown_until=state.cooldown_until, fails=state.fails,
                        ok_count=state.ok_count, avg_ms=state.avg_ms,
                    )

    def _session_of_task(self, task_id: int) -> str | None:
        """Какой сессии принадлежит задача.

        Нужен, чтобы помечать события: переписка принадлежит сессии, а
        `add_event` хранит только `task_id`.
        """
        if self.current_task_id != task_id:
            # Задача уже завершилась, а событие пришло в её `finally`.
            return None
        return self.store.active_session_id()

    def emit(self, event: dict[str, Any]) -> None:
        """Записать событие в журнал и разослать подписчикам SSE.

        Подписчик — обычная функция, вызываемая из потока воркера. Она обязана
        быть быстрой и не бросать исключений; SSE-поток кладёт событие в очередь.
        """
        try:
            self.store.add_event(event, task_id=event.get("task_id"))
        except Exception:
            pass  # журнал не должен ронять работу

        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:
                pass

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Подписаться на события. Возвращает функцию отписки."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def permissions(self) -> dict[str, Any]:
        """Неотвеченные запросы на выход за воркспейс."""
        return {"ok": True, "permissions": self.store.pending_permissions()}

    def answer_permission(self, permission_id: int, allow: bool, *,
                          scope: str = "once") -> dict[str, Any]:
        """Ответить на запрос о доступе вне воркспейса.

        Разрешение возвр��щает задачу в очередь: агент восстановит диалог
        из чекпоинта и повторит операцию уже с разрешённым путём.
        """
        request = self.store.decide_permission(permission_id, allow, scope=scope)
        if request is None:
            return {"ok": False, "error": "Запрос не найден"}

        task_id = request.get("task_id")
        if task_id is None:
            return {"ok": True, "permission": request}

        task = self.store.get_task(int(task_id))
        if task is None:
            return {"ok": True, "permission": request}

        payload = dict(task.get("payload") or {})
        if allow:
            payload["grant_path"] = request.get("path") or ""
        else:
            # Отказ тоже нужно донести до агента: иначе он повторит тот же
            # вызов, снова упрётся в границу и запросит то же самое.
            payload["deny_path"] = request.get("path") or ""
        payload["permission_id"] = None
        payload["cancel"] = False

        self.store.update_task(
            int(task_id), status="queued", payload=payload,
            finished_at=None, result=None, error=None,
        )
        self.emit({
            "type": "permission_decided", "task_id": task_id,
            "permission_id": permission_id, "allow": allow, "scope": scope,
            "path": request.get("path"),
        })
        return {"ok": True, "permission": request, "task_id": task_id}

    # --------------------------------------------------- мягкая граница воркспейса

    def set_base_dir(self, path: str) -> None:
        """Сменить рабочую папку. Только папка из списка воркспейсов.

        Ограничение не формальное. `base_dir` — это граница доступа всего
        сервера: по ней `/api/files` строит дерево, `/api/shot` пишет снимки,
        а агент получает корень для `Guard`. Значение приходит от клиента без
        аутентификации, поэтому произвольный путь означал бы чтение любого
        файла на диске (`POST /api/config {"base_dir":"C:/Users/HP"}`, затем
        `/api/files {"path":".ssh/id_rsa"}`).
        """
        target = Path(path).expanduser()
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise ValueError(f"Не удалось разобрать путь: {exc}") from exc

        for workspace in self.workspaces.items:
            try:
                if workspace.resolved() == resolved:
                    self.config.base_dir = str(resolved)
                    return
            except OSError:
                continue

        known = ", ".join(w.path for w in self.workspaces.items)
        raise ValueError(
            f"Папка не входит в список воркспейсов: {resolved}. "
            f"Добавьте её кнопкой «выбрать папку». Сейчас доступны: {known}"
        )

    def set_soft_boundary(self, enabled: bool) -> dict[str, Any]:
        """Разрешать ли агенту выходить за воркспейс по запросу.

        True (по умолчанию): агент спрашивает, пользователь решает.
        False: жёсткая граница, выход невозможен.
        """
        self.soft_boundary = bool(enabled)
        self.store.set_meta("soft_boundary", self.soft_boundary)
        self.emit({"type": "boundary", "soft": self.soft_boundary})
        return {"ok": True, "soft_boundary": self.soft_boundary}

    # ---------------------------------------------------------------- ответы

    def answer(self, task_id: int, text: str, *, approve: bool = False) -> dict[str, Any]:
        """Ответить на вопрос агента по задаче.

        Агент живёт только во время выполнения задачи, поэтому ответ работает
        так: чекпоинт диалога из payload кладётся обратно и задача
        переочередивается. Воркер восстановит контекст и продолжит с него.
        """
        task = self.store.get_task(task_id)
        if task is None:
            return {"ok": False, "error": "Задача не найдена"}
        if task["status"] not in ("asking", "failed"):
            return {"ok": False, "error": f"задача в статусе {task['status']}, ждёт ответа"}

        payload = dict(task.get("payload") or {})
        payload["resume_answer"] = text
        if approve:
            payload["approve_plan"] = True
        payload["cancel"] = False
        self.store.update_task(task_id, status="queued", payload=payload)
        self.emit({"type": "requeued", "task_id": task_id, "answer": text, "approve": approve})
        return {"ok": True, "task_id": task_id}

    # ------------------------------------------------------------------ пинг

    def ping(self, ref: str | None = None) -> dict[str, Any]:
        """Живой пинг одной модели или всех."""

        async def job() -> dict[str, Any]:
            if self.registry is None:
                await self._bootstrap()
            if self.registry is None:
                raise RuntimeError(self.last_error or "реестр не загружен")

            if ref:
                targets = [m for m in self.registry.chat_models if m.ref == ref]
                if not targets:
                    raise ValueError(f"Модель не найдена: {ref}")
            else:
                targets = self.registry.chat_models

            # При ручном пинге одной модели шлём живой прогресс: запрос
            # занимает до 90 секунд, и без обратной связи он выглядит как
            # зависшая программа.
            def on_progress(ev: dict[str, Any]) -> None:
                if not ref:
                    return
                self.emit({"type": "ping_progress", **ev})

            probes = await probe_models(
                self.gateways, targets, timeout=90.0,
                prompt=PING_PROMPT, max_tokens=PING_MAX_TOKENS,
                on_progress=on_progress,
            )
            self.probes.update(probes)
            self._refresh_snapshot()
            self.store.save_probes(probes)
            self._note_recovery(probes)

            if self.selector is not None:
                for model_ref, probe in probes.items():
                    state = self.selector.states.get(model_ref)
                    if state is None:
                        continue
                    self.selector.record(
                        model_ref, probe.get("status") or "down",
                        error=probe.get("error"),
                        duration_ms=probe.get("duration_ms") or 0,
                    )
                self.store.save_models(self.selector.states)
            self.ping_last = time.time()
            self.ping_running = False
            self._push_ping_history(probes)
            return {"ok": True, "pinged": len(probes), "results": probes}

        # Два пинга одновременно делили бы квоту между собой и мешали друг
        # другу: провайдер считает лимиты на аккаунт, а не на запрос.
        if self.ping_running:
            return {"ok": False, "error": "пинг уже идёт"}
        self.ping_running = True
        try:
            return run(self.loop, job())
        except BaseException:
            self.ping_running = False
            raise

    def _note_recovery(self, probes: dict[str, dict[str, Any]]) -> None:
        """Отметить модель, которая ожила после лимита.

        Смысл автоматического пинга именно в этом: модель вчера была
        недоступна, сейчас отвечает. Пользователь должен узнать об этом без
        нажатий — иначе он считает, что у него одна рабочая модель.
        """
        if self.selector is None:
            return
        for ref, probe in probes.items():
            state = self.selector.states.get(ref)
            if state is None:
                continue
            now_ok = (probe.get("status") or "") in ("ok", "slow")
            was_bad = state.last_status in ("limited", "down", "empty")
            if now_ok and was_bad:
                self.recovered[ref] = self.recovered.get(ref, 0) + 1
                self.emit({
                    "type": "recovered",
                    "ref": ref,
                    "model": state.model,
                    "was": state.last_status,
                })

    def _push_ping_history(self, probes: dict[str, dict[str, Any]]) -> None:
        """Оставить след: кто отвечал в последнем замере."""
        ok = sum(1 for p in probes.values() if (p.get("status") or "") in ("ok", "slow"))
        entry = {
            "at": time.time(),
            "checked": len(probes),
            "ok": ok,
            "results": {
                ref: {"status": probe.get("status"),
                      "ms": probe.get("duration_ms") or 0}
                for ref, probe in probes.items()
            },
        }
        self.ping_history.append(entry)
        # История нужна для сравнения «тогда и сейчас», а не как журнал:
        # двадцать замеров на 38 моделей — это уже не список, а шум.
        del self.ping_history[:-8]
        self.emit({"type": "ping_done", **entry})

    def ping_status(self) -> dict[str, Any]:
        """Состояние автоматической проверки моделей."""
        since = time.time() - self.ping_last if self.ping_last else None
        return {
            "ok": True,
            "running": self.ping_running,
            "interval": PING_INTERVAL,
            "last": self.ping_last,
            "since": since,
            "next_in": max(0.0, PING_INTERVAL - since) if since is not None else None,
            "history": self.ping_history[-4:],
            "recovered": dict(self.recovered),
        }

    # ------------------------------------------------- автоматическая проверка

    def start_background_ping(self) -> None:
        """Планировщик фонового пинга.

        Отдельный поток, а не задача в loop воркера: пинг занимает минуты и
        выполняется сетью, а очередь задач должна продолжать работать.
        """

        def loop_body() -> None:
            while True:
                time.sleep(30.0)
                try:
                    if self.ping_running or self.ping_last and \
                            time.time() - self.ping_last < PING_INTERVAL:
                        continue
                    if self.selector is None or self.registry is None:
                        continue
                    self._ping_unavailable()
                except Exception as exc:  # noqa: BLE001
                    # Планировщик не должен умирать из-за одного сбоя: иначе
                    # автопинг молча отключается навсегда.
                    self.ping_running = False
                    self.emit({"type": "ping_error",
                               "error": f"{type(exc).__name__}: {exc}"})

        thread = threading.Thread(target=loop_body, name="zagent-ping", daemon=True)
        thread.start()

    def _ping_unavailable(self) -> None:
        """Проверить модели, которые сейчас не отвечают.

        Ответившие не трогаются: их состояние и так актуально, а каждый
        лишний запрос к живой модели приближает момент, когда она уйдёт в
        лимит.
        """
        if self.registry is None or self.selector is None:
            return
        interesting: list[Any] = []
        for model in self.registry.chat_models:
            state = self.selector.states.get(model.ref)
            if state is None:
                continue
            if state.last_status in ("ok", "slow"):
                continue
            interesting.append(model)
        # Больше N моделей за раз не берём: иначе цикл пинга займёт больше
        # интервала и будет мешать сам себе.
        interesting = interesting[:PING_MAX_BACKGROUND]
        if not interesting:
            self.ping_last = time.time()
            return

        self.ping_running = True
        try:
            probes = run(self.loop, self._probe_job(interesting))
        finally:
            self.ping_running = False
        self.ping_last = time.time()
        self._push_ping_history(probes)
        self._note_recovery(probes)

    async def _probe_job(self, targets: list[Any]) -> dict[str, dict[str, Any]]:
        """Собственно проба: записать результаты и обновить селектор."""
        probes = await probe_models(
            self.gateways, targets, timeout=60.0,
            prompt=PING_PROMPT, max_tokens=PING_MAX_TOKENS,
            concurrency=3,
        )
        self.probes.update(probes)
        self._refresh_snapshot()
        self.store.save_probes(probes)
        if self.selector is not None:
            for ref, probe in probes.items():
                state = self.selector.states.get(ref)
                if state is None:
                    continue
                self.selector.record(
                    ref, probe.get("status") or "down",
                    error=probe.get("error"),
                    duration_ms=probe.get("duration_ms") or 0,
                )
            self.store.save_models(self.selector.states)
        return probes

    # ------------------------------------------------------- доступность из РФ

    def region_status(self) -> dict[str, Any]:
        """Текущее состояние замеров: что уже измерено и что можно нажать."""
        return {
            "ok": True,
            "running": self.geo_running,
            "mode": self.geo_mode,
            "progress": dict(self.geo_progress),
            "log": list(self.geo_log[-40:]),
            "summary": region_summary(self.regions),
            "direct_measured": len(self.regions.measured()),
        }

    def measure_region(self, mode: str) -> dict[str, Any]:
        """Запустить замер доступности в фоне.

        mode: MODE_DIRECT (VPN выключен) или MODE_VPN (VPN включён).

        Замер идёт в loop воркера и занимает минуты, поэтому возвращаем сразу,
        а прогресс приходит событиями. Один замер не стирает другой: сырые
        пробы хранятся по режимам, вердикт собирается из пары.
        """
        if mode not in (MODE_DIRECT, MODE_VPN):
            return {"ok": False, "error": f"неизвестный режим: {mode}"}
        if self.geo_running:
            return {"ok": False, "error": "Замер уже идёт. Дождитесь конца."}
        if self.selector is None or self.registry is None:
            return {"ok": False, "error": "Реестр не загружен, нажмите «Обновить»"}

        self.geo_running = True
        self.geo_mode = mode
        self.geo_log = []
        self.geo_progress = {"done": 0, "total": 0, "current": "", "phase": "старт"}
        self.emit({"type": "geo_start", "mode": mode})

        async def job() -> dict[str, Any]:
            models = list(self.registry.chat_models)
            self.geo_progress["total"] = len(models)
            self.geo_progress["phase"] = "проверка"

            def progress(info: dict[str, Any]) -> None:
                kind = info.get("kind")
                if kind == "checking":
                    self.geo_progress["current"] = str(info.get("model") or "")
                elif kind == "model":
                    self.geo_progress["done"] = int(info.get("done") or 0)
                    self.geo_progress["current"] = str(info.get("model") or "")
                elif kind in ("pause", "retry"):
                    self.geo_progress["phase"] = (
                        "пауза между шлюзами" if kind == "pause" else "повтор 429"
                    )
                self.emit({"type": "geo_progress", "mode": mode, **info})

            try:
                probes = await probe_models(
                    self.gateways, models,
                    timeout=45.0, per_gateway_pause=1.5,
                    on_progress=progress,
                )
                self.probes.update(probes)
                self.store.save_probes(probes)

                for model in models:
                    probe = probes.get(model.ref) or {}
                    status = str(probe.get("status") or "down")
                    entry = self.regions.record(model.ref, mode, status)
                    self._note_region(model, status, entry)
                    state = self.selector.states.get(model.ref)
                    if state is not None:
                        self.selector.record(model.ref, status,
                                             error=probe.get("error"),
                                             duration_ms=int(probe.get("duration_ms") or 0))
                self.store.save_models(self.selector.states)
                self._apply_vpn_preference()
                self._refresh_snapshot()
                self.regions.save()
                return {"ok": True, "measured": len(models)}
            finally:
                self.geo_running = False
                self.geo_progress["phase"] = "готово"
                self.emit({
                    "type": "geo_done", "mode": mode,
                    "summary": region_summary(self.regions),
                })

        async def wrapper() -> None:
            try:
                result = await job()
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            self.emit({"type": "geo_finished", "mode": mode, **result})

        self.loop.create_task(wrapper())
        return {"ok": True, "mode": mode, "started": True,
                "total": len(self.registry.chat_models)}

    def _note_region(self, model: Any, status: str, entry: Any) -> None:
        """Человеческое пояснение к вердикту, а не только значок."""
        reason = ""
        if status == "blocked" and mode_is_direct(self.geo_mode):
            reason = "провайдер отказал (403)"
        elif status == "limited":
            reason = "лимит запросов, но шлюз отвечает"
        elif status == "down" and mode_is_direct(self.geo_mode):
            reason = "не отвечает без VPN"
        if reason:
            self.geo_log.append(f"{model.ref}: {reason}")

    def scan(self) -> dict[str, Any]:
        """Пересобрать каталог шлюзов."""

        async def job() -> dict[str, Any]:
            self.gateways = load_gateways(self.root, env={})
            self.registry = await collect(self.gateways, root=self.root)
            self.selector = selector_from_registry(
                self.registry, root=str(self.root),
                mode=self.selector.mode.value if self.selector else "auto",
                manual_ref=self.selector.manual_ref if self.selector else None,
                prefer_speed=self.config.prefer_speed,
                require_vision=self.config.require_vision,
            )
            self._restore_model_state()
            self._refresh_snapshot()
            return {"ok": True, "models": len(self.registry.chat_models)}

        return run(self.loop, job())

    def sanity(self, ref: str | None = None, lang: str = "ru") -> dict[str, Any]:
        """Проверка адекватности."""
        from hub.sanity import build_probe_prompt, evaluate
        from providers.openai_compat import OpenAICompatProvider
        import httpx

        async def job() -> dict[str, Any]:
            if self.registry is None:
                raise RuntimeError("реестр не загружен")
            system, user, token = build_probe_prompt(lang)
            targets = (
                [m for m in self.registry.chat_models if m.ref == ref] if ref
                else self.registry.chat_models
            )
            reports: dict[str, dict[str, Any]] = {}
            for model in targets:
                gateway = next(
                    (g for g in self.gateways if g["id"] == model.gateway_id), None
                )
                if gateway is None:
                    continue
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    # Ключ по кругу: проверка всех 38 моделей на одном
                    # аккаунте выбила бы лимит OpenRouter на середине.
                    check_key = gateway_key(gateway)
                    provider = OpenAICompatProvider(
                        model.gateway_id, gateway["resolved_url"], check_key,
                        timeout=90.0, client=client,
                    )
                    result = await provider.chat(
                        model.model_id,
                        [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
                        temperature=0, max_tokens=400,
                    )
                duration = int(result.get("duration_ms") or 0)
                if result.get("error"):
                    # Ошибка одного аккаунта не должна уводить модель из
                    # реестра: остальные ключи шлюза ещё свободны.
                    note_gateway_error(gateway, check_key, str(result["error"]))
                else:
                    note_gateway_ok(gateway, check_key)
                    reports[model.ref] = {
                        "ref": model.ref, "score": 0.0, "verdict": "unreachable",
                        "latency_ms": duration, "sample": "",
                        "checks": [{"name": "reachable", "passed": False,
                                    "detail": str(result["error"]), "score": 0.0}],
                    }
                    continue
                answer = str(result.get("text") or result.get("reasoning") or "")
                reports[model.ref] = evaluate(
                    model.ref, answer, question=user, token=token,
                    duration_ms=duration, lang=lang,
                ).to_dict()
            self.sanity.update(reports)
            self.store.save_sanity(reports)
            good = sum(1 for r in reports.values() if r["verdict"] in ("good", "usable"))
            return {"ok": True, "checked": len(reports), "good": good, "reports": reports}

        return run(self.loop, job())

    # ---------------------------------------------------------------- снимок

    def state(self) -> dict[str, Any]:
        candidates = []
        if self.selector is not None:
            for row in self.selector.candidates():
                ref = row["ref"]
                candidates.append({
                    **row,
                    "probe": self.probes.get(ref) or {},
                    "sanity": self.sanity.get(ref) or {},
                    # Доступность из России показываем рядом с моделью, а не
                    # отдельной вкладкой: решать приходится в момент выбора.
                    "region": self.regions.describe(ref),
                })
        counts = self.store.task_counts()
        # Показываем действующий уровень доступа, а не только общий: настройки
        # активного воркспейса перекрывают общие, и иначе переключатель в
        # интерфейсе показывал бы не то, что реально применяется.
        effective = self.config.to_dict()
        active = self.workspaces.active
        effective["access"] = int(active.access)
        effective["autonomy"] = active.autonomy
        effective["escalation"] = active.escalation
        effective["max_steps"] = int(active.max_steps)
        return {
            "gateways": self.snapshot.get("gateways", []),
            "models": self.snapshot.get("models", []),
            "candidates": candidates,
            # Режим и выбранная модель. Раньше интерфейс брал их из stats(),
            # а оттуда они не приходили: переключатель режима показывал «auto»
            # при ручном выборе, и выбранную модель было негде увидеть.
            "selector": self._selector_state(),
            "stats": self.selector.stats() if self.selector else {},
            # Ключи по шлюзам: сколько аккаунтов подключено, сколько выбито.
            # Для планирования субагентов это главное: мощность считается
            # не моделями, а свободными аккаунтами.
            "keys": self.key_stats(),
            # Состояние автопинга. Без него в интерфейсе вечно горело
            # «следующая проверка через —»: сведения приходили только из
            # события по завершении пинга, а до него отсчёта не было.
            "ping": self.ping_status(),
            "status_counts": self.snapshot.get("status_counts", {}),
            "generated_at": self.snapshot.get("generated_at"),
            "tasks": self.store.list_tasks(limit=30),
            "task_counts": counts,
            "permissions": self.store.pending_permissions(),
            "session": self.store.active_session_id(),
            "sessions": self.store.list_sessions(self.workspaces.active_id),
            "permissions": self.store.pending_permissions(),
            "current_task": self.current_task_id,
            "paused": self.paused,
            "config": effective,
            "workspaces": self.workspaces.describe(),
            "soft_boundary": self.soft_boundary,
            "last_error": self.last_error,
            "store": self.store.stats(),
            "regions": region_summary(self.regions),
            "region": self.region_status(),
        }

    def configure(self, **fields: Any) -> dict[str, Any]:
        """Изменить настройки воркера.

        Уровень доступа, автономию, эскалацию и лимит шагов применяем и к
        активному воркспейсу: настройки воркспейса перекрывают общие, поэтому
        иначе выбор «полный доступ» в интерфейсе выглядел бы рабочим, а на
        деле игнорировался бы.
        """
        workspace_fields: dict[str, Any] = {}
        if "access" in fields:
            self.config.access = AccessLevel(int(fields["access"]))
            workspace_fields["access"] = int(self.config.access)
        if "autonomy" in fields:
            self.config.autonomy = Autonomy(str(fields["autonomy"]))
            workspace_fields["autonomy"] = self.config.autonomy.value
        if "escalation" in fields:
            self.config.escalation = Escalation(str(fields["escalation"]))
            workspace_fields["escalation"] = self.config.escalation.value
        if "base_dir" in fields and fields["base_dir"]:
            # base_dir определяет, какие файлы вообще видит программа:
            # `/api/files` ограничивается им, а `/api/shot` пишет туда.
            # Принимать отсюда любой путь нельзя — неаутентифицированный клиент
            # выбрал бы `C:/Users/HP` и прочитал что угодно. Разрешены только
            # папки из списка воркспейсов.
            self.set_base_dir(str(fields["base_dir"]))
        if "max_steps" in fields:
            self.config.max_steps = int(fields["max_steps"])
            workspace_fields["max_steps"] = int(self.config.max_steps)
        if "prefer_speed" in fields:
            self.config.prefer_speed = bool(fields["prefer_speed"])
        if "require_vision" in fields:
            self.config.require_vision = bool(fields["require_vision"])
        if "avoid_vpn" in fields:
            self.config.avoid_vpn = bool(fields["avoid_vpn"])
        if "soft_boundary" in fields:
            self.soft_boundary = bool(fields["soft_boundary"])
            self.store.set_meta("soft_boundary", self.soft_boundary)

        if workspace_fields:
            try:
                self.workspaces.update(self.workspaces.active_id, **workspace_fields)
            except Exception as exc:  # воркспейс мог быть удалён
                self.last_error = f"не удалось применить к воркспейсу: {exc}"

        if self.selector is not None:
            self.selector.prefer_speed = self.config.prefer_speed
            self.selector.require_vision = self.config.require_vision
        self._apply_vpn_preference()
        self.store.set_meta("config", self.config.to_dict())
        return {
            "ok": True,
            "config": self.config.to_dict(),
            "workspaces": self.workspaces.describe(),
        }

    def _selector_state(self) -> dict[str, Any]:
        """Режим выбора модели и текущая модель — для интерфейса.

        Отдельный метод, а не чтение stats(): stats() описывает состояние
        моделей (сколько ok, в карантине) и про выбранную модель не знает.
        Без этого блока переключатель «auto / ручной выбор» не показывал
        фактическое состояние.
        """
        if self.selector is None:
            return {"mode": "auto", "manual_ref": None, "current": None,
                    "total": 0, "available": 0}
        return {
            "mode": self.selector.mode.value,
            "manual_ref": self.selector.manual_ref,
            "current": self.selector.current,
            "total": len(self.selector.states),
            # Модели, которыми агент может пользоваться прямо сейчас: без
            # карантина и блокировок. Именно их стоит показывать как рабочие.
            "available": sum(
                1 for state in self.selector.states.values()
                if not state.blocked and not state.cooldown_left
            ),
        }

    async def _choose_mode(self, task: str) -> Any:
        """Решить, как выполнять задачу: моделью, потом по признакам.

        Возвращает `Decision`. Ошибка не поднимается: худшее, что может
        случиться, — задача выполнится в обычном режиме. Режим, который
        не удалось выбрать, уронил бы задачу на ровном месте.
        """
        from hub.autochoose import Decision, Limits, choose

        free = self._free_accounts()
        limits = Limits(free_accounts=free, max_steps=self.config.max_steps)
        # Про `self_edit` тут ни слова намеренно: правку собственного кода
        # «Авто» включить не имеет права никогда, она приходит только из
        # задачи, то есть от человека.
        try:
            caller = AutoCaller(self.selector, timeout=60.0, empty_retries=1)
            return await choose(task, caller, limits=limits)
        except Exception as exc:
            self.emit({
                "type": "mode_chosen",
                "task_id": self.current_task_id,
                "web_research": False, "subagents": 0,
                "reason": f"режим не выбран: {type(exc).__name__}",
                "source": "default", "model": "", "mode": "обычный",
            })
            return Decision()

    def _free_accounts(self) -> int:
        """Сколько аккаунтов свободно прямо сейчас."""
        total = 0
        for stats in KEY_RING.snapshot().values():
            total += int(stats.get("available") or 0)
        return total

    async def _run_swarm(self, task: dict[str, Any], agent: Agent,
                         config: AgentConfig, wanted: int,
                         images: list[str] | None = None,
                         decider: Any = None) -> dict[str, Any]:
        """Разбить задачу, выполнить части параллельно, собрать результат.

        Порядок именно такой, и каждый шаг виден человеку:

        1. разбиение — один запрос, части с их областями файлов;
        2. выбор моделей — осознанный, с записанной причиной;
        3. параллельный запуск частей, у каждой своя модель и свои запреты;
        4. сборка — главный агент получает результаты частей целиком и
           отвечает сам.

        Если разбить не удалось, задача выполняется обычным способом: хуже
        медленно, чем не выполнено.
        """
        from hub.assign import assign_all, collect_candidates
        from hub.keyring import REGISTRY as RING
        from hub.subagents import (
            SPLIT_SYSTEM,
            denied_for_all,
            globs_for_all,
            parse_parts as _parse_parts,
            part_brief_for_ui,
            run_parts,
            scope_paths,
            summary_for,
        )

        task_id = int(task["id"])
        text = str(task["task"])
        base = Path(config.base_dir)

        # 1. Разбиение. Отдельный вызывающий без закреплённой модели: выбор
        # модели для разбиения ничего не значит, тут нужен любой, кто
        # умеет отвечать структурированно и быстро.
        parts = []
        if decider is None:
            decider = AutoCaller(self.selector, timeout=60.0, empty_retries=1)
        try:
            split = await decider.ask(
                [{"role": "system", "content": SPLIT_SYSTEM},
                 {"role": "user", "content": text}],
                temperature=0.0, max_tokens=1500)
            if not split.get("error"):
                parts = _parse_parts(str(split.get("text") or ""), limit=wanted)
        except Exception as exc:
            self.emit({"type": "swarm_failed", "task_id": task_id,
                       "stage": "разбиение",
                       "error": f"{type(exc).__name__}: {exc}"})

        if len(parts) < MIN_SWARM_PARTS:
            reason = ("разбить не вышло" if not parts
                      else f"получилось {len(parts)} часть, а нужно минимум {MIN_SWARM_PARTS}")
            self.emit({"type": "swarm_skipped", "task_id": task_id, "reason": reason})
            # Обычный путь: задача выполняется целиком одним агентом.
            return await agent.run()

        # 2. Выбор моделей — осознанный, с причиной по каждой части.
        candidates = collect_candidates(self.selector, RING)
        assignments = assign_all(candidates, parts, steps=agent.config.max_steps)
        denied = denied_for_all(parts, base)
        globs = globs_for_all(parts)

        for part, got in zip(parts, assignments):
            self.emit({
                "type": "part_assigned",
                "task_id": task_id,
                "sub": part.name,
                "part": part.to_dict(),
                "assignment": got.to_dict() if got else None,
            })

        # 3. Параллельный запуск. Части без назначения не запускаются:
        # ждать лимита полезнее, чем начать и бросить на середине.
        live = [part for part, got in zip(parts, assignments)
                if got is not None and got.admitted]
        # Поиск по имени, а не по равенству: две части с одинаковым
        # заголовком и файлами — это две разные части с разными запретами,
        # и по равенству они схлопывались бы в одну.
        index_of = {part.name: i for i, part in enumerate(parts)}

        def make_agent(part: Any) -> Agent:
            index = index_of[part.name]
            guard = make_guard(config)
            guard.protected = list(getattr(agent.guard, "protected", []) or [])
            guard.set_workspace(
                config.base_dir, None,
                granted=scope_paths(part.files, base),
                denied=denied[index],
                soft_boundary=bool(agent.guard.soft_boundary),
            )
            guard.denied_globs = globs[index]
            choice = assignments[index]
            part_agent = Agent(
                self.selector, guard, config,
                on_event=lambda event: self._on_part_event(
                    task_id, part.name, event),
                # Свой вызывающий с закреплённой моделью: часть отдана этой
                # модели осознанно, и первой пробуется именно она.
                caller=AutoCaller(self.selector, timeout=config.step_timeout,
                                  empty_retries=2),
            )
            part_agent.caller.pinned = choice.ref if choice else None
            return part_agent

        async def on_event(event: dict[str, Any]) -> None:
            event.setdefault("task_id", task_id)
            self.emit(event)

        started_at = time.perf_counter()
        results = await run_parts(
            live, base=base, make_agent=make_agent,
            on_event=on_event, task_context=text)
        elapsed = int((time.perf_counter() - started_at) * 1000)

        done = [slot for slot in results if slot.ok]
        self.emit({
            "type": "swarm_done", "task_id": task_id,
            "parts": len(results), "ok": len(done), "elapsed_ms": elapsed,
            "cards": [part_brief_for_ui(slot) for slot in results],
        })

        # 4. Сборка. Неудачные части уходят в сводке целиком, вместе с тем,
        # что успели: главный агент доделает их сам, и это честнее, чем
        # объявить задачу выполненной.
        summary = summary_for(results, base)
        agent.messages = [
            {"role": "system", "content": agent.messages[0]["content"]},
            {"role": "user", "content": text},
            {"role": "user", "content":
                "Части работы выполнены параллельно. Их результаты:\n\n"
                + summary + "\n\n"
                "Проверь, всё ли сделано, и закончи задачу. То, что части не "
                "успели, доделай сам. Ответь человеку: что сделано и что нет."},
        ]
        # Диалог собран заново, поэтому сбрасываем цикл: иначе агент
        # продолжил бы старую задачу, у которой уже есть `finished`, и
        # вышел бы с одним шагом, не проверив ничего.
        agent._reset_cycle()
        # Картинки достаются главному агенту, а не частям: части получают
        # текстовые задания, и та, что работает с изображением, получает
        # модель со зрением при выборе. Фильтр vision ставится только на
        # сборку — иначе он заставил бы и части без картинок работать на
        # зрящих моделях, а те втрое медленнее.
        if images:
            self._attach_images(agent, images)
            selector = self.selector
            if selector is not None and hasattr(selector, "require_vision"):
                had_vision = bool(selector.require_vision)
                selector.require_vision = True
                try:
                    result = await agent.run()
                finally:
                    selector.require_vision = had_vision
            else:
                result = await agent.run()
        else:
            result = await agent.run()
        result["swarm"] = {
            "parts": len(results), "ok": len(done),
            "elapsed_ms": elapsed,
            "cards": [part_brief_for_ui(slot) for slot in results],
        }
        return result

    def _on_part_event(self, task_id: int, part: str, event: dict[str, Any]) -> None:
        """Событие части доезжает до интерфейса с её именем.

        События всех частей идут вперемешку и почти одновременно, поэтому без
        метки в журнале нельзя понять, кто что делал: агент, который молча
        работает над своим файлом двадцать минут, выглядит сломанным.
        """
        payload = dict(event)
        payload.setdefault("sub", part)
        payload["task_id"] = task_id
        self.emit(payload)

    def key_stats(self) -> dict[str, Any]:
        """Сколько ключей подключено и сколько из них свободно.

        Показывается в интерфейсе и в отчётах. Для планирования нагрузки
        важнее не число моделей, а число живых аккаунтов: десять моделей на
        одном выбитом ключе — это ноль мощности.
        """
        snapshot = KEY_RING.snapshot()
        out: dict[str, Any] = {}
        for gateway in self.gateways:
            keys = list(gateway.get("api_keys") or [])
            if not keys:
                continue
            gid = str(gateway.get("id"))
            out[gid] = snapshot.get(
                gid, {"total": len(keys), "available": len(keys),
                      "blocked": 0, "keys": []}
            )
        out["summary"] = {
            "total_keys": sum(int(v.get("total", 0))
                               for k, v in out.items() if k != "summary"),
            "free_keys": sum(int(v.get("available", 0))
                             for k, v in out.items() if k != "summary"),
        }
        return out

    def set_mode(self, mode: str, *, manual_ref: str | None = None) -> dict[str, Any]:
        if self.selector is None:
            return {"ok": False, "error": "реестр не загружен"}
        if mode == "manual" and not manual_ref:
            return {"ok": False, "error": "укажите модель"}
        if manual_ref and manual_ref not in self.selector.states:
            return {"ok": False, "error": f"модель не найдена: {manual_ref}"}
        self.selector.set_mode(mode, manual_ref=manual_ref)
        self.store.set_meta("mode", self.selector.mode.value)
        self.store.set_meta("manual_ref", self.selector.manual_ref)
        # Возвращаем и статистику, и состояние выбора: интерфейс сразу рисует
        # отмеченную модель, не дожидаясь следующего обновления состояния.
        return {"ok": True, "stats": self.selector.stats(),
                "selector": self._selector_state()}


def run(loop: asyncio.AbstractEventLoop | None, coro: Any) -> Any:
    """Выполнить корутину в loop воркера."""
    if loop is None:
        raise RuntimeError("Воркер не запущен")
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=600)
