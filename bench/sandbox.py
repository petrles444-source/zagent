"""Песочница прогона.

Задача выполняется в отдельной временной папке. Агент получает её как свой
``base_dir``, а ``make_guard`` делает её физической границей: писать за её
пределы агент не может даже с полным доступом. Ничего общего с реальным
проектом запуск не имеет.

Песочница также отличает **подложенные референсы** от **созданных агентом
файлов**. Без этого проверка «использовал ли эталон» всегда врала бы: референс
лежал бы рядом и считался бы результатом.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Папки, содержимое которых не считается результатом агента. Подложенные
#: эталоны лежат по исходным путям (``ref/...``, ``games/...``), поэтому
#: «служебными» считаются только явно помеченные папки и ``ref``.
INTERNAL_DIRS = (".ref", ".bench", "__pycache__", ".git", ".venv", "node_modules", "ref")

#: Расширения, которые не имеет смысла открывать как текст.
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip",
    ".gz", ".tar", ".whl", ".exe", ".dll", ".so", ".dylib", ".woff", ".woff2",
    ".ttf", ".otf", ".mp3", ".mp4", ".sqlite", ".db",
}


@dataclass
class RunResult:
    """Что получилось из запуска команды в песочнице."""

    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    timed_out: bool = False


@dataclass
class Sandbox:
    """Изолированная папка для одного прогона задания."""

    root: Path
    ref_dir: Path = field(init=False)
    keep: bool = False
    created: float = field(init=False, default_factory=time.time)
    staged_refs: list[str] = field(default_factory=list)
    commands: list[RunResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.ref_dir = self.root / ".ref"

    # ------------------------------------------------------------ жизненный цикл

    @classmethod
    def create(cls, *, keep: bool = False, prefix: str = "zagent-bench-") -> "Sandbox":
        path = Path(tempfile.mkdtemp(prefix=prefix))
        # mkdtemp даёт права 700 на POSIX; на Windows выставляем явно не нужно.
        box = cls(root=path, keep=keep)
        box.ref_dir.mkdir(exist_ok=True)
        return box

    def cleanup(self) -> None:
        if self.keep:
            return
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()

    # ------------------------------------------------------------------ референсы

    def stage_ref(self, source: Path, *, name: str | None = None,
                  original_path: str | None = None) -> str | None:
        """Скопировать эталон в песочницу и вернуть относительный путь.

        Эталон кладётся **по исходному пути из индекса**, а не в ``.ref/<id>``.
        Причина проверена на живом прогоне: модели читают ``games/snake/index.html``
        буквально, и если папка лежит под другим именем, агент честно сообщает
        «эталона нет» и отказывается работать. Совпадение имён снимает вопрос
        целиком.

        Копия нужна, потому что агент может править эталон под свою задачу —
        исходную библиотеку это не должно портить.
        """
        source = Path(source)
        if not source.is_dir():
            return None
        # Внутри песочницы исходный путь — это вложенная папка, а не `.ref`:
        # иначе агент всё равно ищет `games/snake` и не находит.
        name = name or source.name
        raw = original_path or f"ref/{name}"
        # Путь приходит из индекса эталонов. Индекс локальный и доверенный,
        # но `../../..` в нём записал бы файлы вне песочницы, и проверка
        # артефактов потом решила бы, что агент создал лишнее.
        if ".." in Path(raw).parts or Path(raw).is_absolute():
            return None
        target = self.root / raw
        try:
            # Проверяем результат, а не только вход: после разрешения пути
            # цель обязана лежать внутри песочницы.
            target.resolve().relative_to(self.root.resolve())
        except (ValueError, OSError):
            return None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, dirs_exist_ok=True)
        except OSError:
            return None
        rel = target.relative_to(self.root).as_posix()
        if rel not in self.staged_refs:
            self.staged_refs.append(rel)
        return rel

    def stage_index(self, source: Path | None = None) -> str | None:
        """Положить рядом с эталонами копию ``INDEX.yaml``.

        Индекс — часть библиотеки, а не служебный файл. Без него агент
        перебирает папки и гадает, что там есть.
        """
        index = Path(source) if source else None
        if index is None:
            return None
        if not index.is_file():
            return None
        target = self.root / "ref" / "INDEX.yaml"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(index, target)
        except OSError:
            return None
        return target.relative_to(self.root).as_posix()

    def read_ref(self, relative: str) -> str:
        """Прочитать эталон (для сборки подсказки агенту)."""
        path = self.root / relative
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    # -------------------------------------------------------------------- выводы

    def is_artifact(self, rel: Path) -> bool:
        """Файл создан агентом, а не подложен стендом.

        Список подложенных путей важнее списка служебных папок: эталон лежит по
        исходному пути из индекса (``games/snake``), и никакой список папок его
        не покроет. Сверка идёт по префиксу, поэтому агент, создавший свой файл
        рядом с эталоном, не теряет его из результата.
        """
        posix = rel.as_posix()
        for staged in self.staged_refs:
            root = staged.rstrip("/")
            if posix == root or posix.startswith(root + "/"):
                return False
        return not any(
            part in INTERNAL_DIRS or part.startswith(".")
            for part in rel.parts
        )

    def artifacts(self) -> dict[str, Path]:
        """Файлы, созданные агентом: всё, кроме подложенных эталонов и мусора."""
        found: dict[str, Path] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            if not self.is_artifact(rel):
                continue
            found[rel.as_posix()] = path
        return found

    def readable(self, relative: str) -> str | None:
        """Текст файла результата либо ``None``, если его нет или он бинарный."""
        path = self.root / relative
        if not path.is_file():
            return None
        if path.suffix.lower() in BINARY_SUFFIXES:
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if b"\x00" in data[:8000]:
            return None
        return data.decode("utf-8", errors="replace")

    def tree(self) -> str:
        """Дерево файлов для отчёта."""
        rows = []
        for rel in self.artifacts():
            depth = rel.count("/")
            rows.append("  " * depth + ("└ " if depth else "") + rel.split("/")[-1])
        return "\n".join(rows) if rows else "(пусто)"

    def _sandbox_path(self) -> str:
        return _sandbox_path()

    # -------------------------------------------------------------------- запуск

    def run(self, command: list[str], *, timeout: int = 300) -> RunResult:
        """Запустить команду внутри песочницы.

        Окружение собирается с нуля: системные переменные не должны утекать в
        проверку, иначе результат зависит от машины, а не от работы агента.
        """
        env = _sandbox_env(self.root)
        started = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                [str(part) for part in command],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                encoding="utf-8",
                errors="replace",
            )
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code = -1
            out = exc.stdout or ""
            err = f"не уложился в {timeout} с"
        except FileNotFoundError as exc:
            code, out, err = -1, "", f"команда не найдена: {exc}"

        result = RunResult(
            exit_code=code, stdout=out, stderr=err,
            duration_sec=time.monotonic() - started, timed_out=timed_out,
        )
        self.commands.append(result)
        return result

    def write(self, relative: str, body: str) -> Path:
        """Записать файл в песочницу (для входных данных задания)."""
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def describe(self) -> str:
        age = int(time.time() - self.created)
        state = "сохранена" if self.keep else "будет удалена"
        return f"{self.root} ({state}, возраст {age} с)"


def python() -> str:
    """Путь к интерпретатору: venv стенда, если он есть, иначе текущий."""
    candidate = Path(__file__).resolve().parent.parent / ".venv" / (
        "Scripts" if sys.platform == "win32" else "bin"
    ) / ("python.exe" if sys.platform == "win32" else "python")
    return str(candidate) if candidate.exists() else sys.executable


def _sandbox_env(root: Path) -> dict[str, str]:
    """Окружение для команды внутри песочницы.

    Собрано с нуля: системные переменные не должны утекать в проверку, иначе
    результат зависит от машины, а не от работы агента. Но «с нуля» не
    значит «выдумано»: системные каталоги берутся у самой системы, иначе на
    Windows подпроцесс не запустится вовсе.

    Общее для всех запусков: и `Sandbox.run`, и `checks._run` (проверки
    `tests_pass` и `command_succeeds`). Раньше у них были два разных
    окружения, и второе осталось POSIX — то есть эти две проверки не могли
    проходить на Windows, а молча падали.
    """
    return {
        "PATH": _sandbox_path(),
        "HOME": str(root),
        "USERPROFILE": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "LANG": "C.UTF-8",
        "TMPDIR": str(root),
        "TEMP": str(root),
        "TMP": str(root),
        # pytest не должен падать из-за отсутствия сети.
        "NO_PROXY": "*",
    }


def _sandbox_path() -> str:
    """PATH для команды внутри песочницы.

    Раньше здесь стоял `/usr/bin:/bin:/usr/local/bin` — POSIX-пути на
    Windows-машине. Команда не находила ни `python`, ни системные библиотеки:
    в Windows PATH нужен не только для поиска программ, но и для загрузки
    DLL, а `System32` в нём отсутствовал. То есть песочница работала только
    при запуске по абсолютному пути.

    Системные каталоги берутся у самой Windows, а не выдумываются: на другой
    машине и путь другой, и `SystemRoot` там тоже другой.
    """
    if not sys.platform.startswith("win"):
        return "/usr/bin:/bin:/usr/local/bin"
    parts = []
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    parts.append(str(Path(root) / "System32"))
    parts.append(str(Path(root)))
    # Каталог самого интерпретатора: без него `python` в песочнице не найдётся.
    if sys.executable:
        parts.append(str(Path(sys.executable).parent))
    return os.pathsep.join(dict.fromkeys(parts))