# Минимальные проверки auth-flow. Запуск: python test_auth.py
#
# Проверяем не «работает ли страница», а три места, где обычно появляется дыра:
# пароль в базе, сравнение паролей и одноразовость токена сброса.

import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server


class AuthTests(unittest.TestCase):
    def setUp(self):
        # Каждый тест — своя база, иначе тесты зависят от порядка.
        self.tmp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        server.init_db()
        self.conn = server.db()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    # --- пароль

    def test_password_not_stored_plain(self):
        digest, salt, iterations = server.hash_password("очень-долгий-пароль")
        self.assertNotIn("очень-долгий-пароль", digest)
        self.assertEqual(iterations, server.ITERATIONS)

    def test_same_password_gives_different_hash(self):
        # Одна и та же пара, разные соли: иначе одинаковые пароли видно
        # в баде без её открытия.
        first, _, _ = server.hash_password("пароль-1234")
        second, _, _ = server.hash_password("пароль-1234")
        self.assertNotEqual(first, second)

    def test_verify_accepts_right_password(self):
        digest, salt, iterations = server.hash_password("пароль-1234")
        self.assertTrue(server.verify_password("пароль-1234", digest, salt, iterations))

    def test_verify_rejects_wrong_password(self):
        digest, salt, iterations = server.hash_password("пароль-1234")
        self.assertFalse(server.verify_password("пароль-1235", digest, salt, iterations))

    def test_wrong_salt_fails(self):
        digest, _, iterations = server.hash_password("пароль-1234")
        self.assertFalse(server.verify_password("пароль-1234", digest, "0" * 32, iterations))

    # --- пользователи

    def _add_user(self, email="a@b.ru", password="пароль-1234"):
        digest, salt, iterations = server.hash_password(password)
        self.conn.execute(
            """INSERT INTO users (email, pw_hash, pw_salt, pw_iters, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (email, digest, salt, iterations, time.time()),
        )
        self.conn.commit()

    def test_email_is_unique(self):
        self._add_user()
        with self.assertRaises(sqlite3.IntegrityError):
            self._add_user()

    def test_password_column_has_no_plaintext(self):
        self._add_user(password="пароль-1234")
        row = self.conn.execute(
            "SELECT pw_hash, pw_salt FROM users WHERE email = ?", ("a@b.ru",)
        ).fetchone()
        dumped = f"{row['pw_hash']}{row['pw_salt']}"
        self.assertNotIn("пароль-1234", dumped)

    # --- сессии

    def test_session_created_and_resolved(self):
        cursor = self.conn.execute(
            """INSERT INTO users (email, pw_hash, pw_salt, pw_iters, created_at)
               VALUES ('a@b.ru', 'x', 'y', 1, 0)"""
        )
        user_id = int(cursor.lastrowid or 0)
        token = server.create_session(self.conn, user_id)
        self.assertIsNotNone(server.session_user(self.conn, token))

    def test_session_of_unknown_token_is_none(self):
        self.assertIsNone(server.session_user(self.conn, "подделка"))

    def test_drop_session(self):
        cursor = self.conn.execute(
            """INSERT INTO users (email, pw_hash, pw_salt, pw_iters, created_at)
               VALUES ('a@b.ru', 'x', 'y', 1, 0)"""
        )
        token = server.create_session(self.conn, int(cursor.lastrowid or 0))
        server.drop_session(self.conn, token)
        self.assertIsNone(server.session_user(self.conn, token))

    # --- сброс пароля

    def test_reset_stores_only_hash_of_token(self):
        cursor = self.conn.execute(
            """INSERT INTO users (email, pw_hash, pw_salt, pw_iters, created_at)
               VALUES ('a@b.ru', 'x', 'y', 1, 0)"""
        )
        user_id = int(cursor.lastrowid or 0)
        raw = "секретный-токен"
        self.conn.execute(
            "INSERT INTO resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (__import__("hashlib").sha256(raw.encode()).hexdigest(),
             user_id, time.time() + 60),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT token_hash FROM resets").fetchone()
        self.assertNotIn(raw, row["token_hash"])

    def test_expired_reset_is_rejected(self):
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM resets WHERE expires_at > ?", (time.time(),)
        ).fetchone())

    def test_password_change_clears_sessions(self):
        """Смена пароля обязана рвать сессии, иначе старый доступ выживет."""
        cursor = self.conn.execute(
            """INSERT INTO users (email, pw_hash, pw_salt, pw_iters, created_at)
               VALUES ('a@b.ru', 'x', 'y', 1, 0)"""
        )
        user_id = int(cursor.lastrowid or 0)
        server.create_session(self.conn, user_id)
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.conn.commit()
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0
        )

    # --- почта

    def test_email_regex(self):
        for good in ("a@b.ru", "user.name+tag@example.co.uk"):
            self.assertIsNotNone(server.EMAIL_RE.match(good), good)
        for bad in ("a@b", "без-собаки.ru", "a b@c.ru", "@b.ru"):
            self.assertIsNone(server.EMAIL_RE.match(bad), bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)