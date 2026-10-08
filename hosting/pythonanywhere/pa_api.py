"""Клиент PythonAnywhere API на стандартной библиотеке.

Зачем
-----
Хостинг управляется HTTP-запросами с токеном из панели. Задачи здесь
простые — залить файл, создать веб-приложение, перезапустить — и
тянуть за собой `requests` ради этого незачем: на бесплатном
PythonAnywhere pip работает через виртуальное окружение, и лишняя
зависимость там оборачивается лишними хлопотами.

Токен
-----
Никогда не хранится в коде и не печатается. Берётся из `credentials.json`
рядом с этим файлом; в репозиторий попадает только `credentials.example.json`.

Ограничение бесплатного тарифа, о котором важно помнить
--------------------------------------------------------
100 секунд процессорного времени в сутки. Проверить остаток — `cpu()`.
Скрипт, который висит и спит, почти не тратит квоту; вызов модели —
тратит, и на всём суточном лимите полноценный диалог не выйдет.
"""

from __future__ import annotations

import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CREDENTIALS = HERE / "credentials.json"
EXAMPLE = HERE / "credentials.example.json"


class PaError(RuntimeError):
    """PythonAnywhere отказал. Текст ответа — в сообщении."""


def load_credentials(path: Path | None = None) -> dict[str, Any]:
    """Прочитать учётные данные.

    Переменные окружения имеют приоритет над файлом: на сервере токен
    живёт в `$API_TOKEN`, и класть его в диск не нужно вовсе.
    """
    data: dict[str, Any] = {}
    if path is None:
        path = CREDENTIALS
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise PaError(f"{path.name} не читается: {exc}") from exc
    token = os.environ.get("ZAGENT_PA_TOKEN") or os.environ.get("API_TOKEN") or ""
    username = os.environ.get("ZAGENT_PA_USER") or ""
    host = os.environ.get("ZAGENT_PA_HOST") or ""
    merged = {**data}
    if token:
        merged["token"] = token
    if username:
        merged["username"] = username
    if host:
        merged["host"] = host
    missing = [key for key in ("username", "token") if not merged.get(key)]
    if missing:
        raise PaError(
            f"нет {', '.join(missing)}: скопируй {EXAMPLE.name} в "
            "credentials.json и впиши значения, либо задай переменные "
            "ZAGENT_PA_USER и ZAGENT_PA_TOKEN")
    return merged


class PythonAnywhere:
    """Тонкая обёртка над API. Методы повторяют эндпойнты один в один."""

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self.cfg = credentials or load_credentials()
        self.user = self.cfg["username"]
        self.token = self.cfg["token"]
        self.host = self.cfg.get("host") or "www.pythonanywhere.com"
        if not self.host.startswith("http"):
            self.host = "https://" + self.host

    # ---------------------------------------------------------- низкий уровень

    def _url(self, path: str) -> str:
        return f"{self.host}/api/v0/user/{self.user}/{path.lstrip('/')}"

    def request(self, method: str, path: str, *,
                data: dict[str, Any] | None = None,
                files: dict[str, Any] | None = None,
                raw: bytes | None = None,
                timeout: float = 60.0) -> Any:
        """Один запрос к API. Ошибки ответа превращает в PaError."""
        url = self._url(path)
        headers = {"Authorization": f"Token {self.token}"}
        body: bytes | None = raw

        if files is not None:
            # Граница выбирается случайно: значение не должно встречаться
            # внутри файла, иначе разбор multipart сорвётся.
            boundary = "----zagent" + uuid.uuid4().hex
            chunks: list[bytes] = []
            for name, value in (data or {}).items():
                chunks.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{name}\"\r\n\r\n{value}\r\n".encode())
            for name, (filename, content) in files.items():
                guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                chunks.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{name}\"; filename=\"{filename}\"\r\n"
                    f"Content-Type: {guessed}\r\n\r\n".encode()
                    + content + b"\r\n")
            chunks.append(f"--{boundary}--\r\n".encode())
            body = b"".join(chunks)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            raise PaError(f"{method} {url} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise PaError(f"{method} {url} -> сеть: {exc.reason}") from exc
        if not payload:
            return None
        try:
            return json.loads(payload)
        except ValueError:
            return payload.decode("utf-8", "replace")

    # ---------------------------------------------------------- файлы

    def upload_file(self, remote_path: str, local: Path) -> Any:
        """Залить один файл. Каталоги создаются на сервере сами."""
        return self.request(
            "POST", "files/path" + remote_path,
            files={"content": (local.name, local.read_bytes())})

    def upload_text(self, remote_path: str, text: str,
                    name: str | None = None) -> Any:
        """Залить текст как файл — удобно для конфигов и правок."""
        return self.request(
            "POST", "files/path" + remote_path,
            files={"content": (name or Path(remote_path).name,
                               text.encode("utf-8"))})

    def delete_file(self, remote_path: str) -> Any:
        return self.request("DELETE", "files/path" + remote_path)

    def list_dir(self, remote_path: str = "/") -> Any:
        return self.request("GET", f"files/tree/?path={remote_path}")

    # ---------------------------------------------------------- веб-приложения

    def create_webapp(self, domain_name: str,
                      python_version: str = "python3.11") -> Any:
        return self.request("POST", "webapps/",
                            data={"domain_name": domain_name,
                                  "python_version": python_version})

    def webapp_configure(self, domain_name: str, *,
                         source_directory: str | None = None,
                         force_https: bool = True) -> Any:
        """Задать каталог кода и HTTPS.

        Домен `*.pythonanywhere.com` уже защищён сертификатом; явный
        `force_https` включает переадресацию с http, чтобы посетитель не
        остался без шифрования.
        """
        data: dict[str, Any] = {"force_https": "true"}
        if source_directory:
            data["source_directory"] = source_directory
        return self.request("PUT", f"webapps/{domain_name}/", data=data)

    def webapp_reload(self, domain_name: str) -> Any:
        return self.request("POST", f"webapps/{domain_name}/reload/")

    def webapp_enable(self, domain_name: str) -> Any:
        return self.request("POST", f"webapps/{domain_name}/enable/")

    def webapps(self) -> Any:
        return self.request("GET", "webapps/")

    # ---------------------------------------------------------- фоновые задачи

    def always_on(self) -> Any:
        return self.request("GET", "always_on/")

    def create_always_on(self, command: str, *,
                         description: str = "") -> Any:
        return self.request("POST", "always_on/",
                            data={"command": command,
                                  "description": description or "zagent bot",
                                  "enabled": "true"})

    def schedule(self) -> Any:
        return self.request("GET", "schedule/")

    def create_schedule(self, command: str, *, interval: str = "1",
                        hour: int = 0, minute: int = 0,
                        description: str = "") -> Any:
        return self.request("POST", "schedule/",
                            data={"command": command, "interval": interval,
                                  "hour": hour, "minute": minute,
                                  "description": description or "zagent bot",
                                  "enabled": "true"})

    # ---------------------------------------------------------- прочее

    def cpu(self) -> Any:
        """Остаток процессорного времени. Главный ограничитель тарифа."""
        return self.request("GET", "cpu/")


if __name__ == "__main__":
    try:
        pa = PythonAnywhere()
        info = pa.cpu()
        print("токен рабочий. Квота процессора:")
        print(json.dumps(info, indent=2, ensure_ascii=False))
    except PaError as exc:
        print("ошибка:", exc)
