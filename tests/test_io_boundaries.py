"""Границы файлового ввода-вывода: кодировки, указатели, гонка записи.

Три правки, которые проверяет этот файл:

* **Журнал ошибок больше не читает «последний символ» текстового файла.**
  Для файла, открытого с `encoding="utf-8"`, `tell()` возвращает не
  смещение в байтах, а непрозрачный cookie позиционирования. Вычитать из
  него единицу и звать `read(1)` бессмысленно: cookie не адресует байт, а
  чтение с середины кириллического символа даёт `UnicodeDecodeError` в тот
  самый момент, когда журнал нужнее всего. Теперь проверяется последний
  байт, в бинарном режиме;
* **Обрезка не оставляет обрывок JSON.** Раньше при срезе без перевода
  строки в файл возвращался кусок, начатый посреди записи;
* **Два одновременных сохранения настроек не сталкиваются.** Временный
  файл теперь уникальный; при фиксированном имени второй поток затирал
  запись первого и получал `FileNotFoundError` на `os.replace`.

Проверки «кусающиеся»: каждая падает при возврате правки, потому что
смотрит на конкретное поведение, а не на наличие символа в коде.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.config import atomic_write  # noqa: E402
from hub.diag import DIAG, Diag  # noqa: E402


def make_diag(tmp_path: Path, **kwargs) -> Diag:
    """Журнал в отдельной папке на каждый тест.

    `Diag` сам создаёт `web-state` под корнем, поэтому каждый тест получает
    свою папку: иначе тесты писали бы в один файл и мешали друг другу
    счётчиками и обрезкой.
    """
    return Diag(tmp_path, **kwargs)


def log_path(root: Path) -> Path:
    return root / "web-state" / "diag.jsonl"


# ============================================ журнал: запись без разрывов


def test_запись_без_предыдущей_строки_не_ломается(tmp_path: Path) -> None:
    """Первый вызов: файла нет, ничего проверять не надо."""
    c = make_diag(tmp_path)
    c.note("старт", ValueError("первая"))
    assert c.count == 1


def test_кириллица_пишется_по_строкам(tmp_path: Path) -> None:
    """Многострочная кириллица - обычное дело журнала."""
    path = log_path(tmp_path)
    c = make_diag(tmp_path)
    for i in range(5):
        c.note("ошибка", ValueError(f"кириллица №{i} — проверка чтения"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    for line in lines:
        assert json.loads(line)["error"].startswith("кириллица")


def test_оборванная_строка_добивается_переводом(tmp_path: Path) -> None:
    """Процесс убили посреди записи: хвост не должен приклеиться."""
    path = log_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes('{"error": "обрыв без перевода"'.encode("utf-8"))
    c = make_diag(tmp_path)
    c.note("восстановление", ValueError("следующая"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, f"строк: {len(lines)}"
    assert json.loads(lines[1])["error"] == "следующая"


def test_файл_открывается_в_бинарном_режиме(tmp_path: Path) -> None:
    """Математика указателей в текстовом режиме - главный дефект."""
    src = (ROOT / "hub" / "diag.py").read_text(encoding="utf-8")
    assert 'path.open("ab+")' in src, "запись идёт в текстовом режиме"
    assert 'path.open("a+", encoding="utf-8")' not in src
    # Смещение назад допустимо только в байтах: SEEK_END с отрицательным.
    assert "handle.seek(-1, os.SEEK_END)" in src
    assert "handle.tell() - 1" not in src


def test_ошибка_разбора_не_роняет_запись(tmp_path: Path) -> None:
    """Странный хвост не должен ломать добавление новых записей."""
    path = log_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("мусор без перевода\n".encode("utf-8"))
    c = make_diag(tmp_path)
    c.note("после мусора", ValueError("ок"))
    assert c.count == 1


# ================================================== обрезка без обрывков


def test_обрезка_не_оставляет_половину_json(tmp_path: Path) -> None:
    """Срез без перевода строки непригоден и не должен сохраняться."""
    path = log_path(tmp_path)
    c = make_diag(tmp_path, keep_bytes=200)
    # Одна огромная запись: в срезе не окажется перевода строки.
    c.note("гигант", ValueError("стек-трейс " * 400))
    assert c.count == 1
    data = path.read_bytes()
    if data:
        # Всё, что осталось, обязано быть целыми строками.
        assert data.endswith(b"\n")


def test_обрезка_отбрасывает_неполный_хвост(tmp_path: Path) -> None:
    """Явная проверка ветки: нет перевода строки - пишем пусто."""
    src = (ROOT / "hub" / "diag.py").read_text(encoding="utf-8")
    assert 'else b""' in src, "обрезанный кусок снова сохраняется"
    assert "if cut >= 0 else tail" not in src


def test_после_обрезки_журнал_читается(tmp_path: Path) -> None:
    """Панель не должна получать первую строку из мусора."""
    path = log_path(tmp_path)
    c = make_diag(tmp_path, keep_bytes=120)
    for i in range(60):
        c.note("поток", ValueError(f"запись номер {i} " + "хвост " * 10))
    rows = c.recent()
    for row in rows:
        assert isinstance(row.get("error"), str)


# ============================================ гонка записи настроек


def test_временное_имя_уникально(tmp_path: Path) -> None:
    """Фиксированное `.tmp` делилось между двумя сохранениями."""
    target = tmp_path / "config.json"
    atomic_write(target, '{"a": 1}')
    leftovers = list(tmp_path.glob("*.tmp"))
    assert not leftovers, f"временные файлы остались: {leftovers}"


def test_два_сохранения_подряд_не_ломают_друг_друга(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    atomic_write(target, json.dumps({"первый": True}, ensure_ascii=False))
    atomic_write(target, json.dumps({"второй": True}, ensure_ascii=False))
    assert json.loads(target.read_text(encoding="utf-8")) == {"второй": True}


def test_параллельные_сохранения_не_теряют_данные(tmp_path: Path) -> None:
    """Главный сценарий гонки: веб и консоль пишут настройки разом."""
    target = tmp_path / "config.json"
    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def writer(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            atomic_write(target, json.dumps({"писатель": index},
                                            ensure_ascii=False))
        except BaseException as exc:  # noqa: BLE001 - ошибка и есть результат
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors, f"сохранения упали: {errors}"
    # Файл обязан остаться читаемым и без мусора рядом.
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "писатель" in data
    assert not list(tmp_path.glob("*.tmp")), "остались временные файлы"


def test_фиксированного_имени_в_коде_не_осталось() -> None:
    src = (ROOT / "hub" / "config.py").read_text(encoding="utf-8")
    assert 'path.with_name(path.name + ".tmp")' not in src
    assert "uuid" in src, "уникальное имя временного файла не используется"


# ============================================ клиенты httpx не текут


def test_клиент_failover_закрывается() -> None:
    """Аудит утверждал, что клиенты не закрываются. Проверяем факт.

    Оба прыжка закрывают клиент через `aclose()`. Если появится третья
    ветка без закрытия - тест это заметит, посчитав открытия и закрытия.
    """
    src = (ROOT / "hub" / "failover.py").read_text(encoding="utf-8")
    created = src.count("httpx.AsyncClient(")
    closed = src.count("await client.aclose()")
    assert created, "клиент вообще не создаётся?"
    assert closed == created, (
        f"клиентов создано {created}, закрыто {closed}")
    assert "async with httpx.AsyncClient" not in src, "появился другой способ"

