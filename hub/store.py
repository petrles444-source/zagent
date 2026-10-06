"""Хранилище состояния на SQLite.

Что сохраняется между перезапусками:

    models    состояние моделей: статус, карантин, средняя задержка, счётчики
    probes    результаты последнего пинга (не пинговать заново при старте)
    sanity    оценки адекватности
    tasks     очередь и история задач агента
    events    журнал событий агента
    meta      режим селектора, настройки доступа и автономии

Почему SQLite, а не JSON: запись идёт из фонового потока воркера и из HTTP-обработчиков
одновременно, а состояние нужно переживать падение процесса посреди шага.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

#: Каталог состояния (в .gitignore).
STATE_DIRNAME = "web-state"
DB_FILENAME = "zagent.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    ref            TEXT PRIMARY KEY,
    gateway        TEXT NOT NULL,
    model          TEXT NOT NULL,
    tier           INTEGER NOT NULL DEFAULT 5,
    status         TEXT NOT NULL DEFAULT 'unknown',
    error          TEXT,
    cooldown_until REAL NOT NULL DEFAULT 0,
    fails          INTEGER NOT NULL DEFAULT 0,
    ok_count       INTEGER NOT NULL DEFAULT 0,
    avg_ms         REAL NOT NULL DEFAULT 0,
    updated_at     REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS probes (
    ref         TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sanity (
    ref         TEXT PRIMARY KEY,
    score       REAL NOT NULL DEFAULT 0,
    verdict     TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    priority    INTEGER NOT NULL DEFAULT 5,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL,
    steps       INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    models      TEXT NOT NULL DEFAULT '',
    result      TEXT,
    error       TEXT,
    payload     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    at      REAL NOT NULL,
    type    TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Запросы на выход за границу воркспейса. Агент ждёт решения пользователя,
-- поэтому запрос переживает перезапуск: ответ можно дать и позже.
CREATE TABLE IF NOT EXISTS permissions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER,
    operation  TEXT NOT NULL,
    path       TEXT NOT NULL,
    workspace  TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    scope      TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    decided_at REAL
);
"""

