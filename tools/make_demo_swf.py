#!/usr/bin/env python3
r"""Сгенерировать демонстрационные .swf для портала.

Зачем
-----
Сайт показывает, что умеет воспроизводить Flash. Но показать нечем:
ни одного .swf в проекте нет, а флеш-плеер без файла показывает пустоту.
Поэтому файлы делаются здесь — честные, настоящие, из пары десятков
байт: Ruffle их грузит и играет как обычные.

Как устроен файл
----------------
SWF без сжатия: сигнатура `FWS`, версия, длина, размер сцены, частота
кадров, а дальше теги. На каждый кадр идёт `PlaceObject2`, который
двигает фигуру, и `ShowFrame`. Фигура описана один раз через
`DefineShape`: заливка сплошным цветом и четыре прямолинейных ребра.

Всё это пишется бит за битом, поэтому битовый писатель — с отсчётом
ширины: координаты в SWF упакованы с точностью до бита, и лишний бит
в конце тега делает файл нечитаемым для плеера, а ошибку показывает
только консоль браузера.

Запуск
------
    .venv\Scripts\python.exe tools\make_demo_swf.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

#: Куда класть. Рядом с сайтом: демо едет на сервер вместе с ним.
OUT = Path(__file__).resolve().parent.parent / "site" / "swf"

#: Сцена в твипах (1/20 пикселя). 550x400 — нормальное окно плеера.
STAGE_W, STAGE_H = 550, 400
TWIPS = 20

#: Кадров в секунду. 24 — как в самом флеше по умолчанию.
FPS = 24


class BitWriter:
    """Пишет биты в поток. Старший бит идёт первым — так устроен SWF."""

    def __init__(self) -> None:
        self._bits: list[int] = []

    def write(self, value: int, width: int) -> None:
        """Записать `width` бит числа value (старшие биты — первыми)."""
        if width <= 0:
            return
        for shift in range(width - 1, -1, -1):
            self._bits.append((value >> shift) & 1)

    def write_signed(self, value: int, width: int) -> None:
        """Записать число со знаком. Знаковые биты SWF — это зигзаг."""
        self.write(value & ((1 << width) - 1), width)

    @property
    def bit_length(self) -> int:
        return len(self._bits)

    def align(self) -> None:
        """Дописать нули до границы байта.

        После RECT данные идут с выравниванием по байту: `FrameRate`
        в заголовке и `FillStyleArray` в DefineShape — это поля по целому
        байту, и читатель начинает их с ближайшей границы. Без этого
        сдвига на неполном байте Ruffle читает частоту кадров не с того
        места, дальше теги едут с неверным смещением — и файл
        разваливается целиком, хотя выглядит почти правильным.
        """
        while len(self._bits) % 8:
            self._bits.append(0)

    def u16(self, value: int) -> None:
        """Записать 16-битное поле в порядке little-endian.

        Отдельный метод не для красоты: `write()` кладёт биты от старшего
        к младшему, то есть даёт big-endian. У SWF же многобайтовые числа
        хранятся little-endian, а биты внутри байта — наоборот, от
        старшего. Поэтому `ShapeID = 1` записывался как 00 01, а читался
        как 0x0100 = 256, и Ruffle искал персонажа номер 256 вместо
        первого. Порядок байт и порядок бит внутри байта противоположны.
        """
        if self.bit_length % 8:
            raise ValueError("u16 пишется только на границе байта")
        self.write(value & 0xFF, 8)              # младший байт первым
        self.write((value >> 8) & 0xFF, 8)

    def to_bytes(self) -> bytes:
        """Дописать нулями до байта и отдать байты."""
        while len(self._bits) % 8:
            self._bits.append(0)
        out = bytearray()
        for i in range(0, len(self._bits), 8):
            byte = 0
            for j in range(8):
                byte = (byte << 1) | self._bits[i + j]
            out.append(byte)
        return bytes(out)


def rect(writer: BitWriter, x0: int, x1: int, y0: int, y1: int) -> None:
    """Записать RECT — прямоугольник в битовой упаковке с зигзагом.

    Ширина поля выбирается по максимальному значению: пять бит на старте
    означают, сколько бит займёт каждое из четырёх чисел. Меньше нельзя
    (тогда значение не влезет), больше — файл раздувается.
    """
    values = [x0, x1, y0, y1]
    nbits = 1
    while max(abs(v) for v in values) >= (1 << (nbits - 1)):
        nbits += 1
    writer.write(nbits, 5)
    for value in values:
        # Зигзаг: положительные идут с чётным битом, отрицательные —
        # с нечётным. Так одна и та же ширина покрывает оба знака.
        zigzag = (value << 1) if value >= 0 else ((-value << 1) - 1)
        writer.write(zigzag, nbits)


def tag(code: int, body: bytes) -> bytes:
    """Обернуть тело в заголовок тега: код и длина в двух байтах."""
    if len(body) > 0x3F:
        raise ValueError(f"тег {code} длиннее 63 байт — нужен длинный формат")
    return struct.pack("<H", (code << 6) | len(body)) + body


def set_background(rgb: tuple[int, int, int]) -> bytes:
    """Тег 9: цвет подложки сцены."""
    return tag(9, bytes(rgb))


def define_shape(shape_id: int, width: int, height: int,
                 rgb: tuple[int, int, int]) -> bytes:
    """Тег 2: прямоугольник с заливкой сплошным цветом.

    Контур — четыре прямолинейных ребра, замыкающихся в начало. Заливка
    ненулевая, поэтому область внутри контура заливается целиком.
    """
    writer = BitWriter()
    writer.u16(shape_id)                        # ShapeID
    rect(writer, 0, width, 0, height)           # ShapeBounds
    writer.align()                              # дальше всё по целым байтам

    # FillStyleArray: одна сплошная заливка. Тип 0x00 — solid, следом RGB.
    writer.write(1, 8)
    writer.write(0x00, 8)
    for channel in rgb:
        writer.write(channel, 8)
    writer.write(0, 8)                          # LineStyleArray: без обводки
    writer.write(1, 8)                          # NumFillBits
    writer.write(0, 8)                          # NumLineBits

    # Первая запись контура: сдвиг в начало фигуры.
    #
    # Заголовок записи — НЕ байт. Для записи без ребра это 6 флагов,
    # 6 зарезервированных бит, EdgeFlags и ещё 4 бита числа: итого 13
    # бит, и дальше данные начинаются с середины байта. Первая версия
    # писала 8 бит и 4 бита «NumBits», из-за чего Ruffle не смог
    # прочитать фигуру и не зарегистрировал персонажа.
    writer.write(0b100001, 6)                   # FirstFlag=1 … MoveTo=1
    writer.write(0, 6)                          # reserved
    writer.write(0, 1)                          # EdgeFlags = 0 → не ребро
    writer.write(0, 4)                          # NumBits (для не-ребра не нужен)
    # У MoveTo ширина задаётся сразу на ОБЕ координаты, каждой — половина.
    # 15 бит на координату хватает сцены 11000×8000 твипов.
    writer.write(30, 5)                         # NMoveBits
    writer.write(0, 15)                         # MoveX
    writer.write(0, 15)                         # MoveY

    # Четыре ребра. У записи-ребра только три флага (FirstFlag,
    # ShapeType, FillStyle1), а не шесть: остальные относятся к
    # StyleChangeRecord и здесь просто не читаются.
    points = [(width, 0), (width, height), (0, height), (0, 0)]
    prev = (0, 0)
    for target in points:
        dx, dy = target[0] - prev[0], target[1] - prev[1]
        nbits = 2
        while max(abs(dx), abs(dy)) >= (1 << (nbits - 1)):
            nbits += 1
        writer.write(0, 3)                      # FirstFlag=ShapeType=FillStyle1=0
        writer.write(0, 6)                      # reserved
        writer.write(1, 1)                      # EdgeFlags = 1 → ребро
        writer.write(1, 1)                      # StraightFlag = 1
        writer.write(0, 2)                      # NumBits = 0 → общий случай
        writer.write(1, 1)                      # GeneralLineFlag = 1
        writer.write(nbits, 4)                  # сколько бит на дельту
        writer.write_signed(dx, nbits)
        writer.write_signed(dy, nbits)
        prev = target

    writer.write(0, 13)                         # EndShapeRecord
    return tag(2, writer.to_bytes())


def place(depth: int, shape_id: int, x: int, y: int,
          scale: int = 1024, rotate_twips: int = 0) -> bytes:
    """Тег 26: поставить фигуру в кадр — сдвиг, масштаб, поворот.

    Матрица MATRIX — тоже битовая: сначала «есть ли масштаб», потом
    «есть ли поворот», затем ширина переноса и сам перенос. Пропуск
    любого из этих битов сдвигает всю структуру, и файл не грузится.
    """
    writer = BitWriter()
    # Байт флагов: HasMatrix=1 (бит 2), HasCharacter=1 (бит 1), Move=1 (бит 0).
    writer.write(0b00000110, 8)
    writer.u16(depth)
    writer.u16(shape_id)

    writer.write(1, 1)                          # HasScale
    nscale = 1
    while scale >= (1 << (nscale + 10)):
        nscale += 1
    writer.write(nscale, 5)
    writer.write(scale, nscale)                 # ScaleX
    writer.write(scale, nscale)                 # ScaleY

    writer.write(1, 1)                          # HasRotate
    nrotate = 1
    while abs(rotate_twips) >= (1 << (nrotate - 1)):
        nrotate += 1
    writer.write(nrotate, 5)
    writer.write(rotate_twips, nrotate)         # RotateX
    writer.write(rotate_twips, nrotate)         # RotateY

    ntranslate = 1
    while max(abs(x), abs(y)) >= (1 << (ntranslate - 1)):
        ntranslate += 1
    writer.write(ntranslate, 5)
    writer.write_signed(x, ntranslate)
    writer.write_signed(y, ntranslate)
    return tag(26, writer.to_bytes())


def show_frame() -> bytes:
    """Тег 1: конец кадра — что накоплено, показывается."""
    return tag(1, b"")


def end() -> bytes:
    """Тег 0: конец фильма."""
    return tag(0, b"")


def build_swf(shapes: list[tuple[int, int, int, int]],
              frames: list[bytes], background: tuple[int, int, int],
              width: int = STAGE_W * TWIPS,
              height: int = STAGE_H * TWIPS) -> bytes:
    """Собрать файл: заголовок, теги фигур, кадры, конец.

    Длина в заголовке указывается на весь файл, включая сам заголовок, и
    файл дополняется до чётной длины — иначе плеер читает за границей.
    """
    body = bytearray()
    body += set_background(background)
    for shape_id, shape_w, shape_h, color in shapes:
        body += define_shape(shape_id, shape_w, shape_h, color)
    for frame in frames:
        body += frame
    body += end()

    head = BitWriter()
    rect(head, 0, width, 0, height)
    head.align()                                # поля дальше читаются по байтам
    # FrameRate хранится как 8.8 fixed point: целая часть в старшем байте,
    # поэтому 24 кадра — это 24 << 8 = 6144, а не 24. Запишем 24, и
    # читатель поделит на 256.
    head.u16(FPS << 8)
    head.u16(len(frames))
    prefix = head.to_bytes()

    header = b"FWS" + bytes([6])
    # Длина в заголовке — на весь файл, включая сам заголовок. Считаем
    # от настоящих байт и сверяем: расхождение на байт означает, что файл
    # либо обрезан на последнем теге, либо читатель уйдёт за конец.
    total = len(header) + 4 + len(prefix) + len(body)
    if total % 2:
        body += b"\x00"
        total += 1
    data = header + struct.pack("<I", total) + prefix + bytes(body)
    if len(data) != total:
        raise ValueError(
            f"длина в заголовке {total}, а файл {len(data)} байт")
    return data


def demo_pulse() -> bytes:
    """Пульсирующий квадрат: масштаб ходит по синусоиде."""
    shape_w = shape_h = 160 * TWIPS
    frames = []
    for step in range(48):
        # Синусоида через целочисленный угол: в файле нужны целые
        # числа, а float в него писать некуда.
        import math
        phase = step / 48 * 2 * math.pi
        scale = 512 + int(512 * (0.5 + 0.5 * math.sin(phase)))
        x = (STAGE_W * TWIPS) // 2 - (shape_w * scale) // 2048
        y = (STAGE_H * TWIPS) // 2 - (shape_h * scale) // 2048
        frames.append(place(1, 1, x, y, scale=scale) + show_frame())
    return build_swf([(1, shape_w, shape_h, (0x00, 0xF0, 0xFF))],
                     frames, (0x05, 0x05, 0x05))


def demo_orbit() -> bytes:
    """Три квадрата по кругу: разные цвета, разный радиус."""
    size = 60 * TWIPS
    palette = [(0xFC, 0xE3, 0x00), (0xFF, 0x00, 0x3C), (0x00, 0xF0, 0xFF)]
    frames = []
    for step in range(36):
        for index, color in enumerate(palette):
            import math
            angle = (step / 36) * 2 * math.pi + index * 2 * math.pi / 3
            radius = 120 * TWIPS
            x = int((STAGE_W * TWIPS) / 2 + radius * math.cos(angle)) - size // 2
            y = int((STAGE_H * TWIPS) / 2 + radius * math.sin(angle)) - size // 2
            frames.append(place(index + 1, index + 1, x, y) + show_frame())
    return build_swf(
        [(i + 1, size, size, color) for i, color in enumerate(palette)],
        frames, (0x05, 0x05, 0x05))


def demo_bars() -> bytes:
    """Столбики разной высоты — проверка, что кадры обновляются."""
    count = 8
    bar_w = 40 * TWIPS
    gap = 8 * TWIPS
    total_w = count * bar_w + (count - 1) * gap
    frames = []
    for step in range(30):
        import math
        for index in range(count):
            height = int((60 + 120 * (0.5 + 0.5 * math.sin(
                (step / 30) * 2 * math.pi + index * 0.7))) * TWIPS)
            x = ((STAGE_W * TWIPS) - total_w) // 2 + index * (bar_w + gap)
            y = (STAGE_H * TWIPS) - 60 * TWIPS - height
            frames.append(place(index + 1, index + 1, x, y) + show_frame())
    return build_swf(
        [(i + 1, bar_w, 300 * TWIPS, (0x00, 0xF0, 0xFF)) for i in range(count)],
        frames, (0x05, 0x05, 0x05))


DEMOS = {
    "pulse": demo_pulse,
    "orbit": demo_orbit,
    "bars": demo_bars,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, builder in DEMOS.items():
        data = builder()
        path = OUT / f"{name}.swf"
        path.write_bytes(data)
        print(f"  {path.name}: {len(data)} байт, {data[:3].decode('ascii')} v{data[3]}")
    print(f"готово: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
