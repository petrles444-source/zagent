"""Сборщик ошибок: всё, что проглочено, но должно быть видно.

Зачем этот файл. В проекте примерно двадцать мест, где ошибку ловят и
молча кладут в сторону: `except Exception: pass` в `Worker.emit`,
в записи чекпоинта, в раздаче событий подписчикам, в очереди SSE. Это
правильное поведение для работы программы — ошибка не должна ронять шаг
агента, — но неправильное для человека: он видит «программа ничего не
делает» и не имеет ни одного способа понять, где именно затык.

Программа, которая годами молча глотает ошибки, в какой-то момент
возвращает их одним куском: «ничего не работает». Сборщик нужен, чтобы
этот кусок был не «ничего не работает», а список из двадцати строк с
именами мест.

Что это НЕ полноценное логирование
---------------------------------
Здесь нет уровней (`info`/`warning`/`debug`), нет фильтров, нет ротации
по дням и нет отправки куда-либо. Есть ровно одна обязанность: записать
факт «здесь что-то упало» так, чтобы это можно было потом прочитать —
через панель в режиме разработчика или файлом. Полноценный `logging` с
ротацией остаётся отдельной задачей (пункт плана update/update-07-10-26.txt);
миграция туда всех `print` — большой рефакторинг, и начинать его с нуля,
когда уже есть работающий кольцевой журнал, незачем.

Два правила, которые здесь не обсуждаются
-----------------------------------------
1. **Ключи сюда не попадают.** Текст ошибки проходит через
   `blackbox.redact` — тем же способом, что и выгрузка чёрного ящика.
   Причина простая: в текст исключения попадает URL шлюза, а у части
   шлюзов секрет живёт прямо в адресе. Ошибка, которая пишет ключ в файл
   на диск, — это не диагностика, а новая утечка.
2. **Сборщик не имеет права уронить программу.** Любая ошибка внутри —
   проглатывается. Иначе диагностика могла бы стать причиной сбоя,
   которого она не расследует.

Формат: одна строка JSON на ошибку, файл `web-state/diag.jsonl` рядом с
базой. Строки вместо объектов — потому что журнал кольцевой: при
переполнении мы отрезаем начало, и построчный формат позволяет сделать
это не читая всего файла.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from hub.blackbox import redact

#: Имя файла журнала. Живёт рядом с базой (`web-state/`), а не в корне:
#: там уже лежат рабочие данные, и папка целиком в `.gitignore`.
DIAG_NAME = "diag.jsonl"

#: Сколько примерно байт держим. 512 КБ — это около двух тысяч записей,
#: то есть несколько дней плотной работы, а для локального инструмента
#: места хватает с запасом. Кольцо нужно для одного: журнал, который
#: растёт вечно, однажды перестаёт открываться.
KEEP_BYTES = 512 * 1024

#: Сколько записей отдавать в панель. Больше не полезно: панель и так
#: перестаёт читаться, а журнал целиком качается файлом.
RECENT_LIMIT = 40


def _safe_text(value: Any, root: Any = None, limit: int = 600) -> str:
    """Текст ошибки, безопасный для записи.

    Порядок именно такой: сначала срез по длине (чтобы не тащить в
    память мегабайт трейсбека), потом вымарывание ключей, потом схлопывание
    пробелов — иначе в JSON попал бы многострочный хвост, который портит
    журнал тем, что из него потом нельзя считать построчно.
    """
    text = str(value)
    if len(text) > limit:
        text = text[:limit] + f"… (+{len(str(value)) - limit} симв.)"
    return " ".join(redact(text, root).split())


class Diag:
    """Кольцевой журнал ошибок в файле.

    Один экземпляр на процесс (см. `DIAG` внизу модуля). Всё, что пишется,
    идёт под замком: вызывать могут поток воркера, поток HTTP-обработчика
    и event loop, а частичная запись строки сделала бы JSONL нечитаемым.
    """

    def __init__(self, root: Any = None, *, keep_bytes: int = KEEP_BYTES) -> None:
        self.root = Path(root) if root else None
        self.keep_bytes = int(keep_bytes)
        self._lock = threading.Lock()
        #: Сколько записей всего за текущий запуск — показывается в панели,
        #: чтобы человек узнал о проблеме, даже не открывая файл.
        self.count = 0
        #: Сколько записей потеряно, потому что сам сборщик не смог записать.
        #: Само это число — уже диагностика: молчащий сборщик хуже его
        #: отсутствия, потому что создаёт ложное впечатление «всё тихо».
        self.lost = 0

    # ------------------------------------------------------------- путь

    @property
    def path(self) -> Path | None:
        """Файл журнала. `None`, пока не указан корень установки."""
        if self.root is None:
            return None
        return Path(self.root) / "web-state" / DIAG_NAME

    # ------------------------------------------------------------ запись

    def note(self, scope: str, exc: BaseException | None = None, **fields: Any) -> None:
        """Записать одну ошибку. Никогда не бросает ничего.

        `scope` — имя места («emit», «checkpoint», «sse»): по нему человек
        ищет потом в коде, поэтому он короткий и неизменный, а не
        «какая-то ошибка».
        """
        path = self.path
        if path is None:
            self.lost += 1
            return
        record: dict[str, Any] = {
            "at": round(time.time(), 3),
            "scope": str(scope),
        }
        if exc is not None:
            record["type"] = type(exc).__name__
            record["error"] = _safe_text(exc, self.root)
            # Трейс — только по запросу. Он большой, а нужен он в одном
            # случае из ста: когда «здесь упало» мало о чём говорит.
            if fields.pop("trace", False):
                record["trace"] = _safe_text(
                    "".join(traceback.format_exception(
                        type(exc), exc, exc.__traceback__)),
                    self.root, limit=4000,
                )
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                record[key] = value if value is None else (
                    _safe_text(value, self.root)
                    if isinstance(value, str) else value
                )
            else:
                record[key] = _safe_text(value, self.root, limit=300)

        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Открываем в бинарном режиме намеренно. Раньше файл был
                # текстовым с encoding="utf-8", а проверка последнего
                # символа делалась так: seek(tell() - 1), read(1).
                # Для текстового файла tell() - это НЕ смещение в байтах,
                # а непрозрачный cookie позиционирования: он кодирует
                # стартовую позицию и состояние декодера. Вычитать из него
                # единицу и читать «последний символ» бессмысленно, а
                # чтение с середины многобайтового кириллического символа
                # может дать UnicodeDecodeError - и ровно в тот момент,
                # когда журнал ошибок нужнее всего.
                #
                # Байты здесь честные: файл сам по себе UTF-8, а последний
                # байт перевода строки (0x0A) в кириллице не встречается.
                with path.open("ab+") as handle:
                    if handle.seek(0, os.SEEK_END):
                        handle.seek(-1, os.SEEK_END)
                        if handle.read(1) != b"\n":
                            handle.write(b"\n")
                    handle.write((line + "\n").encode("utf-8"))
                self.count += 1
                self._rotate(path)
            except OSError:
                # Диск кончился, папка защищена от записи, файл занят
                # антивирусом — причины разные, а поступление одинаковое:
                # ошибку мы не записали. Считаем и продолжаем работать.
                self.lost += 1
                # Помечаем потерю в общем файле: знание о том, что запись
                # не дошла, не должно умирать вместе с процессом.
                self._add_lost(1)

    def _rotate(self, path: Path) -> None:
        """Обрезать начало, когда файл переполнен.

        Режем до половины от лимита: однострочная обрезка оставляла бы файл
        на пределе и заставляла бы переписывать его на каждой следующей
        ошибке. Половина — это компромисс между «резать часто» и «резать
        редко»; на объёме в сотни ошибок разница незаметна.
        """
        try:
            if path.stat().st_size <= self.keep_bytes:
                return
        except OSError:
            return

        limit = max(self.keep_bytes // 2, 1024)
        try:
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - limit))
                tail = handle.read()
        except OSError:
            return
        # Первая строка после обрезки может оказаться половиной JSON —
        # её выкидываем, иначе панель будет читать мусор.
        cut = tail.find(b"\n")
        # Если перевода строки нет, срез начат посреди записи (частая
        # история: стек-трейс на десятки килобайт занимал всю строку
        # JSON). Такой кусок не восстановим - раньше он возвращался в
        # файл, и журнал оставался испорченным навсегда.
        tail = tail[cut + 1:] if cut >= 0 else b""
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(tail)
            os.replace(tmp, path)
        except OSError:
            pass

    # ------------------------------------------------------------- чтение

    def recent(self, limit: int = RECENT_LIMIT) -> list[dict[str, Any]]:
        """Последние записи, новые первыми.

        Читаем файл целиком: он кольцевой и ограничен по размеру, а читать
        «последние N» с конца без чтения всего — сложнее, чем нужно для
        локального инструмента.
        """
        path = self.path
        if path is None or not path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Одна битая строка не должна прятать остальные:
                        # журнал мог оборваться на середине записи.
                        out.append({"scope": "?", "error": "битая строка журнала"})
        except OSError:
            return []
        return list(reversed(out[-int(limit):]))

    def clear(self) -> None:
        """Очистить журнал. Счётчики остаются: они про текущий запуск."""
        path = self.path
        if path is None:
            return
        with self._lock:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

    def _meta_path(self) -> Path | None:
        """Служебный файл рядом с журналом: там живёт общее число потерянных.

        Отдельный файл нужен потому, что в сам журнал записать нельзя: если
        он недоступен (диск, антивирус), то и счётчик потерь туда не
        положить. А терять его нельзя - именно в этом случае он и нужен.
        """
        path = self.path
        return path.with_suffix(".lost") if path is not None else None

    def _count_lines(self) -> int:
        """Сколько записей в журнале на самом деле.

        Читается файл, а не память процесса: журналом пользуются два
        процесса (сайт и донорский шлюз), и показывать им разные числа
        об одном файле нельзя.
        """
        path = self.path
        if path is None or not path.exists():
            return 0
        try:
            with path.open("rb") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    def _lost_total(self) -> int:
        """Сумма потерь по всем процессам, а не только по текущему."""
        meta = self._meta_path()
        if meta is None or not meta.exists():
            return self.lost
        try:
            return max(int(meta.read_text(encoding="utf-8").strip() or "0"),
                       self.lost)
        except (OSError, ValueError):
            return self.lost

    def _add_lost(self, how_many: int) -> None:
        """Отметить потерю так, чтобы её увидели все процессы."""
        meta = self._meta_path()
        if meta is None:
            return
        try:
            current = 0
            if meta.exists():
                current = int(meta.read_text(encoding="utf-8").strip() or "0")
            meta.write_text(str(current + how_many), encoding="utf-8")
        except (OSError, ValueError):
            # Нечем записать счётчик потерь - молча, потеря и так уже есть.
            pass

    def stats(self) -> dict[str, Any]:
        """Сводка для панели: где лежит журнал, сколько записей."""
        path = self.path
        size = 0
        if path is not None and path.exists():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
        return {
            "path": str(path) if path else "",
            # Числа - из файлов, а не из памяти процесса: панель сайта и
            # панель шлюза читают один журнал и обязаны показывать одно
            # и то же. Раньше сайт писал count=0, шлюз count=34 по одному
            # и тому же файлу.
            "count": self._count_lines(),
            "lost": self._lost_total(),
            "count_in_process": self.count,
            "lost_in_process": self.lost,
            "size": size,
            "keep_bytes": self.keep_bytes,
        }


#: Экземпляр на процесс. Настраивается один раз при старте воркера —
#: до этого момента `note()` честно считает записи потерянными, а не
#: молчит: неправильный путь журнала сам по себе должен быть виден.
DIAG = Diag()


def configure(root: Any) -> None:
    """Указать сборщику, где лежит установка."""
    DIAG.root = Path(root)


def note(scope: str, exc: BaseException | None = None, **fields: Any) -> None:
    """Короткая запись в журнал ошибок. Подробности — в `Diag.note`."""
    DIAG.note(scope, exc, **fields)