#: Индексы создаются отдельно от таблиц и только после миграций: индекс по
#: колонке, которой в старой базе ещё нет, роняет executescript целиком.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_permissions_status ON permissions(status, id);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id, id);
"""

#: Колонки, которые добавляются к уже существующим базам. `CREATE TABLE IF
#: EXISTS` не меняет старые таблицы, поэтому новую колонку приходится добавлять
#: отдельно — иначе после обновления программа падала бы на старте.
#: Формат: (таблица, колонка, определение).
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("tasks", "session_id", "TEXT"),
)


def state_dir(root: str | Path | None = None) -> Path:
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    return base / STATE_DIRNAME


class Store:
    """Потокобезопасная обёртка над SQLite.

    Один файл, один лок на запись: воркер и HTTP-обработчики работают в разных
    потоках, и sqlite3.Connection сам по себе этому не удовлетворяет.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.dir = state_dir(root)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / DB_FILENAME
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.executescript(INDEXES)
            self._conn.commit()

    def _migrate(self) -> None:
        """Добавить недостающие колонки в базу, созданную прошлой версией.

        ALTER TABLE не умеет «если есть», поэтому наличие колонки проверяем
        сами по списку колонок таблицы.
        """
        for table, column, definition in MIGRATIONS:
            rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            existing = {row["name"] for row in rows}
            if column in existing:
                continue
            self._conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------- низкий уровень

    def _exec(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cursor

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    # ---------------------------------------------------------------- модели

    def save_models(self, states: dict[str, Any]) -> None:
        """Сохранить состояние всех моделей."""
        now = time.time()
        rows = [
            (
                state.ref,
                state.gateway,
                state.model,
                int(state.tier),
                state.last_status,
                state.last_error,
                float(state.cooldown_until),
                int(state.fails),
                int(state.ok_count),
                float(state.avg_ms),
                now,
            )
            for state in states.values()
        ]
        with self._lock:
            self._conn.executemany(
                """INSERT INTO models (ref, gateway, model, tier, status, error,
                                       cooldown_until, fails, ok_count, avg_ms, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ref) DO UPDATE SET
                       status=excluded.status, error=excluded.error,
                       cooldown_until=excluded.cooldown_until, fails=excluded.fails,
                       ok_count=excluded.ok_count, avg_ms=excluded.avg_ms,
                       updated_at=excluded.updated_at""",
                rows,
            )
            self._conn.commit()

    def load_models(self) -> dict[str, dict[str, Any]]:
        """Загрузить состояние моделей: ref -> поля состояния."""
        return {
            row["ref"]: {
                "status": row["status"],
                "error": row["error"],
                "cooldown_until": row["cooldown_until"],
                "fails": row["fails"],
                "ok_count": row["ok_count"],
                "avg_ms": row["avg_ms"],
            }
            for row in self._query("SELECT * FROM models")
        }

    def touch_models(self, ref: str, status: str, *, error: str | None = None,
                     cooldown_until: float = 0.0, fails: int = 0,
                     ok_count: int = 0, avg_ms: float = 0.0) -> None:
        """Обновить одну модель, не трогая остальные."""
        self._exec(
            """INSERT INTO models (ref, gateway, model, tier, status, error,
                                  cooldown_until, fails, ok_count, avg_ms, updated_at)
               VALUES (?, '', '', 5, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ref) DO UPDATE SET
                   status=excluded.status, error=excluded.error,
                   cooldown_until=excluded.cooldown_until, fails=excluded.fails,
                   ok_count=excluded.ok_count, avg_ms=excluded.avg_ms,
                   updated_at=excluded.updated_at""",
            (ref, status, error, cooldown_until, fails, ok_count, avg_ms, time.time()),
        )

    # ------------------------------------------------------------- пинги/sanity

    def save_probes(self, probes: dict[str, dict[str, Any]]) -> None:
        now = time.time()
        rows = [(ref, json.dumps(payload, ensure_ascii=False), now)
                for ref, payload in probes.items()]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                """INSERT INTO probes (ref, payload, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(ref) DO UPDATE SET
                       payload=excluded.payload, updated_at=excluded.updated_at""",
                rows,
            )
            self._conn.commit()

    def load_probes(self, *, max_age: float = 6 * 3600) -> dict[str, dict[str, Any]]:
        """Загрузить результаты пинга. max_age: старые считаем протухшими."""
        cutoff = time.time() - max_age
        out: dict[str, dict[str, Any]] = {}
        for row in self._query("SELECT ref, payload FROM probes WHERE updated_at > ?", (cutoff,)):
            try:
                out[row["ref"]] = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
        return out

    def save_sanity(self, reports: dict[str, dict[str, Any]]) -> None:
        now = time.time()
        rows = [
            (ref, float(payload.get("score") or 0), str(payload.get("verdict") or ""),
             json.dumps(payload, ensure_ascii=False), now)
            for ref, payload in reports.items()
        ]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                """INSERT INTO sanity (ref, score, verdict, payload, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(ref) DO UPDATE SET
                       score=excluded.score, verdict=excluded.verdict,
                       payload=excluded.payload, updated_at=excluded.updated_at""",
                rows,
            )
            self._conn.commit()

    def load_sanity(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in self._query("SELECT ref, payload FROM sanity"):
            try:
                out[row["ref"]] = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
        return out

    # --------------------------------------------------------------- сессии

    def add_session(self, workspace_id: str, name: str = "",
                    *, session_id: str | None = None) -> str:
        """Создать сессию в воркспейсе и вернуть её id.

        Сессия — это отдельная переписка в рамках одной папки. Папку можно
        менять, а историю можно начать заново, не теряя сам воркспейс.
        """
        now = time.time()
        # Имя по умолчанию — по времени, чтобы в списке было видно порядок.
        title = (name or "").strip() or time.strftime("%H:%M", time.localtime(now))
        base = _slugify(title)
        new_id = session_id or base
        # Слотка не должна перетирать чужую сессию: угадываем свободный.
        # Проверка и вставка идут под одним замком: между ними другой поток
        # мог вставить тот же id, и `sqlite3.IntegrityError` ушёл бы в 500.
        counter = 1
        with self._lock:
            while self.get_session(new_id) is not None:
                counter += 1
                new_id = f"{base}-{counter}"
            self._exec(
                "INSERT INTO sessions (id, workspace_id, name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_id, workspace_id, title, now, now),
            )
        return new_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM sessions WHERE id = ?", (session_id,))
        if not rows:
            return None
        record = dict(rows[0])
        record["task_count"] = int(self._query(
            "SELECT COUNT(*) AS n FROM tasks WHERE session_id = ?", (session_id,)
        )[0]["n"])
        return record

    def list_sessions(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        """Сессии по воркспейсу, свежие сверху.

        Порядок по updated_at, а не по имени: переключили сессию — она
        поднялась наверх, это ожидаемое поведение списка «недавних».
        """
        if workspace_id:
            rows = self._query(
                "SELECT id FROM sessions WHERE workspace_id = ? "
                "ORDER BY updated_at DESC, id ASC",
                (workspace_id,),
            )
        else:
            rows = self._query("SELECT id FROM sessions ORDER BY updated_at DESC, id ASC")
        return [record for record in (self.get_session(row["id"]) for row in rows)
                if record]

    def touch_session(self, session_id: str) -> None:
        """Отметить сессию использованной только что."""
        if session_id:
            self._exec("UPDATE sessions SET updated_at = ? WHERE id = ?",
                       (time.time(), session_id))

    def rename_session(self, session_id: str, name: str) -> dict[str, Any] | None:
        record = self.get_session(session_id)
        if record is None:
            return None
        title = (name or "").strip()
        if not title:
            return record
        self._exec("UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
                   (title, time.time(), session_id))
        return self.get_session(session_id)

    def remove_session(self, session_id: str) -> bool:
        """Удалить сессию. Задачи остаются в базе со своим session_id.

        Нельзя удалить последнюю сессию своего воркспейса: активной сессии
        пришлось бы не быть, а интерфейс без неё не знает, что показывать.
        Остальные воркспейсы на это не влияют — у каждого своя последняя.
        """
        record = self.get_session(session_id)
        if record is None:
            return False
        left = self._query(
            "SELECT id FROM sessions WHERE workspace_id = ?",
            (record["workspace_id"],),
        )
        if len(left) <= 1:
            return False
        self._exec("DELETE FROM sessions WHERE id = ?", (session_id,))
        return True

    def ensure_session(self, workspace_id: str) -> str:
        """Сессия для воркспейса: свежая или только что созданная.

        Вызывается при старте, чтобы интерфейс всегда имел что показывать.
        """
        active = self.active_session_id()
        if active:
            record = self.get_session(active)
            if record and record["workspace_id"] == workspace_id:
                return active
        existing = self.list_sessions(workspace_id)
        if existing:
            return str(existing[0]["id"])
        return self.add_session(workspace_id)

    def active_session_id(self) -> str:
        return str(self.get_meta("active_session", "") or "")

    def set_active_session(self, session_id: str) -> None:
        self.set_meta("active_session", session_id)
        self.touch_session(session_id)

    # ----------------------------------------------------------------- задачи

    def add_task(self, task: str, *, priority: int = 5,
                 payload: dict[str, Any] | None = None,
                 session_id: str = "") -> int:
        cursor = self._exec(
            "INSERT INTO tasks (task, status, priority, created_at, payload, session_id) "
            "VALUES (?, 'queued', ?, ?, ?, ?)",
            (task, priority, time.time(),
             json.dumps(payload or {}, ensure_ascii=False), session_id or None),
        )
        return int(cursor.lastrowid)

    def next_queued_task(self) -> dict[str, Any] | None:
        """Взять следующую задачу: сначала с меньшим числом priority, затем старее."""
        rows = self._query(
            "SELECT * FROM tasks WHERE status = 'queued' ORDER BY priority ASC, id ASC LIMIT 1"
        )
        if not rows:
            return None
        return _task_row(rows[0])

    def update_task(self, task_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status", "started_at", "finished_at", "steps", "duration_ms",
            "models", "result", "error", "priority", "payload",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        # payload и result ходят в базу строкой JSON, наружу отдаются словарём.
        for key in ("payload", "result"):
            if isinstance(updates.get(key), dict):
                updates[key] = json.dumps(updates[key], ensure_ascii=False, default=str)
        assignments = ", ".join(f"{key} = ?" for key in updates)
        params = [updates[key] for key in updates] + [task_id]
        self._exec(f"UPDATE tasks SET {assignments} WHERE id = ?", params)

    def claim_task(self, task_id: int) -> None:
        """Перевести задачу в running. Возвращает False, если её уже взяли."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE tasks SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                (time.time(), task_id),
            )
            self._conn.commit()
            if cursor.rowcount == 0:
                raise RuntimeError(f"Задача {task_id} уже выполняется или не найдена")

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _task_row(rows[0]) if rows else None

    def list_tasks(self, *, limit: int = 50,
                   status: str | None = None,
                   session_id: str | None = None) -> list[dict[str, Any]]:
        """Задачи, свежие сверху.

        session_id фильтрует по сессии. Пустая строка означает «все», а None —
        «не фильтровать вовсе»: разница нужна, чтобы отличать «показать все»
        от «показать те, у кого сессии нет».
        """
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if session_id is not None:
            if session_id == "":
                clauses.append("session_id IS NULL")
            else:
                clauses.append("session_id = ?")
                params.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(
            f"SELECT * FROM tasks {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )
        return [_task_row(row) for row in rows]

    def cancel_task(self, task_id: int) -> bool:
        """Отменить задачу.

        queued и parked (asking / waiting_permission) снимаются сразу — они
        ничего не выполняют, просто ждут пользователя. running нельзя убить
        напрямую: запрос к модели посреди генерации не прервать, поэтому
        ставим флаг, который агент проверяет между шагами.
        """
        task = self.get_task(task_id)
        if task is None:
            return False
        status = task["status"]
        if status in ("queued", "asking", "waiting_permission"):
            self.update_task(task_id, status="cancelled", finished_at=time.time())
            return True
        if status == "running":
            payload = dict(task.get("payload") or {})
            payload["cancel"] = True
            self.update_task(task_id, payload=payload)
            return True
        return False

    def task_counts(self) -> dict[str, int]:
        rows = self._query("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")
        return {row["status"]: row["n"] for row in rows}

    # ----------------------------------------------------------------- события

    def add_event(self, event: dict[str, Any], *, task_id: int | None = None) -> int:
        # Порядок параметров обязан совпадать с порядком колонок в INSERT:
        # task_id, at, type, payload. Раньше здесь стоял task_id дважды, и
        # колонка at получала NULL — падало NOT NULL constraint.
        at = event.get("at")
        if not isinstance(at, (int, float)):
            at = time.time()

        # task_id берём из аргумента, а если его нет — из самого события:
        # вызывающий код (воркер) кладёт его в тело события.
        if task_id is None:
            task_id = event.get("task_id")

        event_type = str(event.get("type") or "unknown")
        # Сессия нужна событию, чтобы поток можно было фильтровать: иначе в
        # переписке сессии мешались бы шаги чужой задачи из другой папки.
        # Берём её из задачи, а не просим у вызывающего: событие не должно
        # знать про сессии само по себе.
        session_id = event.get("session_id")
        if session_id is None and task_id is not None:
            rows = self._query("SELECT session_id FROM tasks WHERE id = ?", (task_id,))
            session_id = rows[0]["session_id"] if rows else None
        payload = dict(event)
        payload["session_id"] = session_id

        cursor = self._exec(
            "INSERT INTO events (task_id, at, type, payload) VALUES (?, ?, ?, ?)",
            (task_id, float(at), event_type,
             json.dumps(payload, ensure_ascii=False, default=str)),
        )
        return int(cursor.lastrowid)

    def events_since(self, last_id: int = 0, *, limit: int = 300,
                     task_id: int | None = None) -> list[dict[str, Any]]:
        """События после last_id — для SSE-стрима и догрузки журнала."""
        if task_id is not None:
            rows = self._query(
                "SELECT * FROM events WHERE id > ? AND task_id = ? ORDER BY id ASC LIMIT ?",
                (last_id, task_id, limit),
            )
        else:
            rows = self._query(
                "SELECT * FROM events WHERE id > ? ORDER BY id ASC LIMIT ?", (last_id, limit)
            )
        out = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
            payload["id"] = row["id"]
            payload["task_id"] = row["task_id"]
            out.append(payload)
        return out

    def last_event_id(self) -> int:
        rows = self._query("SELECT COALESCE(MAX(id), 0) AS n FROM events")
        return int(rows[0]["n"]) if rows else 0

    def trim_events(self, keep: int = 2000) -> None:
        """Подрезать журнал, иначе он растёт без ограничений."""
        self._exec(
            "DELETE FROM events WHERE id <= (SELECT COALESCE(MAX(id), 0) - ? FROM events)",
            (keep,),
        )

    # ------------------------------------------------------------ разрешения

    def add_permission(
        self, *, operation: str, path: str, workspace: str, reason: str = "",
        task_id: int | None = None,
    ) -> int:
        """Запросить разрешение на выход за границу воркспейса."""
        cursor = self._exec(
            """INSERT INTO permissions (task_id, operation, path, workspace, reason,
                                       status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (task_id, operation, path, workspace, reason, time.time()),
        )
        return int(cursor.lastrowid)

    def get_permission(self, permission_id: int) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM permissions WHERE id = ?", (permission_id,))
        return dict(rows[0]) if rows else None

    def pending_permissions(self, *, task_id: int | None = None) -> list[dict[str, Any]]:
        """Неотвеченные запросы. Если задан task_id — только по нему."""
        if task_id is not None:
            rows = self._query(
                "SELECT * FROM permissions WHERE status = 'pending' AND task_id = ? ORDER BY id",
                (task_id,),
            )
        else:
            rows = self._query(
                "SELECT * FROM permissions WHERE status = 'pending' ORDER BY id"
            )
        return [dict(row) for row in rows]

    def decide_permission(self, permission_id: int, allow: bool, *,
                          scope: str = "once") -> dict[str, Any] | None:
        """Ответить на запрос: allow=True и scope=once|always.

        scope сохраняется и при отказе: по нему denied_paths() находит пути,
        которые повторно спрашивать не надо. Возвращает запись с ответом
        или None, если запрос не найден.
        """
        request = self.get_permission(permission_id)
        if request is None:
            return None
        status = "granted" if allow else "denied"
        self._exec(
            "UPDATE permissions SET status = ?, scope = ?, decided_at = ? WHERE id = ?",
            (status, scope, time.time(), permission_id),
        )
        return self.get_permission(permission_id)

    def drop_permissions(self, *, task_id: int | None = None,
                         reason: str = "") -> int:
        """Снять неотвеченные запросы: задачу отменили или она неактуальна.

        Возвращает количество снятых. Используется при отмене задачи и при
        старте воркера, чтобы окно разрешения не висело после перезапуска.
        """
        if task_id is None:
            rows = self._query("SELECT id, reason FROM permissions WHERE status = 'pending'")
        else:
            rows = self._query(
                "SELECT id, reason FROM permissions WHERE status = 'pending' AND task_id = ?",
                (task_id,),
            )
        stamp = time.time()
        for row in rows:
            note = f"{row['reason']} [{reason}]" if reason and row["reason"] else (
                reason or row["reason"]
            )
            self._exec(
                "UPDATE permissions SET status = 'dropped', reason = ?, decided_at = ? "
                "WHERE id = ?",
                (note, stamp, int(row["id"])),
            )
        return len(rows)

    def granted_paths(self, *, task_id: int | None = None) -> list[str]:
        """Пути, на которые пользователь уже дал разрешение.

        scope=always действует глобально, scope=once — только в рамках задачи.
        """
        if task_id is None:
            rows = self._query(
                "SELECT path, scope FROM permissions WHERE status = 'granted' AND scope = 'always'"
            )
        else:
            rows = self._query(
                """SELECT path, scope FROM permissions
                   WHERE status = 'granted' AND (scope = 'always' OR task_id = ?)""",
                (task_id,),
            )
        return [row["path"] for row in rows]

    def stranded_permission_tasks(self) -> list[dict[str, Any]]:
        """Задачи, ждущие разрешения, которого уже нет.

        Такое бывает, если запрос сняли вручную или он потерялся. Ответить
        больше не на что, поэтому задача не может продолжиться.
        """
        rows = self._query(
            """SELECT t.* FROM tasks t
               WHERE t.status = 'waiting_permission'
                 AND NOT EXISTS (
                     SELECT 1 FROM permissions p
                     WHERE p.task_id = t.id AND p.status = 'pending'
                 )"""
        )
        return [_task_row(row) for row in rows]

    def denied_paths(self, *, task_id: int | None = None) -> list[str]:
        """Пути, по которым пользователь отказал.

        scope=always действует глобально, scope=once — только в рамках задачи.
        """
        if task_id is None:
            rows = self._query(
                "SELECT path FROM permissions WHERE status = 'denied' AND scope = 'always'"
            )
        else:
            rows = self._query(
                """SELECT path FROM permissions
                   WHERE status = 'denied' AND (scope = 'always' OR task_id = ?)""",
                (task_id,),
            )
        return [row["path"] for row in rows]

    # -------------------------------------------------------------------- meta

    def set_meta(self, key: str, value: Any) -> None:
        self._exec(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False, default=str)),
        )

    def get_meta(self, key: str, default: Any = None) -> Any:
        rows = self._query("SELECT value FROM meta WHERE key = ?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["value"])
        except json.JSONDecodeError:
            return default

    # -------------------------------------------------------- диагностика

    def stats(self) -> dict[str, Any]:
        tasks = self.task_counts()
        events = self._query("SELECT COUNT(*) AS n FROM events")
        pending = len(self.pending_permissions())
        return {
            "path": str(self.path),
            "tasks": tasks,
            "events": int(events[0]["n"]) if events else 0,
            "models": int(self._query("SELECT COUNT(*) AS n FROM models")[0]["n"]),
            "permissions_pending": pending,
        }


def _task_row(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    try:
        task["payload"] = json.loads(task.get("payload") or "{}")
    except json.JSONDecodeError:
        task["payload"] = {}
    task["models"] = [m for m in (task.get("models") or "").split(",") if m]
    return task


def _slugify(text: str) -> str:
    """Имя в id: по-русски, без пробелов и спецсимволов.

    Транслитерации нет специально: кириллица в id совершенно рабочая, а
    транслитерация добавила бы словарь ради одной строки.
    """
    cleaned = "".join(
        ch if ch.isalnum() or ch in "-_" else "-"
        for ch in str(text).strip().lower()
    )
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "session"
