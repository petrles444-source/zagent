"""Воркспейсы: агент работает только внутри выбранной папки.

Зачем это нужно: агент с правом записи не должен трогать весь компьютер.
Воркспейс — это корень, внутри которого агент свободен, и всё, что снаружи,
для него закрыто.

Устройство:
    workspaces.json    список папок, каждая со своей конфигурацией агента
    <workspace>/       рабочая папка: сюда агент пишет файлы

Проверка путей двойная:
    1. Guard проверяет write_roots (уровень доступа)
    2. сам инструмент проверяет, что путь внутри воркспейса

Вторая проверка важна: она не зависит от режима автономии и не отключается
переменными окружения.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WORKSPACES_FILE = "workspaces.json"

#: Папка, в которой агент держит всё созданное.
#:
#: Раньше воркспейсом по умолчанию был корень проекта, и агент создавал
#: `calculator/` прямо в нём — рядом с кодом zagent. Выглядело это грязно,
#: и главное: непонятно было, что belongs проекту, а что результату работы.
#: Теперь результаты отделены: `projects/<имя задачи>/`, а код zagent лежит
#: на своём месте и не смешивается с тем, что агент нагенерировал.
PROJECTS_DIRNAME = "projects"


def projects_dir(root: str | Path | None = None) -> Path:
    """Папка под результаты работы агента. Создаётся при обращении."""
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    path = base / PROJECTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path

#: Что никогда не отдаётся агенту даже внутри воркспейса.
DEFAULT_PROTECTED = [
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".env", ".env.local", "secrets.local.json",
]


@dataclass
class Workspace:
    """Один воркспейс: папка и настройки агента в ней."""

    id: str
    name: str
    path: str
    access: int = 2
    autonomy: str = "normal"
    escalation: str = "auto"
    max_steps: int = 40
    protected: list[str] = field(default_factory=lambda: list(DEFAULT_PROTECTED))
    created_at: str = ""
    #: Правка собственного кода zagent. По умолчанию выключено, и это
    #: единственный режим, где агент пишет в файлы программы, а не в результат
    #: работы. Включается вручную и только на одну задачу.
    self_edit: bool = False

    def resolved(self) -> Path:
        return Path(self.path).expanduser().resolve()

    def exists(self) -> bool:
        return self.resolved().is_dir()

    def is_code_root(self, root: str | Path | None = None) -> bool:
        """Воркспейс ли это сам проект zagent.

        Определяем по совпадению с корнем репозитория. Проверка нужна, чтобы
        показать предупреждение: агент, который правит код программы, которая
        его же запускает, — это особый случай, и о нём надо сказать заранее.
        """
        base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
        try:
            return self.resolved() == base.resolve()
        except OSError:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "access": self.access,
            "autonomy": self.autonomy,
            "escalation": self.escalation,
            "max_steps": self.max_steps,
            "protected": self.protected,
            "created_at": self.created_at,
            "exists": self.exists(),
            "self_edit": self.self_edit,
            "is_code_root": self.is_code_root(),
        }

    def summary(self) -> str:
        return f"{self.name} — {self.resolved()}"


class WorkspaceError(RuntimeError):
    """Некорректный воркспейс."""


def workspaces_path(root: str | Path | None = None) -> Path:
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    return base / "config" / WORKSPACES_FILE


class WorkspaceManager:
    """Загружает, сохраняет и проверяет воркспейсы."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
        self.path = workspaces_path(self.root)
        self.items: list[Workspace] = []
        self.active_id: str = ""
        self.load()

    # ------------------------------------------------------------- загрузка

    def load(self) -> None:
        if not self.path.is_file():
            self.items = [self._default_workspace()]
            self.active_id = self.items[0].id
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.items = [self._default_workspace()]
            self.active_id = self.items[0].id
            return

        items: list[Workspace] = []
        for entry in data.get("workspaces") or []:
            if not isinstance(entry, dict):
                continue
            workspace_id = str(entry.get("id") or "").strip()
            path = str(entry.get("path") or "").strip()
            if not workspace_id or not path:
                continue
            items.append(Workspace(
                id=workspace_id,
                name=str(entry.get("name") or Path(path).name or workspace_id),
                path=path,
                access=int(entry.get("access") or 2),
                autonomy=str(entry.get("autonomy") or "normal"),
                escalation=str(entry.get("escalation") or "auto"),
                max_steps=int(entry.get("max_steps") or 40),
                protected=[str(p) for p in (entry.get("protected") or DEFAULT_PROTECTED)],
                created_at=str(entry.get("created_at") or ""),
                # По умолчанию выключено: правка собственного кода включается
                # руками на одну задачу, а не молча наследуется из файла.
                self_edit=bool(entry.get("self_edit", False)),
            ))

        if not items:
            items = [self._default_workspace()]

        self.items = items
        self.active_id = str(data.get("active") or items[0].id)
        if not self.get(self.active_id):
            self.active_id = items[0].id

    def _default_workspace(self) -> Workspace:
        # Воркспейс по умолчанию — папка projects/, а не корень проекта.
        # Иначе агент создаёт свои папки рядом с кодом zagent, и через
        # несколько задач в репозитории лежит вперемешку код и результаты.
        return Workspace(
            id="default",
            name="projects",
            path=str(projects_dir(self.root)),
            created_at="",
        )

    def save(self) -> None:
        payload = {
            "active": self.active_id,
            "workspaces": [
                {
                    "id": w.id,
                    "name": w.name,
                    "path": w.path,
                    "access": w.access,
                    "autonomy": w.autonomy,
                    "escalation": w.escalation,
                    "max_steps": w.max_steps,
                    "protected": w.protected,
                    "created_at": w.created_at,
                    "self_edit": w.self_edit,
                }
                for w in self.items
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # -------------------------------------------------------------- доступ

    def get(self, workspace_id: str) -> Workspace | None:
        for item in self.items:
            if item.id == workspace_id:
                return item
        return None

    @property
    def active(self) -> Workspace:
        workspace = self.get(self.active_id) or self.items[0]
        return workspace

    def activate(self, workspace_id: str) -> Workspace:
        workspace = self.get(workspace_id)
        if workspace is None:
            known = ", ".join(w.id for w in self.items)
            raise WorkspaceError(f"Воркспейс не найден: {workspace_id}. Есть: {known}")
        self.active_id = workspace_id
        self.save()
        return workspace

    def add(self, path: str, *, name: str | None = None, access: int = 2,
            autonomy: str = "normal", escalation: str = "auto",
                     create: bool = False) -> Workspace:
        """Добавить воркспейс.

        Папка должна существовать, но по умолчанию её можно создать: человек
        выбрал каталог в диалоге, а каталога с таким именем ещё нет — отказ
        здесь выглядел бы как «кнопка не работает». С `create=False` поведение
        прежнее: только проверка.
        """
        target = Path(path).expanduser()
        if not target.is_dir():
            if not create:
                raise WorkspaceError(f"Папка не найдена: {target}")
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise WorkspaceError(f"Не удалось создать папку {target}: {exc}")

        resolved = target.resolve()
        for item in self.items:
            if item.resolved() == resolved:
                raise WorkspaceError(f"Этот путь уже добавлен как «{item.name}»")

        workspace_id = _slugify(name or resolved.name)
        counter = 1
        while self.get(workspace_id):
            counter += 1
            workspace_id = f"{_slugify(name or resolved.name)}-{counter}"

        workspace = Workspace(
            id=workspace_id,
            name=name or resolved.name,
            path=str(resolved),
            access=access,
            autonomy=autonomy,
            escalation=escalation,
            created_at=__import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.items.append(workspace)
        self.save()
        return workspace

    def remove(self, workspace_id: str) -> None:
        if len(self.items) <= 1:
            raise WorkspaceError("Нельзя удалить последний воркспейс")
        workspace = self.get(workspace_id)
        if workspace is None:
            raise WorkspaceError(f"Воркспейс не найден: {workspace_id}")
        self.items = [w for w in self.items if w.id != workspace_id]
        if self.active_id == workspace_id:
            self.active_id = self.items[0].id
        self.save()

    def update(self, workspace_id: str, **fields: Any) -> Workspace:
        """Изменить настройки воркспейса (не путь)."""
        workspace = self.get(workspace_id)
        if workspace is None:
            raise WorkspaceError(f"Воркспейс не найден: {workspace_id}")
        if "access" in fields:
            workspace.access = int(fields["access"])
        if "autonomy" in fields:
            workspace.autonomy = str(fields["autonomy"])
        if "escalation" in fields:
            workspace.escalation = str(fields["escalation"])
        if "max_steps" in fields:
            workspace.max_steps = int(fields["max_steps"])
        if "name" in fields and fields["name"]:
            workspace.name = str(fields["name"])
        if "protected" in fields and isinstance(fields["protected"], list):
            workspace.protected = [str(p) for p in fields["protected"]]
        if "self_edit" in fields:
            workspace.self_edit = bool(fields["self_edit"])
        self.save()
        return workspace

    # ------------------------------------------------------------ проверка

    def contains(self, workspace_id: str, target: str | Path) -> bool:
        """Находится ли путь внутри воркспейса."""
        workspace = self.get(workspace_id)
        if workspace is None:
            return False
        try:
            resolved = Path(target).expanduser().resolve()
        except (OSError, RuntimeError):
            return False
        root = workspace.resolved()
        if resolved == root:
            return True
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            return False

    def describe(self) -> dict[str, Any]:
        """Состояние воркспейсов для интерфейса.

        Вместе со списком отдаём папку по умолчанию для результатов и флаг
        «это сам zagent»: без него нельзя отличить рабочую папку от папки с
        кодом программы, а это единственный случай, где агент пишет в софт,
        который сейчас чинит.
        """
        return {
            "active": self.active_id,
            "workspaces": [w.to_dict() for w in self.items],
            "config_path": str(self.path),
            "projects_dir": str(projects_dir(self.root)),
            "code_root": str(Path(self.root).resolve()),
        }


def _slugify(text: str) -> str:
    """Имя воркспейса в безопасный идентификатор."""
    cleaned = "".join(
        c if c.isalnum() or c in "-_" else "-" for c in text.strip().lower()
    )
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "workspace"
