"""Инструменты агента: файлы, оболочка, скриншоты, браузер.

Инструменты — обычные функции, а не LLM-вызовы. Агент получает список
доступных инструментов, а Guard решает, что из него можно выполнить.

Приоритет текста и кода: основная работа агента — чтение, написание и правка
файлов. Визуальные инструменты (screenshot, browser) — вспомогательные, они
нужны там, где агент не может прочитать содержимое страницы или окна.
"""

from __future__ import annotations

import base64
import codecs
import inspect
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hub.autonomy import (
    Guard,
    inspect_shell,
    is_permission_request,
    permission_question,
)

#: Максимум символов, который читается из файла за раз.
READ_LIMIT = 200_000

#: Расширения, которые читаем как текст.
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".yml", ".yaml",
    ".toml", ".cfg", ".ini", ".sh", ".bat", ".ps1", ".html", ".css", ".sql",
    ".rs", ".go", ".java", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".xml",
    ".env", ".gitignore", ".dockerignore", ".lock",
}

#: Подписи бинарных форматов. Проверяются **только в начале файла**.
#:
#: Именно в начале: настоящая картинка начинается с подписи, а та же подпись
#: в середине текста — просто слово в комментарии. Раньше маркеры искались
#: как подстроки во всём файле, и `b"GIF8"` находился в самом этом модуле:
#: агент, читающий собственный исходник, получал «файл выглядит бинарным» —
#: файл, который определяет поиск бинарников, объявлял бинарным сам себя.
#: Проверено на проекте: из всех исходников ложно считывался один.
BINARY_MARKERS = (b"PK\x03\x04", b"\xff\xd8\xff", b"GIF87a", b"GIF89a",
                  b"\x89PNG\r\n\x1a\n", b"%PDF-", b"\x7fELF")


def looks_binary(head: bytes) -> bool:
    """Похож ли кусок файла на двоичный.

    Решение принимается по содержимому, а не по имени: расширение врёт
    регулярно, а содержимое врёт редко.

    Три признака, в порядке возрастания строгости:

    * **NUL-байты.** У текста их не бывает, у двоичного — почти всегда.
      UTF-16 читается как `i\0m\0p\0`, то есть NUL через байт: такой файл
      текстовый по смыслу, но нечитаемый как UTF-8, и оборачивать его надо
      в перекодировку, а не отвергать.
    * **Подпись формата в самом начале.** ZIP, JPEG, PNG, GIF, PDF, ELF.
      Только в начале: та же подпись в середине — это слово в комментарии.
    * **Не декодируется ни как UTF-8, ни как однобайтовая кодовая страница.**
      Последний и самый честный признак: если текст прочитался без потерь
      хоть одним из них, он текст, даже если в нём встретились странные
      байты. Файл в windows-1251 декодируется с ошибками как UTF-8, но
      читается прекрасно.
    """
    if not head:
        return False
    if b"\x00\x00\x00" in head:
        return True
    if head.startswith(BINARY_MARKERS):
        return True
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        # Не UTF-8 — но это ещё не значит «двоичный». Русский исходник,
        # сохранённый в windows-1251 (а таких файлов на любой русской машине
        # осталось немало), декодируется с ошибками и при этом читается
        # perfectly: это текст. Пробуем однобайтовые кодовые страницы, и если
        # сложилась хоть одна — перед нами текст в не-UTF-8.
        if _decodes_as_legacy(head):
            return False
        return _is_mostly_undecodable(head)
    return False


def _decodes_as_legacy(head: bytes) -> bool:
    """Складывается ли текст в одну из однобайтовых кодовых страниц.

    Само по себе «складывается» бесполезно: в однобайтовой кодировке
    раскладывается **любая** последовательность байтов, включая двоичный
    мусор. Поэтому результат проверяется на правдоподобие: у текста почти
    нет управляющих символов, а у мусора их сколько угодно.
    """
    for codec in _LEGACY_ENCODINGS:
        try:
            text = head.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
        if _looks_like_text(text):
            return True
    return False


def _looks_like_text(text: str) -> bool:
    """Правдоподобен ли текст: почти всё печатное, управляющих — минимум."""
    if not text:
        return False
    odd = sum(1 for ch in text
              if ord(ch) < 32 and ch not in "\t\r\n\f")
    if odd:
        # Допускается немного: у настоящего текста тоже встречаются
        # непечатные символы, но не треть содержимого.
        return odd <= len(text) * 0.02
    return True


def _is_mostly_undecodable(head: bytes) -> bool:
    """Почти весь файл не декодируется — значит он и правда не текст."""
    bad = 0
    index = 0
    while index < len(head):
        try:
            head[index:].decode("utf-8")
            break
        except UnicodeDecodeError as exc:
            index += max(1, exc.end - exc.start)
            bad += exc.end - exc.start
    return bad > len(head) * 0.1

#: Расширения, которые имеет смысл открывать в браузере. Остальное браузер
#: не покажет: .py откроется как текст, а не как страница, и кнопка «открыть»
#: станет обманом.
BROWSER_SUFFIXES = {
    ".html", ".htm", ".xhtml", ".svg", ".xml", ".pdf",
}

#: Расширения, которые браузер честно показывает как текст.
BROWSER_TEXT_SUFFIXES = {
    ".css", ".js", ".mjs", ".json", ".txt", ".md", ".csv", ".log",
}


def browser_url(path: str | Path) -> str:
    """Ссылка для открытия в браузере — или пустая строка.

    Пустая строка означает «открывать нечем», и интерфейс не рисует кнопку.
    Для каталога смотрим внутрь: агент обычно раскладывает сайт в папку с
    index.html, и открывать есть что, хотя сам каталог браузер не покажет.
    """
    target = Path(path)
    try:
        if target.is_dir():
            for name in ("index.html", "index.htm"):
                candidate = target / name
                if candidate.is_file():
                    return candidate.resolve().as_uri()
            return ""
        suffix = target.suffix.lower()
        if suffix not in BROWSER_SUFFIXES and suffix not in BROWSER_TEXT_SUFFIXES:
            return ""
        if not target.is_file():
            return ""
        return target.resolve().as_uri()
    except (OSError, ValueError):
        # На Windows путь с недопустимыми символами не превращается в URI.
        return ""


