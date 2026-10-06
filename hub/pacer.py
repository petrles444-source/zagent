"""Ограничитель темпа запросов — чтобы рой не выглядел атакой и не получил бан.

Зачем это отдельный модуль. Рой агентов по определению шлёт много запросов
одновременно, и именно это выглядит для провайдера как злоупотребление.
Ограничение нельзя оставить «на совести провайдера»: один вредный аккаунт
испортит репутацию не только себе.

Четыре правила, и все четыре нужны одновременно.

**Каждому аккаунту — свой счётчик.** Предел считается на аккаунт, а не на
задачу. Восемь частей на восьми NVIDIA-ключах держатся по 40 запросов в
минуту каждый — это восемь аккаунтов, а не 320 запросов с одного адреса.
Но если две части встанут на один аккаунт, они удвоят его темп, и вот
здесь уже начинается настоящая проблема.

**Ведро на скользящей минуте.** Провайдер не «обнуляет счётчик в начале
минуты» — запрос, ушедший 59 секунд назад, освобождает место только что.
Ведро со сбросом по таймеру выпускало бы всю минуту разом и упиралось в
потолок ровно в тот момент, когда всё одновременно пошло в сеть.

**Падение при переполнении.** Лучше подождать, чем превысить лимит: отказ по
лимиту у провайдера — это уже история в его журналах, а ожидание — нет.

**Глобальная пауза между запусками.** Части стартуют не одновременно, а с
разбросом. Восемь одинаковых запросов в одну миллисекунду — это ровно то,
что система защиты видит первым.

Значение по умолчанию для шлюзов с неизвестным лимитом — намеренно
небольшое: неизвестность не повод лить запросы.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

#: Запросов в минуту на аккаунт, когда провайдер не сообщает лимит и его нет в
#: конфиге. Мало: лучше задача идёт медленнее, чем аккаунт помечен злоупотреблением.
DEFAULT_RPM = 20

#: Разброс при старте частей, в секундах. Небольшой, но достаточный, чтобы
#: запросы разошлись по времени, а не ударили одной пачкой.
LAUNCH_STAGGER_S = 0.7

#: Сколько запросов аккаунт может отдать подряд, не ожидая.
#:
#: Мало, и это главное. Полное ведро на старте (равное лимиту) означало бы
#: пачку из сорока запросов в одну секунду — ровно то, что система защиты
#: видит первым и что выглядит как злоупотребление. Дальше темп держится по
#: лимиту, а первые запросы — короткий разбег.
BURST = 4


def default_interval(rpm: int) -> float:
    return 60.0 / max(1, rpm)


@dataclass
class Bucket:
    """Ведро запросов одного аккаунта на скользящей минуте."""

    rate_per_min: int
    #: Токенов в ведре. Равно лимиту, а не единице: минута может съесть
    #: целиком, и ждать каждый запрос по отдельности было бы медленнее
    #: провайдера без всякой пользы.
    tokens: float = field(init=False)
    #: Токенов в ведре на старте. Короткий разбег вместо полного ведра: пачка
    #: из сорока запросов в секунду — это то, что система защиты видит
    #: первым, а лимит при этом даже не превышен.
    burst: int = BURST
    last: float = field(init=False)
    #: Всего запросов через это ведро — для показа в интерфейсе.
    passed: int = field(default=0)

    def __post_init__(self) -> None:
        self.rate_per_min = max(1, int(self.rate_per_min))
        self.tokens = float(min(self.rate_per_min, max(1, self.burst)))
        self.last = time.monotonic()

    def _refill(self, now: float) -> None:
        """Наполнить ведо до текущего момента. Ведро не выше лимита."""
        if now <= self.last:
            return
        elapsed_min = (now - self.last) / 60.0
        self.tokens = min(float(self.rate_per_min),
                          self.tokens + elapsed_min * self.rate_per_min)
        self.last = now

    def take_now(self) -> bool:
        """Взять токен, если он есть. False — надо подождать."""
        self._refill(time.monotonic())
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            self.passed += 1
            return True
        return False

    def wait_seconds(self) -> float:
        """Сколько ждать до ближайшего токена."""
        self._refill(time.monotonic())
        if self.tokens >= 1.0:
            return 0.0
        missing = 1.0 - self.tokens
        return missing / self.rate_per_min * 60.0

    def left(self) -> int:
        self._refill(time.monotonic())
        return int(self.tokens)


class Pacer:
    """Темп запросов по всем аккаунтам сразу.

    Один объект на задачу. Общий, а не на часть: иначе две части, случайно
    попавшие на один аккаунт, обошли бы ограничение, считая каждый свой.
    """

    def __init__(self, *, default_rpm: int = DEFAULT_RPM,
                 max_parallel: int = 8) -> None:
        self.default_rpm = default_rpm
        self.max_parallel = max(1, int(max_parallel))
        self._buckets: dict[str, Bucket] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    def bucket(self, account: str, rpm: int | None = None) -> Bucket:
        """Ведро аккаунта. Создаётся при первом обращении."""
        got = self._buckets.get(account)
        if got is None:
            got = Bucket(rpm if rpm else self.default_rpm)
            self._buckets[account] = got
        elif rpm and rpm != got.rate_per_min:
            # Лимит мог прийти из конфига позже, чем первое обращение.
            got.rate_per_min = max(1, int(rpm))
            got.tokens = min(got.tokens, float(got.rate_per_min))
        return got

    def set_rpm(self, account: str, rpm: int) -> None:
        """Задать лимит аккаунту, когда он известен из конфига."""
        if rpm:
            self.bucket(account, int(rpm))

    async def acquire(self, account: str, rpm: int | None = None) -> None:
        """Дождаться своей очереди на аккаунт и занять один запрос.

        Вызывается перед каждым запросом к модели, а не один раз на часть:
        темп ограничивается на всём ходе, а не на старте.
        """
        got = self.bucket(account, rpm)
        lock = self._locks.setdefault(account, asyncio.Lock())
        async with lock:
            while True:
                if got.take_now():
                    return
                delay = got.wait_seconds()
                # Пауза с потолком: иначе при очень малой скорости ожидание
                # растягивается на минуты и не реагирует на изменения.
                await asyncio.sleep(min(max(delay, 0.01), 5.0))

    def left(self, account: str) -> int:
        return self.bucket(account).left()

    def report(self) -> dict[str, int]:
        """Сколько запросов прошло через каждый аккаунт."""
        return {name: b.passed for name, b in self._buckets.items()}


class PacedCaller:
    """Вызывающий, который спрашивает разрешения у ограничителя темпа.

    Оборачивает `AutoCaller` и ничего о нём не знает. Важно, что ожидание
    происходит на каждом запросе, а не один раз: иначе ограничитель
    превратился бы в задержку на старте и перестал бы ограничивать что-либо.
    """

    def __init__(self, inner: object, pacer: Pacer, account: str,
                 rpm: int | None = None) -> None:
        self.inner = inner
        self.pacer = pacer
        self.account = account
        self.rpm = rpm

    @property
    def pinned(self) -> str | None:
        return getattr(self.inner, "pinned", None)

    @pinned.setter
    def pinned(self, value: str | None) -> None:
        setattr(self.inner, "pinned", value)

    async def ask(self, messages, **kw):  # noqa: ANN001, ANN003
        await self.pacer.acquire(self.account, self.rpm)
        return await self.inner.ask(messages, **kw)