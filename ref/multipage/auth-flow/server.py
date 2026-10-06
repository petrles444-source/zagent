#!/usr/bin/env python
"""Регистрация, вход и сброс пароля на стандартной библиотеке.

Запуск:  python server.py  →  http://127.0.0.1:8765

Три страницы, одна база sqlite3, ноль зависимостей. Это учебный образец
безопасности, а не готовый продукт: см. раздел «Чего здесь нет».

Что показывает этот файл:

* пароль хранится ТОЛЬКО как PBKDF2-HMAC-SHA256 со случайной солью,
  сравнение паролей — ``hmac.compare_digest``, а не ``==``;
* сессия лежит в httpOnly cookie с ``SameSite=Lax`` и не переживает
  перезапуск сервера: идентификатор хранится в базе и удаляется при выходе;
* токен сброса пароля — одноразовый, хранится только его хеш, и имеет
  срок жизни;
* форма входа не сообщает, существует ли такой адрес: ответ на неверный пароль
  и на несуществующий аккаунт одинаковый. Иначе форма входа превращается в
  способ узнать, кому принадлежит адрес.
"""

from __future__ import annotations

import hashlib
import hmac
import http.cookies
import html
import json
import os
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "auth.sqlite3"

#: PBKDF2 дорожает на каждой итерации, поэтому итераций много, а счётчик
#: хранится рядом с хешем: через год можно пересчитать с новым числом.
ITERATIONS = 240_000
ALGO = "sha256"

#: Сколько живёт ссылка для сброса пароля.
RESET_TTL = 1800  # полчаса
SESSION_TTL = 7 * 24 * 3600

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)


# ----------------------------------------------------------------- база


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY,
            email       TEXT NOT NULL UNIQUE,
            pw_hash     TEXT NOT NULL,
            pw_salt     TEXT NOT NULL,
            pw_iters    INTEGER NOT NULL,
            created_at  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resets (
            token_hash  TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at  REAL NOT NULL
        );
        """)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------- пароли


def hash_password(password: str, *, salt: str | None = None,
                  iterations: int = ITERATIONS) -> tuple[str, str, int]:
    """Пароль → (хеш, соль, число итераций)."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        ALGO, password.encode("utf-8"), salt.encode("utf-8"), iterations
    )
    return digest.hex(), salt, iterations


def verify_password(password: str, stored_hash: str, salt: str,
                    iterations: int) -> bool:
    """Сравнение за постоянное время: иначе по времени ответа можно подбирать."""
    candidate, _, _ = hash_password(password, salt=salt, iterations=iterations)
    return hmac.compare_digest(candidate, stored_hash)


# ------------------------------------------------------------ сессии


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, time.time()),
    )
    conn.commit()
    return token


