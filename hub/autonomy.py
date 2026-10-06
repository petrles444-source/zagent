"""Уровни доступа и режимы работы агента.

Три независимых измерения:

ACCESS_LEVEL — насколько агент может трогать систему
    read      только читать файлы
    write     читать и создавать/править файлы
    full      плюс удалять, запускать процессы, ходить в сеть

AUTONOMY — как агент принимает решения
    yolo      решает сам, не спрашивает ничего
    normal    спрашивает перед рискованными операциями
    strict    спрашивает перед каждой операцией изменения
    plan      сначала строит план, ждёт одобрения, потом выполняет

ESCALATION — агент может попросить пользователя о помощи, когда не справляется
    off       никогда не просить
    auto      просить, только если задача невыполнима без человека
    on        просить при любой неуверенности

Матрица доступа: каждая операция помечена минимальным уровнем. Агент с уровнем
ниже必要ного получает отказ — либо спрашивает пользователя (если escalation on).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Enum
import fnmatch
from pathlib import Path
from typing import Any


class AccessLevel(IntEnum):
    """Уровни доступа к файловой системе и процессам. Больше — больше прав."""

    READ = 1
    WRITE = 2
    FULL = 3

    @property
    def label(self) -> str:
        return {1: "только чтение", 2: "чтение и запись", 3: "полный доступ"}[int(self)]


class Autonomy(str, Enum):
    """Как агент принимает решения."""

    YOLO = "yolo"
    NORMAL = "normal"
    STRICT = "strict"
    PLAN = "plan"

    @property
    def label(self) -> str:
        return {
            "yolo": "полная автономия",
            "normal": "обычный",
            "strict": "с подтверждением",
            "plan": "с планом",
        }[self.value]


class Escalation(str, Enum):
    """Может ли агент просить пользователя о помощи."""

    OFF = "off"
    AUTO = "auto"
    ON = "on"

    @property
    def label(self) -> str:
        return {
            "off": "не просить",
            "auto": "тогда, когда иначе никак",
            "on": "при любой неуверенности",
        }[self.value]


#: Операции и минимальный требуемый уровень доступа.
OPERATION_ACCESS = {
    "read": AccessLevel.READ,
    "list": AccessLevel.READ,
    "search": AccessLevel.READ,
    "glob": AccessLevel.READ,
    "stat": AccessLevel.READ,
    "screenshot": AccessLevel.READ,
    "browse": AccessLevel.READ,
    "write": AccessLevel.WRITE,
    "edit": AccessLevel.WRITE,
    "create": AccessLevel.WRITE,
    "mkdir": AccessLevel.WRITE,
    "delete": AccessLevel.FULL,
    "move": AccessLevel.FULL,
    "shell": AccessLevel.FULL,
    "install": AccessLevel.FULL,
}

#: Операции, которые разрушительны: по умолчанию требуют подтверждения.
DESTRUCTIVE_OPS = {"delete", "move", "install", "shell"}

#: Операции, которые меняют систему, но не разрушительны.
MUTATING_OPS = {"write", "edit", "create", "mkdir"}


@dataclass
class Permission:
    """Решение по одной операции."""

    allowed: bool
    reason: str = ""
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass
class Guard:
    """Политика доступа: проверяет операции перед выполнением.

    Пути: защищённые от записи/удаления даже при FULL (репозиторий, .git,
    системные каталоги) — защита от того, чтобы агент снёс сам себя.
    """

    access: AccessLevel = AccessLevel.READ
    autonomy: Autonomy = Autonomy.NORMAL
    escalation: Escalation = Escalation.AUTO
    protected: list[str] = field(default_factory=lambda: [".git", ".venv", "node_modules"])
    write_roots: list[str] = field(default_factory=list)
    read_roots: list[str] = field(default_factory=list)
    confirmed: set[str] = field(default_factory=set)

    #: Абсолютный путь воркспейса. Если задан, агент не может выйти за него
    #: ни при каком уровне доступа — это граница, а не разрешение.
    workspace_root: str | None = None
    #: id воркспейса (для сообщений об ошибке).
    workspace_id: str | None = None
    #: Пути, на которые пользователь явно разрешил выход.
    #: Заполняется из хранилища при старте задачи и при ответе пользователя.
    granted_paths: list[str] = field(default_factory=list)
    #: Пути, по которым пользователь отказал. Нужны, чтобы агент не
    #: зациклился: иначе после отказа он повторит тот же вызов, снова
    #: упрётся в границу и снова спросит — и так до лимита шагов.
    denied_paths: list[str] = field(default_factory=list)
    #: Маски путей в запрете, относительно корня воркспейса.
    #:
    #: Нужны для субагентов: одна часть объявляет `assets/*.css`, другая —
    #: `assets/app.js`. Свести маску к папке нельзя, иначе вторая часть
    #: получит запрет на собственную работу, потому что её файл лежит
    #: внутри папки первой.
    denied_globs: list[str] = field(default_factory=list)
    #: Разрешать выход за границу по запросу. False — жёсткая граница,
    #: True — агент спрашивает пользователя и ждёт ответа.
    soft_boundary: bool = True

    def set_workspace(self, root: str | Path, workspace_id: str | None = None,
                      *, granted: list[str] | None = None,
                      denied: list[str] | None = None,
                      soft_boundary: bool = True) -> None:
        """Ограничить агента папкой воркспейса."""
        self.workspace_root = str(Path(root).expanduser().resolve())
        self.workspace_id = workspace_id
        self.soft_boundary = soft_boundary
        self.granted_paths = [str(Path(p).expanduser().resolve()) for p in (granted or [])]
        self.denied_paths = [str(Path(p).expanduser().resolve()) for p in (denied or [])]
        # write_roots дополняется, чтобы действовали обе проверки.
        resolved = self.workspace_root.replace("\\", "/").rstrip("/").lower()
        if not any(r.replace("\\", "/").rstrip("/").lower() == resolved
                   for r in self.write_roots):
            self.write_roots.insert(0, self.workspace_root)

    def grant_path(self, path: str) -> None:
        """Разрешить выход за границу воркспейса на конкретный путь."""
        resolved = str(Path(path).expanduser().resolve())
        if resolved not in self.granted_paths:
            self.granted_paths.append(resolved)
        # Отказ был отменён: путь снова можно запрашивать.
        self.denied_paths = [p for p in self.denied_paths
                             if not self._inside(p, resolved)]

    def deny_path(self, path: str) -> None:
        """Запомнить отказ пользователя, чтобы не спрашивать по кругу."""
        resolved = str(Path(path).expanduser().resolve())
        if resolved not in self.denied_paths:
            self.denied_paths.append(resolved)

    def inside_workspace(self, path: str) -> bool:
        """Путь внутри воркспейса. Без воркспейса проверка не действует."""
        if not self.workspace_root:
            return True
        if self._inside(self.workspace_root, path):
            return True
        # Явно разрешённые пути тоже считаются своими.
        return any(self._inside(granted, path) for granted in self.granted_paths)

    @staticmethod
    def _inside(root: str, path: str) -> bool:
        root_norm = str(root).replace("\\", "/").rstrip("/").lower()
        target = str(path).replace("\\", "/").rstrip("/").lower()
        if target == root_norm:
            return True
        return target.startswith(root_norm + "/")

    def outside_workspace(self, path: str) -> bool:
        """Путь точно вне воркспейса и не покрыт разрешениями."""
        if not self.workspace_root:
            return False
        return not self.inside_workspace(path)

    # -------------------------------------------------------------- проверки

    def check_access(self, operation: str) -> Permission:
        """Хватает ли уровня доступа для операции."""
        required = OPERATION_ACCESS.get(operation, AccessLevel.FULL)
        if self.access < required:
            return Permission(
                allowed=False,
                reason=(
                    f"Операция «{operation}» требует уровня «{required.label}», "
                    f"а у агента «{self.access.label}»"
                ),
            )

        if operation in DESTRUCTIVE_OPS and self.access < AccessLevel.FULL:
            return Permission(
                allowed=False,
                reason=f"«{operation}» разрушительна и требует полного доступа",
            )
        return Permission(allowed=True)

    def needs_confirmation(self, operation: str, target: str = "") -> bool:
        """Нужно ли подтверждение пользователя по режиму автономии."""
        key = f"{operation}:{target}"
        if key in self.confirmed:
            return False
        if self.autonomy is Autonomy.YOLO:
            return False
        if self.autonomy is Autonomy.STRICT:
            return True
        if self.autonomy is Autonomy.NORMAL:
            # `shell` из правил убран **намеренно**, и это не смягчение.
            #
            # В `DESTRUCTIVE_OPS` команда значит «разрушительна», и по списку
            # выходило, что обычный режим спрашивает перед каждой командой —
            # включая `git status`. На любой реальной задаче это превращается
            # в диалог из десятков одинаковых вопросов, то есть режим просто
            # непригоден; а «спрашивать всё подряд» — это уже `STRICT`.
            #
            # Для команды точная проверка уже есть: список опасных разбирается
            # **до** выполнения (`_dangerous_shell` в `hub/agent.py`), и
            # `rm -rf`, `format`, `git reset --hard` спрашиваются всегда, кроме
            # YOLO. Список опасных команд работает точнее, чем вопрос перед
            # всем подряд, поэтому он и остаётся единственным для `shell`.
            if operation == "shell":
                return False
            return operation in DESTRUCTIVE_OPS or operation in MUTATING_OPS
        # PLAN: подтверждается план целиком, отдельные операции — нет.
        return False

    def confirm(self, operation: str, target: str = "") -> None:
        """Запомнить подтверждение пользователя."""
        self.confirmed.add(f"{operation}:{target}")

    def check_path(self, path: str, *, writing: bool) -> tuple[bool, str]:
        """Проверить путь: защищённые каталоги и границы write_roots."""
        normalized = str(path).replace("\\", "/")
        parts = normalized.split("/")

        if writing:
            for protected in self.protected:
                if f"/{protected}/" in f"/{normalized}/" or normalized.endswith(f"/{protected}"):
                    return False, f"Путь защищён от изменений: {protected}"
        else:
            for protected in self.protected:
                if f"/{protected}/" in f"/{normalized}/":
                    return False, f"Путь защищён даже от чтения: {protected}"

        # Граница воркспейса проверяется всегда и не зависит от уровня
        # доступа: это стена, а не ключ, который можно получить.
        # В мягком режиме стена превращается в вопрос пользователю, поэтому
        # здесь нужен особый код возврата.
        # Разрешённые пользователем пути пропускаем обе проверки: grant_path()
        # сознательно НЕ расширяет write_roots, иначе разрешение на один файл
        # открыло бы всю родительскую папку, а на Windows — целый диск.
        if self._is_granted(normalized):
            return True, ""

        # Область чужой части. Проверяется и на чтение, и на запись: если
        # часть объявила свои файлы, она не должна даже подсматривать в
        # соседние, иначе две части напишут один и тот же файл «под влиянием»
        # того, что одна из них прочитала чужую половину.
        if self._matches_denied_glob(normalized):
            return False, (
                "Это область другой части работы. Она выполняется параллельно "
                "и её файлы нельзя трогать. Сделай свою часть в своих файлах."
            )

        if self.workspace_root and not self.inside_workspace(normalized):
            reason = (
                f"Путь вне воркспейса «{self.workspace_id or self.workspace_root}»: "
                f"{path}"
            )
            # Отказ пользователя важнее мягкой границы: он уже сказал «нет»,
            # и повторный вопрос по тому же пути только докучает. Отказ касается
            # только выхода наружу — внутри воркспейса он не действует.
            if self._is_denied(normalized):
                return False, (
                    f"{reason}. В доступе отказано, повторно не спрашиваю — "
                    "обойдись без этого пути."
                )
            # Полный доступ — это уже ответ на вопрос «можно ли выходить
            # наружу». Спрашивать ещё раз значило бы докучать пользователю
            # вопросом, на который он сам же и ответил выбором уровня доступа.
            if self.access is AccessLevel.FULL and self.soft_boundary:
                return True, ""

            if self.soft_boundary:
                return False, PERMISSION_PREFIX + reason
            return False, (
                f"Путь вне воркспейса «{self.workspace_id or self.workspace_root}». "
                f"Разрешено только внутри: {self.workspace_root}"
            )

        if self.write_roots and writing:
            if not self._inside_roots(normalized):
                roots = ", ".join(str(r) for r in self.write_roots)
                return False, f"Запись разрешена только внутри: {roots}"

        return True, ""

    def _is_granted(self, normalized: str) -> bool:
        """Путь покрыт явным разрешением пользователя."""
        return any(self._inside(granted, normalized) for granted in self.granted_paths)

    def _is_denied(self, normalized: str) -> bool:
        """Пользователь уже отказал в доступе к этому пути."""
        return any(self._inside(denied, normalized) for denied in self.denied_paths)

    def _matches_denied_glob(self, normalized: str) -> bool:
        """Путь попадает в маску из запрета.

        Маски заданы относительно корня воркспейса, а `normalized` —
        полный путь. Поэтому сначала отрезаем корень: иначе маска
        `assets/*.css` никогда не совпадёт, а запрет будет пустым и
        субагенты перепишут друг друга.
        """
        if not self.denied_globs or not self.workspace_root:
            return False
        root = self.workspace_root.replace("\\", "/").rstrip("/").lower()
        # Приводим к нижнему регистру оба: иначе сравнение префиксов
        # не проходит, потому что `resolve()` возвращает путь с настоящим
        # регистром, а Windows ему не подчиняется.
        low = normalized.lower()
        if not low.startswith(root + "/"):
            return False
        relative = low[len(root) + 1:]
        return any(fnmatch.fnmatch(relative, pattern)
                   for pattern in self.denied_globs)

    def _inside_roots(self, normalized: str) -> bool:
        """Проверить, что путь внутри одного из разрешённых корней.

        Сравнение регистронезависимое и по границам компонентов: путь должен
        начинаться с корня целиком, иначе «/repo-evil» прошёл бы проверку для
        корня «/repo».
        """
        target = normalized.replace("\\", "/").rstrip("/")
        target_lower = target.lower()

        for root in self.write_roots:
            root_formatted = str(root).replace("\\", "/").rstrip("/").lower()
            if not root_formatted:
                continue
            if target_lower == root_formatted:
                return True
            if target_lower.startswith(root_formatted + "/"):
                return True
        return False

    def should_escalate(self, operation: str, error: str) -> bool:
        """Нужно ли просить пользователя о помощи."""
        if self.escalation is Escalation.OFF:
            return False
        if self.escalation is Escalation.ON:
            return True

        # AUTO: только если операция в принципе недоступна этому уровню,
        # либо провайдер не дал добиться результата.
        if self.check_access(operation).allowed:
            return False
        blocked_markers = (
            "requires", "требует уровня", "защищён", "только внутри",
            "login", "капча", "captcha", "403", "401", "нет доступа",
        )
        return any(marker in error.lower() for marker in blocked_markers)

    def describe(self) -> dict[str, Any]:
        return {
            "access": int(self.access),
            "access_label": self.access.label,
            "autonomy": self.autonomy.value,
            "autonomy_label": self.autonomy.label,
            "escalation": self.escalation.value,
            "escalation_label": self.escalation.label,
            "protected": list(self.protected),
            "write_roots": list(self.write_roots),
            "workspace_root": self.workspace_root,
            "workspace_id": self.workspace_id,
            "confirmed": sorted(self.confirmed),
        }


#: Префикс сообщения, которым check_path сигнализирует о необходимости
#: спросить пользователя о выходе за границу воркспейса.
PERMISSION_PREFIX = "needs_permission:"


def is_permission_request(reason: str) -> bool:
    """Требуется ли разрешение пользователя на этот путь."""
    return str(reason or "").startswith(PERMISSION_PREFIX)


def permission_question(reason: str) -> str:
    """Превратить служебное сообщение в вопрос для пользователя."""
    return str(reason or "")[len(PERMISSION_PREFIX):].strip()


#: Опасные кучки команд — при их наличии требуется полный доступ и подтверждение.
DANGEROUS_SHELL = (
    "rm -rf", "rm -fr", "format", "del /f", "diskpart", "mkfs",
    "shutdown", "restart-computer", "reg delete", "takeown", "icacls",
    "curl", "wget", "invoke-webrequest", "remove-item", "rmdir /s",
    "git push --force", "git reset --hard", "pip uninstall", "npm uninstall -g",
)


def inspect_shell(command: str) -> dict[str, Any]:
    """Разобрать команду оболочки: опасные подстроки, длина, типы операций."""
    low = command.lower()
    found = [marker for marker in DANGEROUS_SHELL if marker in low]
    return {
        "command": command,
        "dangerous": bool(found),
        "markers": found,
        "length": len(command),
        "multiline": "\n" in command,
    }