@dataclass
class ToolResult:
    """Результат инструмента."""

    ok: bool
    data: Any = None
    error: str | None = None
    needs_user: bool = False
    question: str = ""
    duration_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    #: Нужно решение пользователя о выходе за границу воркспейса.
    #: Отличается от needs_user: это всегда вопрос с однозначным «да/нет».
    needs_permission: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "needs_user": self.needs_user,
            "needs_permission": self.needs_permission,
            "question": self.question,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
        }


class ToolError(RuntimeError):
    """Инструмент не может выполнить операцию."""


# ------------------------------------------------------------------- файлы


def _default_base(guard: Guard | None) -> Path:
    """Рабочий каталог для относительных путей.

    Берётся корень воркспейса из guard. ``Path.cwd()`` как запасной вариант
    нужен только когда guard не передан: в этом случае вызывающий код сам
    разберётся, и молча подставлять каталог процесса опаснее, чем взять
    пустой базовый путь и получить абсолютный путь.
    """
    if guard is not None and guard.workspace_root:
        return Path(guard.workspace_root)
    return Path.cwd()


def _resolve(path: str | Path, base: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


#: Кодировки, в которых на Windows живут старые текстовые файлы. Проверяются по
#: порядку: сначала самая частая для русских .bat/.ini, потом остальные.
_LEGACY_ENCODINGS = ("cp1251", "cp1252", "cp866", "cp1250")


def _read_text_preserving(target: Path) -> tuple[str | None, str]:
    """Прочитать файл, не потеряв кодировку.

    Возвращает `(текст, кодировка)`. Текст `None` означает «это не текст в
    известной кодировке» — вызывающий обязан отказать, а не читать с
    ``errors="replace"``: подмена нечитаемых байтов на ``U+FFFD`` приводит к
    тому, что испорченный файл записывается обратно и выглядит валидным.

    Наличие BOM важно: без него файл в UTF-16 читается как мусор, и такая
    ошибка выглядит как «файл не в UTF-8», хотя это UTF-16.
    """
    raw = target.read_bytes()

    if _looks_binary(raw):
        return None, "двоичный файл"

    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8 с BOM"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        enc = "utf-16"
        try:
            return raw.decode(enc), f"{enc} с BOM"
        except UnicodeDecodeError:
            return None, "utf-16 с повреждённой меткой"

    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    for enc in _LEGACY_ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None, "неизвестная кодировка"


def _looks_binary(raw: bytes) -> bool:
    """Файл считается двоичным, если в нём есть нули или много непечатных байт.

    Проверка нужна, потому что однобайтовые кодировки декодируют почти что
    угодно: файл с байтами 0x00 0xFF 0xFE успешно «читается» как cp1251 и
    выглядит текстом с крякозябрами. Нулевой байт в тексте не встречается.
    """
    if b"\x00" in raw:
        return True
    if not raw:
        return False
    sample = raw[:4096]
    odd = sum(1 for byte in sample if byte < 9 or 13 < byte < 32)
    return odd / len(sample) > 0.05


def _write_atomic(target: Path, text: str) -> None | str:
    """Записать файл целиком, не оставляя его в промежуточном состоянии.

    Сначала пишем рядом временный файл, затем `os.replace`, который на Windows
    атомарен в пределах тома. Прямая запись обрезала файл до записи нового
    содержимого: сбой питания в этот момент оставлял пустой файл.

    Возвращает текст ошибки или None при успехе.
    """
    tmp = target.with_name(target.name + ".zagent-tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="")
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"Не удалось записать {target.name}: {exc}"
    return None


def _relative_if_inside(path: Path, base: Path) -> str:
    """Показать путь относительно рабочей директории, если он внутри неё.

    Модели гораздо реже ошибаются в относительных путях, а абсолютный путь
    Windows с обратными слэшами они регулярно пытаются писать «наизусть».
    """
    try:
        return str(path.relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(path)


def _refuse_self_deletion(target: Path, base: Path) -> str | None:
    """Отказать, если удаление снесёт воркспейс.

    Отказ вместо успеха по двум причинам. Первая: удалить корень воркспейса
    или его предка — значит снести всё, над чем агент работает, включая
    ``.git`` и ``.venv``, которые ``protected`` защищает только по строке пути.
    Вторая: цель может ещё не существовать, а ``Path.resolve()`` на Windows
    не поднимает симлинк — папка появится позже, и следующий вызов удалит уже
    её. Поэтому сравнение идёт по разыменованным путям обеих сторон.
    """
    try:
        root = base.resolve()
        goal = target.resolve()
    except OSError:
        return None

    if goal == root:
        return "Нельзя удалить корень воркспейса — это снесло бы всю работу"

    for parent in root.parents:
        if goal == parent:
            return (f"Нельзя удалить родителя воркспейса ({goal}) — "
                    "это снесло бы воркспейс целиком")

    return None


def read_file(path: str | Path, *, base: Path, offset: int = 0,
              limit: int | None = None) -> ToolResult:
    """Прочитать файл. Бинарные файлы отклоняются с понятным сообщением."""
    started = time.perf_counter()
    target = _resolve(path, base)
    if not target.is_file():
        return ToolResult(False, error=f"Файл не найден: {target}", duration_ms=_ms(started))

    size = target.stat().st_size
    if size > 8 * 1024 * 1024:
        return ToolResult(False, error=f"Файл слишком большой для чтения: {size} байт",
                          duration_ms=_ms(started))

    with target.open("rb") as handle:
        head = handle.read(4096)
        if looks_binary(head):
            # Здесь нечего спрашивать. Двоичный файл — это не препятствие
            # задаче, а один пропущенный файл: агент читает остальное сам.
            # Вопрос человеку останавливал всю работу из-за одного файла,
            # и спрашивать было не о чем — спрашивающий не мог ответить
            # «прочитай его как текст».
            return ToolResult(
                False,
                error=(f"{target.name} — двоичный файл, прочитать как текст "
                       f"нельзя. Пропусти его и работай дальше; если он "
                       f"нужен по смыслу задачи, скажи об этом в ответе."),
                duration_ms=_ms(started),
            )
        handle.seek(0)
        raw = handle.read(READ_LIMIT)

    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    window = lines[offset : offset + (limit or len(lines))]

    return ToolResult(
        True,
        data={
            "path": _relative_if_inside(target, base),
            "lines": len(lines),
            "size": size,
            "content": "\n".join(window),
            "offset": offset,
            "truncated": len(lines) > offset + (limit or len(lines)),
        },
        duration_ms=_ms(started),
    )


def write_file(path: str | Path, content: str, *, base: Path,
               append: bool = False) -> ToolResult:
    """Создать или перезаписать файл."""
    started = time.perf_counter()
    target = _resolve(path, base)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if append:
            with target.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        else:
            # Через `_write_atomic`, как `edit_file`. Прямая запись обрезает
            # файл до записи содержимого: сбой питания или убитый процесс в этот
            # момент оставляли пустой файл на месте прежнего. Агент перезаписывает
            # файлы постоянно, и потерянный файл — это потерянная работа.
            #
            # Возвращается текст ошибки, а не исключение: сбой записи не должен
            # выглядеть как сбой программы, иначе он уйдёт из `ToolResult` в
            # обработчик, который к таким ошибкам не готов.
            problem = _write_atomic(target, content)
            if problem:
                return ToolResult(False, error=problem,
                                  duration_ms=_ms(started))
    except OSError as exc:
        return ToolResult(False, error=f"Не удалось записать {target}: {exc}",
                          duration_ms=_ms(started))

    return ToolResult(
        True,
        data={
            "path": _relative_if_inside(target, base),
            "bytes": len(content.encode("utf-8")),
            "append": append,
        },
        duration_ms=_ms(started),
    )


def edit_file(path: str | Path, old: str, new: str, *, base: Path,
              replace_all: bool = False, allow_multiple: bool = False) -> ToolResult:
    """Точечная замена строки. Требует точного совпадения — как в коде.

    При нескольких вхождениях спрашивает пользователя, а не выбирает сам:
    молчаливая замена не того места — худший вид поломки.

    Файл обязан быть в UTF-8. Раньше читалось с ``errors="replace"``, и любой
    байт, невалидный в UTF-8, заменялся на ``U+FFFD`` — а потом файл целиком
    перезаписывался уже с крякозябрами и возвращал ``ok=True``. Один
    безобидный ``edit_file`` необратимо портил .bat, .ini и .srt в cp1251.
    Запись идёт через временный файл: сбой питания между усечением и записью
    оставлял пустой файл.
    """
    started = time.perf_counter()
    target = _resolve(path, base)
    if not target.is_file():
        return ToolResult(False, error=f"Файл не найден: {target}", duration_ms=_ms(started))

    text, encoding = _read_text_preserving(target)
    # Правим только UTF-8. Файл в cp1251 читается, но перезапись перевела бы
    # его в UTF-8, а русский текст превратился бы в крякозябры у всех, кто его
    # откроет в исходной кодировке. Это тихая порча содержимого, поэтому
    # отказ — единственный честный вариант.
    if text is None or not encoding.lower().startswith("utf-8"):
        return ToolResult(
            False,
            error=(
                f"{target.name} не в UTF-8 ({encoding}) — правка отключена, "
                "чтобы не испортить файл"
            ),
            needs_user=True,
            question=(
                f"{target.name} сохранён в кодировке {encoding}, а не в UTF-8. "
                "Переписать его в UTF-8? При этом русский текст может "
                "исказиться, если кодировка определена неверно."
            ),
            meta={"path": str(target), "encoding": encoding},
            duration_ms=_ms(started),
        )
    occurrences = text.count(old)
    if occurrences == 0:
        return ToolResult(
            False,
            error=f"Строка не найдена в {target.name}",
            needs_user=True,
            question=(
                f"Не нашёл строку для замены в {target.name}. "
                "Прислать содержимое файла, чтобы я подобрал точное совпадение?"
            ),
            duration_ms=_ms(started),
        )
    if occurrences > 1 and not (replace_all or allow_multiple):
        return ToolResult(
            False,
            error=f"Строка встречается {occurrences} раз в {target.name}",
            needs_user=True,
            question=(
                f"Строка встречается {occurrences} раз. Заменить все вхождения или только первое?"
            ),
            meta={"occurrences": occurrences},
            duration_ms=_ms(started),
        )

    if replace_all:
        updated = text.replace(old, new)
        replaced = occurrences
    else:
        updated = text.replace(old, new, 1)
        replaced = 1

    # BOM обязан выжить: без него файл меняет кодировку, и русский текст в
    # нём начинает читаться неверно у любого, кто откроет файл в Windows.
    if "BOM" in encoding:
        updated = "﻿" + updated

    written = _write_atomic(target, updated)
    if isinstance(written, str):
        return ToolResult(False, error=written, duration_ms=_ms(started))

    return ToolResult(
        True,
        data={"path": _relative_if_inside(target, base), "replacements": replaced},
        duration_ms=_ms(started),
    )


def delete_path(path: str | Path, *, base: Path, recursive: bool = False) -> ToolResult:
    """Удалить файл или каталог.

    Отказ, если цель — корень воркспейса или его предок. Список ``protected``
    проверяет строку пути, а не содержимое каталога, поэтому ``delete_path(".")``
    проходил мимо него: путь — «точка», а внутри воркспейса лежит ``.git``,
    который удалять нельзя. Агент решал «прибраться» и сносил рабочую папку
    целиком, а инструмент отчитывался об успехе.
    """
    started = time.perf_counter()
    target = _resolve(path, base)

    refused = _refuse_self_deletion(target, base)
    if refused is not None:
        return ToolResult(False, error=refused, duration_ms=_ms(started))

    if not target.exists():
        return ToolResult(False, error=f"Нечего удалять: {target}", duration_ms=_ms(started))

    try:
        if target.is_dir():
            if recursive:
                shutil.rmtree(target)
            else:
                target.rmdir()
        else:
            target.unlink()
    except OSError as exc:
        return ToolResult(False, error=f"Не удалось удалить {target}: {exc}",
                          duration_ms=_ms(started))

    return ToolResult(
        True,
        data={"path": _relative_if_inside(target, base), "recursive": recursive},
        duration_ms=_ms(started),
    )


def list_dir(path: str | Path, *, base: Path) -> ToolResult:
    """Содержимое каталога."""
    started = time.perf_counter()
    target = _resolve(path, base)
    if not target.is_dir():
        return ToolResult(False, error=f"Не каталог: {target}", duration_ms=_ms(started))

    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        try:
            stat = item.stat()
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": stat.st_size,
                "suffix": item.suffix,
                "is_text": item.suffix.lower() in TEXT_SUFFIXES,
            })
        except OSError:
            continue
    return ToolResult(
        True,
        data={"path": _relative_if_inside(target, base), "entries": entries},
        duration_ms=_ms(started),
    )


def search_text(pattern: str, path: str | Path, *, base: Path,
                glob: str = "**/*", max_results: int = 200) -> ToolResult:
    """Поиск по содержимому файлов."""
    started = time.perf_counter()
    root = _resolve(path, base)
    if not root.is_dir():
        return ToolResult(False, error=f"Не каталог: {root}", duration_ms=_ms(started))

    hits: list[dict[str, Any]] = []
    for file in root.glob(glob):
        if len(hits) >= max_results:
            break
        if not file.is_file() or file.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            for number, line in enumerate(
                file.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if pattern in line:
                    hits.append({
                        # Раньше здесь стояло префиксное сравнение строк:
                        # `C:\ws2\x` начинается с `C:\ws`, и файл из соседней
                        # папки показывался как лежащий внутри. `_relative_if_inside`
                        # сравнивает по компонентам и нечувствителен к регистру.
                        "path": _relative_if_inside(file, base),
                        "line": number,
                        "text": line.strip()[:200],
                    })
                    if len(hits) >= max_results:
                        break
        except OSError:
            continue

    return ToolResult(True, data={"hits": hits, "count": len(hits)},
                      duration_ms=_ms(started))


# ---------------------------------------------------------------- оболочка


#: Команды, которые в Windows встроены в cmd и не существуют как программы.
#: Через список аргументов их не запустить: `shutil.which("dir")` не находит
#: ничего, хотя команда рабочая. Модели пишут `dir`, `echo`, `type` постоянно,
#: и без этого списка каждая такая команда заканчивалась «не найдена».
WINDOWS_BUILTINS = frozenset({
    "assoc", "attrib", "break", "cd", "chcp", "chdir", "cls", "color", "copy",
    "date", "del", "dir", "echo", "endlocal", "erase", "exit", "for", "ftype",
    "goto", "if", "md", "mkdir", "mklink", "move", "path", "pause", "popd",
    "prompt", "pushd", "rd", "rem", "ren", "rename", "rmdir", "set", "setlocal",
    "shift", "start", "time", "title", "type", "ver", "verify", "vol",
})


#: Кодовые страницы, которые встречаются у консолей Windows. Нумерация
#: cp1252 — последняя, поэтому код 866 не конфликтует.
_CONSOLE_CODECS = ("cp866", "cp1251")


def _console_encoding() -> str:
    """Кодировка вывода консоли Windows.

    Берётся у системы, а не задаётся константой: OEM-кодовая страница зависит
    от настроек машины, и на другой Windows она будет другой.
    """
    if not sys.platform.startswith("win"):
        return "utf-8"
    try:
        import ctypes

        oem = int(ctypes.windll.kernel32.GetOEMCP())
    except (OSError, AttributeError, ValueError):
        oem = 0
    for name in _CONSOLE_CODECS:
        if oem == {"cp866": 866, "cp1251": 1251}.get(name):
            return name
    return "utf-8"


def _decode_output(raw: bytes | None, console_encoding: str) -> str:
    """Разобрать вывод команды, не испортив русский текст.

    Кодировки у команд разные, и угадать по одной нельзя: ``cmd /c echo`` на
    русской Windows пишет в OEM-866, а Python, запущенный из неё же, — в UTF-8.
    Поэтому сначала пробуем UTF-8 строгим разбором: если байты в неё
    складываются, значит писали в UTF-8. Не сложились — перед нами однобайтовая
    кодовая страница, и тогда берём ту, что назвала система.
    """
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(console_encoding, errors="replace")


def _split_command(command: str) -> tuple[str, list[str]]:
    """Разделить команду на программу и аргументы, уважая кавычки.

    Разбивка по пробелам ломала любую команду со строкой в кавычках:
    ``python -c "print(1)"`` предавалось как три аргумента, где второй —
    ``"print(1)"`` вместе с кавычками. Python такой код исполняет молча и
    ничего не печатает, поэтому выглядело это как « команда отработала, но
    пусто». Так переставал работать любой ``-c`` и любой путь с пробелом.

    Кавычки снимаются: дальше аргументы уходят в subprocess списком, а тот
    расставляет их сам по правилам операционной системы.
    """
    parts: list[str] = []
    current: list[str] = []
    quoted = False

    for char in command:
        if char == '"':
            # Переключатель режима, а не символ: кавычки в аргумент не идут.
            quoted = not quoted
            continue
        if char.isspace() and not quoted:
            if current:
                parts.append("".join(current))
                current = []
            continue
        current.append(char)

    if current:
        parts.append("".join(current))

    if not parts:
        return command, []
    return parts[0], parts[1:]


def run_shell(command: str, *, timeout: float = 120.0, cwd: str | Path | None = None,
              base: Path | None = None) -> ToolResult:
    """Выполнить команду оболочки.

    Команды выполняются через список аргументов (без shell=True), если возможно,
    иначе — через cmd/sh. Вывод ограничивается, чтобы агент не утонул в логах.

    Параметр ``base`` есть у всех инструментов: run_tool передаёт его безусловно.
    Без него в подписи он был бы лишним, и ``TypeError`` превращался в
    «неверные аргументы» — вечную ошибку, из-за которой инструмент не мог
    выполниться никогда, а агент об этом не знал.
    """
    started = time.perf_counter()
    inspection = inspect_shell(command)

    if cwd is None and base is not None:
        cwd = base

    is_windows = sys.platform.startswith("win")
    shell = (bool(inspection["multiline"]) or ("&&" in command) or ("|" in command)
         # Перенаправление тоже требует оболочки: `git log > out.txt` без `&&`
         # и `|` уходил в `subprocess` аргументами по отдельности, и git получал
         # два лишних — команда падала. Разбор выходных путей для проверки
         # границ этот же случай обрабатывал, то есть перенаправление было
         # задумано и просто не поддержано.
         or bool(re.search(r"\d?>{1,2}\s*\S", command)))
    # cmd.exe пишет в OEM-кодировке консоли (на русской Windows — 866), а не в
    # UTF-8, и при чтении как utf-8 русский текст превращался в иероглифы.
    # Сами байты разбирает _decode_output: он сначала пробует UTF-8, потому что
    # утилиты наподобие Python пишут именно в неё.
    encoding = _console_encoding() if is_windows else "utf-8"

    try:
        if shell:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=timeout,
                cwd=str(cwd) if cwd else None,
            )
        else:
            head, tail = _split_command(command)
            if is_windows and not shutil.which(head):
                # 7-Zip и часть утилит Windows живут как cmd-скрипты.
                head = f"{head}.exe" if shutil.which(f"{head}.exe") else head
            if is_windows and head.lower() in WINDOWS_BUILTINS:
                # Встроенная команда cmd: запускаемой программы нет, но сама
                # команда рабочая. Через `cmd /c` она выполняется, и вывод
                # возвращается в том же виде, что и у любой другой команды.
                completed = subprocess.run(
                    ["cmd", "/c", command],
                    capture_output=True,
                    timeout=timeout,
                    cwd=str(cwd) if cwd else None,
                )
            else:
                completed = subprocess.run(
                    [head, *tail],
                    capture_output=True,
                    timeout=timeout,
                    cwd=str(cwd) if cwd else None,
                )
        code = completed.returncode
        out = _decode_output(completed.stdout, encoding)
        err = _decode_output(completed.stderr, encoding)
    except subprocess.TimeoutExpired:
        return ToolResult(False, error=f"Команда не завершилась за {timeout:.0f} с",
                          duration_ms=_ms(started))
    except FileNotFoundError:
        return ToolResult(
            False,
            error=f"Команда не найдена: {command.split()[0] if command.split() else command}",
            needs_user=True,
            question=f"Не нашёл утилиту «{command.split()[0] if command.split() else command}». "
                     "Установить её или дать альтернативную команду?",
            duration_ms=_ms(started),
        )
    except OSError as exc:
        return ToolResult(False, error=f"Ошибка запуска: {exc}", duration_ms=_ms(started))

    output = (out or "")[-READ_LIMIT:]
    errors = (err or "")[-20_000:]
    return ToolResult(
        code == 0,
        data={"stdout": output, "stderr": errors, "code": code},
        error=None if code == 0 else f"Код возврата {code}",
        duration_ms=_ms(started),
        meta={"dangerous": inspection["dangerous"], "markers": inspection["markers"]},
    )


# -------------------------------------------------------------- скриншоты


def capture_screen(output: str | Path = "screenshots/screen.png", *,
                   base: Path | None = None) -> ToolResult:
    """Снимок экрана.

    Требует Pillow (Pillow>=10 для ImageGrab). Если библиотеки нет — понятная
    ошибка с инструкцией, а не исключение.

    Существующий файл не перезаписывается молча: агент с правом только на
    чтение мог указать путь чужого файла и затереть его картинкой.
    """
    started = time.perf_counter()
    target = Path(output)
    if not target.is_absolute():
        target = (base or Path.cwd()) / target

    # Снимок всегда замаскирован как «чтение» — иначе агент, которому нельзя
    # писать, не смог бы им воспользоваться вовсе. Но путь проверяется на
    # запись, потому что файл инструмент перезаписывает.
    if target.is_file() and target.stat().st_size > 0:
        return ToolResult(
            False,
            error=(
                f"Файл {target.name} уже существует — снимок его перезапишет. "
                "Укажите другое имя"
            ),
            needs_user=True,
            question=(
                f"{target.name} уже есть в папке. Перезаписать его снимком "
                "экрана или сохранить снимок под другим именем?"
            ),
            meta={"path": str(target)},
            duration_ms=_ms(started),
        )

    try:
        from PIL import ImageGrab  # type: ignore
    except ImportError:
        return ToolResult(
            False,
            error="Нужен Pillow для снимков экрана: pip install Pillow",
            needs_user=True,
            question="Установить Pillow, чтобы я мог делать скриншоты экрана?",
            duration_ms=_ms(started),
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(all_screens=False)
        image.save(target)
    except Exception as exc:
        return ToolResult(False, error=f"Не удалось сделать снимок: {exc}",
                          duration_ms=_ms(started))

    return ToolResult(
        True,
        data={"path": str(target), "width": image.width, "height": image.height},
        duration_ms=_ms(started),
    )


def image_to_data_url(path: str | Path, *, max_bytes: int = 4 * 1024 * 1024,
                      base: Path | None = None) -> ToolResult:
    """Прочитать картинку и вернуть как data-URL для vision-модели.

    ``base`` принимается ради единообразия с остальными инструментами:
    run_tool передаёт его всем, и без параметра в подписи вызов падал бы с
    TypeError. Заодно относительный путь теперь разрешается от рабочей
    директории, а не от текущей директости процесса.
    """
    started = time.perf_counter()
    source = _resolve(path, base) if base is not None else Path(path)
    if not source.is_file():
        return ToolResult(False, error=f"Картинка не найдена: {source}", duration_ms=_ms(started))

    size = source.stat().st_size
    if size > max_bytes:
        return ToolResult(
            False,
            error=f"Картинка слишком большая ({size} байт, лимит {max_bytes})",
            needs_user=True,
            question="Картинка больше 4 МБ. Сжать её перед отправкой модели?",
            duration_ms=_ms(started),
        )

    suffix = source.suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp",
            "gif": "gif"}.get(suffix, "png")
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    return ToolResult(True, data=f"data:image/{mime};base64,{encoded}",
                      duration_ms=_ms(started))


# ------------------------------------------------------------------ утилиты


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def mask_secret(value: str | None) -> str:
    """Показать ключ так, чтобы его нельзя было случайно унести из программы.

    Ключ попадает в DOM интерфейса, а страница тянет шрифты с CDN. Если
    подключение к CDN скомпрометировано, его скрипт прочитает всё, что лежит
    в странице, — вместе с ключами провайдеров. Полный ключ показывается
    только по прямому действию человека, и то на один вызов.

    Остаток выбран так, чтобы человек узнал свой ключ в списке из девяти, но
    не смог им воспользоваться.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 12:
        return "…" + text[-4:]
    return text[:6] + "…" + text[-4:]


#: Признаки абсолютного пути в произвольном месте команды. Проверяется по всей
#: строке, а не только после `>`: `del C:\x` и `copy a C:\b` — те же
#: абсолютные пути, просто стоят не там, где их ищет разбор перенаправлений.
#:
#: У UNC-пути отдельно запрещён хост `..`: иначе в `del ..\..\файл` двойная
#: обратная косая черта принималась за сетевую шару и путь получался таким,
#: который разрешиться не может. Ничего опасного, но в отчёте — мусор.
_ABSOLUTE_PATH = re.compile(
    r"""(?ix)
      (?: [A-Za-z]:[\\/]                            # C:\... или D:/...
        | \\\\(?!\.\.?[\\/]) [^\s\\/]+ [\\/]          # \\server\share
        | / (?:etc|usr|var|home|root|tmp|opt|mnt|Users|Volumes)\b
        | \%[A-Za-z_]+%                              # %USERPROFILE%, %TEMP%
        | \$\{?[A-Za-z_][A-Za-z0-9_]*\}? )           # $HOME, ${HOME}
    """
)


def _paths_in_command(command: str, base: Path) -> list[str]:
    """Найти в команде пути, которые выходят за пределы рабочей директории.

    Распознаются: перенаправления (`> путь`, `>> путь`), флаги вывода
    (`--output`, `-o`) и **любой** абсолютный путь в любом месте строки.

    Последнее — сознательный разворот: перебор всех форм записи в cmd
    (`del`, `copy a b`, `Set-Content`, `python -c`) бесконечен, а ложных
    тревог тут почти нет. Команда без абсолютных путей, без подстановок
    переменных и без `..` не выходит из воркспейса по определению:
    относительные пути разрешаются от рабочей директории.

    Список «непрозрачных» команд убран намеренно. Он требовал разрешения на
    каждую `python -m pytest` и `git status`, а толку не давал: сама команда
    в списке не доказывает выхода за границу, а проверка абсолютных путей
    ловит и `python -c "open(r'C:\\x','w')"`, и `curl -o C:\\y` — то есть
    ровно те случаи, ради которых список и составлялся.
    """
    text = str(command or "").strip()

    candidates: list[str] = []
    # Перенаправления вывода: `> файл`, `>> файл`, `2> файл`.
    for match in re.finditer(r"\d?>{1,2}\s*([^\s>|&;]+)", text):
        candidates.append(_absolute_guess(match.group(1), base))
    # Явные флаги вывода.
    for match in re.finditer(r"--(?:output|out-file|-o)\s+([^\s]+)", text):
        candidates.append(_absolute_guess(match.group(1), base))
    # Любой абсолютный путь или подстановка переменной окружения.
    for match in _ABSOLUTE_PATH.finditer(text):
        token = _clean_token(text[match.start():match.start() + 260])
        if token:
            candidates.append(_absolute_guess(token, base))
    # Путь вверх через `..`. Он не абсолютный, поэтому предыдущая проверка его
    # не видит: `del ..\..\документы\отчёт.docx` выглядит как команда без
    # путей вообще. Разрешается от рабочей папки — и уезжает наружу.
    for token in text.replace('"', " ").replace("'", " ").split():
        if ".." in Path(token.replace("\\", "/")).parts:
            candidates.append(_absolute_guess(token, base))

    # Повторы мешают только читать отчёт.
    seen: set[str] = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


#: Символы, которых в Windows-пути быть не может. По ним токен обрезается:
#: иначе из `python -c "open(r'C:\x','w')"` уедет путь с хвостом `,'w')`,
#: родитель которого — внутри воркспейса, и проверка решит, что всё в порядке.
_NOT_IN_PATH = '<>:"|?*,'

#: Символы, заканчивающие токен помимо пробела и разделителей оболочки.
_TOKEN_STOP = "|&;<>\r\n"


def _clean_token(text: str) -> str:
    r"""Первый осмысленный кусок строки: до пробела, скобки или запятой.

    Двоеточие обрезает токен не всегда: в `C:\путь` это буква диска, и без её
    обработки путь обрывался на втором символе и не проходил проверку.

    Обрезка нужна для ``python -c "open(r'C:\x','w')"`` — без неё в проверку
    уехал бы путь с хвостом ``,'w')``, чей родитель внутри воркспейса, и
    проверка пропустила бы запись наружу.
    """
    out = []
    for position, char in enumerate(text):
        if char.isspace() or char in _TOKEN_STOP or char in "(){}":
            break
        if char in _NOT_IN_PATH and not (char == ":" and position == 1):
            break
        out.append(char)
    token = "".join(out).strip("'\"")
    return token if len(token) > 2 else ""


def _absolute_guess(token: str, base: Path) -> str:
    """Привести токен из команды к абсолютному пути для проверки границы.

    Подстановки переменных окружения разворачиваются на этой же машине.
    Иначе `> "%TEMP%\\x"` остался бы путём вроде `projects/%TEMP%/x`, его
    родитель лежал бы внутри воркспейса, и проверка пропустила бы запись
    наружу — молча, с `ok=True`.
    """
    text = token.strip().strip("'\"")
    if not text:
        return str(base)
    text = os.path.expandvars(text)
    text = os.path.expanduser(text)
    candidate = Path(text)
    if candidate.is_absolute():
        return str(candidate)
    try:
        return str((base / candidate).resolve())
    except (OSError, RuntimeError):
        return str(base / text)


#: Реестр инструментов: имя -> (функция, требуемый доступ, описание для модели).
# ------------------------------------------------------- веб-ресёрч


def web_search(query: str, max_results: int = 6) -> ToolResult:
    """Найти в интернете.

    Отдельный инструмент, а не часть `run_shell` с `curl`: адреса внутренней
    сети отсекаются до запроса, и агент не может вытащить содержимое
    localhost'а или сетевого диска, подставив адрес в команду.
    """
    started = time.perf_counter()
    from hub.research import WebError, search_web

    try:
        hits = search_web(query, max_results=max_results)
    except WebError as exc:
        # Отказ поисковика и пустая выдача — разные вещи: в первом случае
        # надо работать с тем, что уже есть, во втором — спросить иначе.
        return ToolResult(False, error=str(exc), duration_ms=_ms(started))
    if not hits:
        return ToolResult(
            False,
            error="Ничего не нашлось. Сформулируй запрос иначе или скажи прямо, "
                  "что искал.",
            needs_user=True,
            question=f"По запросу «{query}» ничего не нашлось. Уточнить формулировку?",
            duration_ms=_ms(started),
        )
    return ToolResult(
        True,
        data={"query": query, "count": len(hits),
              "results": [hit.to_dict() for hit in hits]},
        duration_ms=_ms(started),
    )


def web_fetch(url: str, limit: int = 0) -> ToolResult:
    """Открыть страницу и вернуть её текст."""
    started = time.perf_counter()
    from hub.research import PAGE_CHARS, WebError, fetch_page

    try:
        page = fetch_page(url, limit=int(limit) or PAGE_CHARS)
    except WebError as exc:
        return ToolResult(False, error=str(exc), duration_ms=_ms(started))
    return ToolResult(True, data=page, duration_ms=_ms(started))


TOOLS: dict[str, dict[str, Any]] = {
    "read_file": {
        "fn": read_file,
        "operation": "read",
        "signature": "read_file(path, offset=0, limit=None)",
        "description": "Прочитать текстовый файл. Возвращает строки с нумерацией.",
    },
    "write_file": {
        "fn": write_file,
        "operation": "write",
        "signature": "write_file(path, content, append=False)",
        "description": "Создать файл или перезаписать его целиком.",
    },
    "edit_file": {
        "fn": edit_file,
        "operation": "edit",
        "signature": "edit_file(path, old, new, replace_all=False, allow_multiple=False)",
        "description": (
            "Заменить точную строку в файле. old должен совпадать посимвольно. "
            "Если строка встречается несколько раз и не задано replace_all или "
            "allow_multiple, инструмент спросит пользователя."
        ),
    },
    "delete_path": {
        "fn": delete_path,
        "operation": "delete",
        "signature": "delete_path(path, recursive=False)",
        "description": "Удалить файл или каталог. Необратимо.",
    },
    "list_dir": {
        "fn": list_dir,
        "operation": "list",
        "signature": "list_dir(path)",
        "description": "Показать содержимое каталога.",
    },
    "search_text": {
        "fn": search_text,
        "operation": "search",
        "signature": "search_text(pattern, path, glob='**/*')",
        "description": "Найти все вхождения строки в файлах каталога.",
    },
    "run_shell": {
        "fn": run_shell,
        "operation": "shell",
        "signature": "run_shell(command, timeout=120)",
        "description": "Выполнить команду в оболочке. Требует полного доступа.",
    },
    "capture_screen": {
        "fn": capture_screen,
        "operation": "screenshot",
        "signature": "capture_screen(output='screenshots/screen.png')",
        "description": "Снимок экрана. Картинку потом можно отдать vision-модели.",
    },
    "image_to_data_url": {
        "fn": image_to_data_url,
        "operation": "read",
        "signature": "image_to_data_url(path)",
        "description": "Закодировать картинку в data-URL для отправки модели.",
    },
    "web_search": {
        "fn": web_search,
        "operation": "browse",
        "signature": "web_search(query, max_results=6)",
        "description": (
            "Найти в интернете по текстовому запросу. Возвращает заголовок, "
            "адрес и короткое описание каждой найденной страницы."
        ),
    },
    "web_fetch": {
        "fn": web_fetch,
        "operation": "browse",
        "signature": "web_fetch(url, limit=0)",
        "description": (
            "Открыть страницу по адресу и вернуть её текст. Из страницы "
            "берётся примерно 4000 символов, поэтому длинную статью придётся "
            "читать частями по ссылкам."
        ),
    },
}

#: Инструменты, которые появляются только в режиме веб-разведки. В обычной
#: задаче их не видно: поиск в интернете стоит денег и времени, а по вопросу
#: «посчитай 2+2» он не нужен и только соблазняет модель им воспользоваться.
WEB_TOOLS = ("web_search", "web_fetch")


def _takes_base(fn: Any) -> bool:
    """Принимает ли инструмент `base` — рабочую директорию.

    Проверяется по подписи, а не «передать и поймать TypeError»: иначе
    инструмент без `base` (инструменты веба работают с адресом, а не с
    файлом) падал бы с сообщением об аргументах там, где на самом деле нет
    никакой ошибки.
    """
    import inspect

    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return True
    if "base" in parameters:
        return True
    # `**kwargs` принимает всё: по подписи нельзя сказать, что он не примет.
    return any(p.kind is inspect.Parameter.VAR_KEYWORD
               for p in parameters.values())


def available_tools(guard: Guard, *, web: bool = False) -> list[dict[str, Any]]:
    """Список инструментов, доступных при текущем уровне доступа."""
    out = []
    for name, spec in TOOLS.items():
        if name in WEB_TOOLS and not web:
            continue
        if guard.check_access(spec["operation"]).allowed:
            out.append({
                "name": name,
                "signature": spec["signature"],
                "description": spec["description"],
            })
    return out


def tool_arg_names(name: str) -> set[str]:
    """Какие аргументы инструмента положено принимать.

    Берётся из самой функции в реестре, а не из строки `signature`: строка нужна модели и может разойтись с кодом, а фильтр строится именно для того, чтобы не пропустить лишнее имя.
    """
    entry = TOOLS.get(name) or {}
    fn = entry.get("fn")
    if fn is None:
        return set()
    try:
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def run_tool(name: str, guard: Guard, /, *args: Any, **kwargs: Any) -> ToolResult:
    """Выполнить инструмент с проверкой доступа.

    Если доступа не хватает, а эскалация разрешена — результат с needs_user=True
    и вопросом пользователю, а не просто отказ.
    """
    spec = TOOLS.get(name)
    if spec is None:
        return ToolResult(False, error=f"Неизвестный инструмент: {name}. "
                                       f"Доступные: {', '.join(sorted(TOOLS))}")

    operation = spec["operation"]
    permission = guard.check_access(operation)
    if not permission.allowed:
        if guard.should_escalate(operation, permission.reason):
            return ToolResult(
                False,
                error=permission.reason,
                needs_user=True,
                question=(
                    f"Мне нужно «{operation}», но сейчас у меня уровень "
                    f"«{guard.access.label}». Повысить доступ до «{guard.escalation.label}»?"
                ),
            )
        return ToolResult(False, error=permission.reason)

    # Относительные пути агента относятся к корню воркспейса, а не к каталогу,
    # откуда запущен процесс. Иначе агент, работающий в отдельной папке, писал
    # бы в проект, запустивший его, и получал бы отказ «путь вне воркспейса»
    # на файле, который только что сам же открыл.
    base = kwargs.pop("base", None) or _default_base(guard)

    # Проверка пути — на разрешённом абсолютном пути. Относительный путь
    # не начинается с корня, поэтому проверять «сырое» значение бессмысленно.
    path_arg = kwargs.get("path") or kwargs.get("output")

    # Команда оболочки тоже может писать куда угодно: проверяем пути,
    # упомянутые внутри неё, иначе границу обойдёт одна строка в команде.
    if operation == "shell" and isinstance(kwargs.get("command"), str):
        candidates = _paths_in_command(kwargs["command"], base)
        for candidate in candidates:
            allowed, reason = guard.check_path(candidate, writing=True)
            if allowed:
                continue
            if is_permission_request(reason):
                return ToolResult(
                    False,
                    error=f"Нужно разрешение: {permission_question(reason)}",
                    needs_user=True,
                    needs_permission=True,
                    question=(
                        "Мне нужно выйти за пределы воркспейса.\n"
                        f"{permission_question(reason)}\n"
                        "Команда:\n" + str(kwargs["command"])[:300]
                    ),
                    meta={"path": candidate, "operation": operation},
                )
            return ToolResult(False, error=reason)
        if candidates:
            base = kwargs.pop("base", None) or _default_base(guard)
            if _takes_base(spec["fn"]):
                kwargs["base"] = base
            try:
                return spec["fn"](*args, **kwargs)
            except TypeError as exc:
                return ToolResult(False, error=f"Неверные аргументы для {name}: {exc}")
            except Exception as exc:
                return ToolResult(False, error=f"{name} упал: {type(exc).__name__}: {exc}")

    if isinstance(path_arg, (str, Path)) and operation in (
        "read", "write", "edit", "delete", "list", "search", "create", "mkdir", "screenshot"
    ):
        # Снимок экрана пишет файл, пусть и считается операцией чтения. Раньше он был
        # в списке «не пишет», и агент с уровнем «только чтение» перезаписывал
        # произвольный путь PNG-данными без всякого вопроса: разрушающая запись,
        # замаскированная под чтение.
        writing = operation not in ("read", "list", "search")
        resolved = _resolve(path_arg, base)
        allowed, reason = guard.check_path(str(resolved), writing=writing)
        if not allowed:
            # Мягкая граница: путь вне воркспейса, но пользователь может
            # разрешить. Это отдельный случай, его надо отличить от отказа
            # по уровню доступа — сообщение у них разное.
            if is_permission_request(reason):
                return ToolResult(
                    False,
                    error=f"Нужно разрешение: {permission_question(reason)}",
                    needs_user=True,
                    needs_permission=True,
                    question=(
                        f"Мне нужно выйти за пределы воркспейса.\n"
                        f"{permission_question(reason)}\n"
                        "Разрешить?"
                    ),
                    meta={"path": str(resolved), "operation": operation},
                )
            if guard.should_escalate(operation, reason):
                return ToolResult(False, error=reason, needs_user=True,
                                  question=f"{reason}. Разрешить этот путь?")
            return ToolResult(False, error=reason)

    # `base` передаётся только тем инструментам, у которых он есть в
    # подписи. Раньше он подставлялся всем, и инструмент без `base`
    # (инструменты веба работают с адресом, а не с файлом) падал с
    # «неверные аргументы» — то есть был недоступен в принципе.
    if _takes_base(spec["fn"]):
        kwargs["base"] = base

    try:
        return spec["fn"](*args, **kwargs)
    except TypeError as exc:
        # Отдельно отличаем «параметра base нет в подписи» от настоящей ошибки
        # вызова. Раньше это не различалось, и инструмент, не принимающий
        # base, не мог выполниться никогда — агент получал «неверные
        # аргументы» про параметр, которого он не передавал.
        return ToolResult(False, error=f"Неверные аргументы для {name}: {exc}")
    except Exception as exc:  # инструмент не должен ронять агента
        return ToolResult(False, error=f"{name} упал: {type(exc).__name__}: {exc}")


def tool_catalog_for_prompt(guard: Guard, *, web: bool = False) -> str:
    """Каталог инструментов в виде текста для системного промпта."""
    tools = available_tools(guard, web=web)
    if not tools:
        return "Инструменты недоступны при текущем уровне доступа."
    lines = [
        "Ты агент с доступом к файловой системе. Инструменты вызываешь через JSON:",
        '{"tool": "read_file", "args": {"path": "src/main.py"}}',
        "",
        "Доступные инструменты:",
    ]
    for tool in tools:
        lines.append(f"- {tool['signature']} — {tool['description']}")
    return "\n".join(lines)