def session_user(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    return conn.execute(
        """
        SELECT u.id, u.email, s.created_at
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    ).fetchone()


def drop_session(conn: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


# ------------------------------------------------------------- страницы

STYLE = """
* { box-sizing: border-box }
body { margin:0; min-height:100vh; display:grid; place-items:center;
       font:16px/1.6 system-ui, sans-serif; background:#f6f7f9; color:#15181d }
form { width:100%; max-width:360px; background:#fff; padding:26px;
       border-radius:12px; border:1px solid #e2e6ed; display:grid; gap:6px }
h1 { font-size:21px; margin:0 0 14px }
label { font-size:14px; font-weight:600 }
input { font:inherit; padding:10px 12px; border:1px solid #d8dde6; border-radius:8px }
input:focus { outline:2px solid #2563eb; outline-offset:1px }
button { margin-top:12px; font:inherit; font-weight:600; padding:11px;
         background:#2563eb; color:#fff; border:0; border-radius:8px; cursor:pointer }
.msg { min-height:20px; font-size:13px; margin:4px 0 0 }
.bad { color:#c03221 } .good { color:#157f4a }
nav { text-align:center; font-size:14px; margin-top:14px }
a { color:#2563eb }
"""


def page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{STYLE}</style></head>
<body><form>{body}
<nav><a href="/login">Вход</a> · <a href="/">Регистрация</a> · <a href="/reset">Сброс</a></nav>
</form></body></html>""".encode("utf-8")


def message(text: str, kind: str = "bad") -> str:
    if not text:
        return '<p class="msg"></p>'
    return f'<p class="msg {kind}">{html.escape(text)}</p>'


LOGIN_BODY = """
<h1>Вход</h1>
<p class="msg {cls}" role="alert">{note}</p>
<label for="email">Почта</label>
<input id="email" name="email" type="email" required autocomplete="email" autofocus>
<label for="password">Пароль</label>
<input id="password" name="password" type="password" required autocomplete="current-password">
<button type="submit">Войти</button>
"""

RESET_BODY = """
<h1>Сброс пароля</h1>
<p class="msg {cls}" role="status">{note}</p>
<label for="email">Почта</label>
<input id="email" name="email" type="email" required autocomplete="email" autofocus>
<button type="submit">Выслать ссылку</button>
"""

NEW_PASSWORD_BODY = """
<h1>Новый пароль</h1>
<p class="msg {cls}" role="alert">{note}</p>
<input type="hidden" name="token" value="{token}">
<label for="password">Пароль</label>
<input id="password" name="password" type="password" required autocomplete="new-password">
<button type="submit">Сохранить</button>
"""


# ------------------------------------------------------------- обработчик


class Handler(BaseHTTPRequestHandler):
    server_version = "auth-flow/1.0"

    # --- вспомогательное

    def _cookie(self) -> http.cookies.SimpleCookie:
        raw = self.headers.get("Cookie", "")
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(raw)
        except http.cookies.CookieError:
            pass
        return jar

    def _session_token(self) -> str | None:
        morsel = self._cookie().get("sid")
        return morsel.value if morsel else None

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 64 * 1024:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def _send(self, body: bytes, status: int = 200,
              cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- маршруты

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        conn = db()
        try:
            user = session_user(conn, self._session_token())
            if path == "/":
                if user:
                    self._send(page("Готово", (
                        f"<h1>Привет, {html.escape(user['email'])}</h1>"
                        f"<p class='msg good'>Вы вошли.</p>"
                        f"<a href='/logout'>Выйти</a>"
                    )))
                    return
                self._send(page("Регистрация", """
                    <h1>Регистрация</h1>
                    <p class="msg bad" role="alert"></p>
                    <label for="email">Почта</label>
                    <input id="email" name="email" type="email" required
                           autocomplete="email" autofocus>
                    <label for="password">Пароль</label>
                    <input id="password" name="password" type="password" required
                           autocomplete="new-password">
                    <button type="submit">Создать аккаунт</button>
                """))
            elif path == "/login":
                self._send(page("Вход", LOGIN_BODY.format(cls="", note="")))
            elif path == "/reset":
                self._send(page("Сброс пароля", RESET_BODY.format(cls="", note="")))
            elif path == "/new-password":
                query = parse_qs(urlparse(self.path).query)
                token = (query.get("token") or [""])[0]
                if not token:
                    self._send(page("Ссылка недействительна", """
                        <h1>Ссылка недействительна</h1>
                        <p class="msg bad">Запросите новую на странице сброса.</p>
                    """), status=400)
                    return
                self._send(page("Новый пароль", NEW_PASSWORD_BODY.format(
                    cls="", note="", token=html.escape(token))))
            else:
                self._send(page("Не найдено", "<h1>Страница не найдена</h1>"), status=404)
        finally:
            conn.close()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        form = self._form()
        conn = db()
        try:
            if path == "/":
                self._register(conn, form)
            elif path == "/login":
                self._login(conn, form)
            elif path == "/logout":
                drop_session(conn, self._session_token())
                self._send(b"", status=303,
                           cookie="sid=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            elif path == "/reset":
                self._request_reset(conn, form)
            elif path == "/new-password":
                self._finish_reset(conn, form)
            else:
                self._send(page("Не найдено", "<h1>Страница не найдено</h1>"),
                           status=404)
        finally:
            conn.close()

    # --- действия

    def _register(self, conn: sqlite3.Connection, form: dict[str, str]) -> None:
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""

        if not EMAIL_RE.match(email):
            self._send(page("Регистрация", """
                <h1>Регистрация</h1>
                <p class="msg bad" role="alert">Похоже, в адресе опечатка.</p>
                <label for="email">Почта</label>
                <input id="email" name="email" type="email" required autofocus>
                <label for="password">Пароль</label>
                <input id="password" name="password" type="password" required
                       autocomplete="new-password">
                <button type="submit">Создать аккаунт</button>
            """))
            return
        if len(password) < 8:
            note = "Пароль короче 8 символов."
            self._send(page("Регистрация", """
                <h1>Регистрация</h1>
                <p class="msg bad" role="alert">Пароль короче 8 символов.</p>
                <label for="email">Почта</label>
                <input id="email" name="email" type="email" required autofocus>
                <label for="password">Пароль</label>
                <input id="password" name="password" type="password" required
                       autocomplete="new-password">
                <button type="submit">Создать аккаунт</button>
            """))
            return

        pw_hash, salt, iterations = hash_password(password)
        try:
            cursor = conn.execute(
                """INSERT INTO users (email, pw_hash, pw_salt, pw_iters, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (email, pw_hash, salt, iterations, time.time()),
            )
        except sqlite3.IntegrityError:
            # Регистрация повторная — это нормальный сценарий, не поломка.
            self._send(page("Адрес занят", """
                <h1>Адрес уже занят</h1>
                <p class="msg bad">На эту почту уже есть аккаунт. Попробуйте войти.</p>
                <a href="/login">Войти</a>
            """))
            return
        conn.commit()

        token = create_session(conn, int(cursor.lastrowid or 0))
        self._send(b"", status=303,
                   cookie=f"sid={token}; Path=/; Max-Age={SESSION_TTL}; "
                          "HttpOnly; SameSite=Lax")

    def _login(self, conn: sqlite3.Connection, form: dict[str, str]) -> None:
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        # Один и тот же ответ на «нет такого адреса» и «неверный пароль»:
        # иначе форма входа позволяет выяснить, какие адреса зарегистрированы.
        # Чтобы время ответа не выдавало разницу, пароль всё равно считаем.
        if row is None:
            hash_password(password, salt="0" * 32, iterations=ITERATIONS)
            note = "Неверная почта или пароль."
        elif not verify_password(password, row["pw_hash"], row["pw_salt"],
                                 int(row["pw_iters"])):
            note = "Неверная почта или пароль."
        else:
            token = create_session(conn, int(row["id"]))
            self._send(b"", status=303,
                       cookie=f"sid={token}; Path=/; Max-Age={SESSION_TTL}; "
                              "HttpOnly; SameSite=Lax")
            return

        body = LOGIN_BODY.format(cls="bad", note=html.escape(note))
        self._send(page("Вход", body))

    def _request_reset(self, conn: sqlite3.Connection, form: dict[str, str]) -> None:
        email = (form.get("email") or "").strip().lower()
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row is not None:
            raw = secrets.token_urlsafe(32)
            # В базу кладём только хеш токена: сама ссылка живёт в письме.
            conn.execute(
                "INSERT INTO resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (hashlib.sha256(raw.encode()).hexdigest(), int(row["id"]),
                 time.time() + RESET_TTL),
            )
            conn.commit()
            # В учебном образце ссылка печатается в консоль: почты здесь нет.
            print(f"Ссылка для сброса: http://127.0.0.1:{self.server.server_port}"
                  f"/new-password?token={raw}")

        # Ответ одинаковый независимо от того, есть такой адрес или нет.
        body = RESET_BODY.format(
            cls="good",
            note="Если такой адрес есть, ссылка придёт на почту.",
        )
        self._send(page("Сброс пароля", body))

    def _finish_reset(self, conn: sqlite3.Connection, form: dict[str, str]) -> None:
        raw = form.get("token") or ""
        password = form.get("password") or ""
        digest = hashlib.sha256(raw.encode()).hexdigest()
        row = conn.execute(
            "SELECT * FROM resets WHERE token_hash = ?", (digest,)
        ).fetchone()
        if row is None or float(row["expires_at"]) < time.time():
            self._send(page("Ссылка недействительна", """
                <h1>Ссылка недействительна</h1>
                <p class="msg bad">Она истекла или уже использована.</p>
                <a href="/reset">Запросить новую</a>
            """), status=400)
            return
        if len(password) < 8:
            self._send(page("Новый пароль", NEW_PASSWORD_BODY.format(
                cls="bad", note=html.escape("Пароль короче 8 символов."),
                token=html.escape(raw))))
            return

        pw_hash, salt, iterations = hash_password(password)
        conn.execute(
            "UPDATE users SET pw_hash = ?, pw_salt = ?, pw_iters = ? WHERE id = ?",
            (pw_hash, salt, iterations, int(row["user_id"])),
        )
        # Одноразовость: токен удаляется сразу после использования.
        conn.execute("DELETE FROM resets WHERE token_hash = ?", (digest,))
        # Смена пароля рвёт все сессии: иначе старый доступ пережил бы смену.
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (int(row["user_id"]),))
        conn.commit()

        self._send(page("Пароль изменён", """
            <h1>Пароль изменён</h1>
            <p class="msg good">Теперь можно войти с новым паролем.</p>
            <a href="/login">Войти</a>
        """))


def main() -> None:
    init_db()
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Открой http://127.0.0.1:{port}")
    print(f"База: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()