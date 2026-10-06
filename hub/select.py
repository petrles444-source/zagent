"""Выбор модели для агента: режимы auto / manual / chain.

Ключевая идея режима auto: у каждой модели есть состояние (здорова / лимит /
заблокирована / медленная). При падении модель уходит в карантин, и агент берёт
следующую по приоритету, не тратя время на повтор той же.

Типы отказов (из registry.probe_models):
    ok / slow        модель работает
    empty            ответ без текста (reasoning съел max_tokens)
    limited          HTTP 429 — карантин до cooldown_seconds
    blocked          403 провайдера — карантин навсегда (до перепроверки)
    down             сеть/5xx/таймаут — короткий карантин
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from hub.registry import Registry
from hub.tiers import TierBook, rank_models


class Mode(str, Enum):
    AUTO = "auto"        # лучшая доступная, переключение при отказе
    MANUAL = "manual"    # строго выбранная пользователем
    CHAIN = "chain"      # заданный пользователем порядок


@dataclass
class ModelState:
    """Живое состояние одной модели в рантайме агента."""

    ref: str
    gateway: str
    model: str
    tier: int = 5
    last_status: str = "unknown"
    last_error: str | None = None
    last_used: float = 0.0
    cooldown_until: float = 0.0
    fails: int = 0
    ok_count: int = 0
    avg_ms: float = 0.0

    @property
    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    @property
    def cooldown_left(self) -> int:
        return max(0, int(self.cooldown_until - time.time()))

    @property
    def blocked(self) -> bool:
        return self.last_status == "blocked"

    def usable(self, now: float | None = None) -> bool:
        """Можно ли сейчас попробовать эту модель."""
        current = now if now is not None else time.time()
        if self.last_status == "blocked":
            return current >= self.cooldown_until
        return current >= self.cooldown_until

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "gateway": self.gateway,
            "model": self.model,
            "tier": self.tier,
            "status": self.last_status,
            "error": self.last_error,
            "in_cooldown": self.in_cooldown,
            "cooldown_left": self.cooldown_left,
            "fails": self.fails,
            "ok_count": self.ok_count,
            "avg_ms": int(self.avg_ms),
        }


#: Карантин по типу отказа, секунды.
COOLDOWN = {
    "limited": 300.0,      # 429: 5 минут
    "blocked": 3600.0,     # 403 провайдера: час, потом перепроверка
    "down": 90.0,          # сеть/5xx
    "empty": 30.0,         # пустой ответ, попробовать позже
    "slow": 0.0,
    "ok": 0.0,
}

#: Потолок отката при повторных отказах.
MAX_COOLDOWN_S = 3600.0


class Selector:
    """Держит состояние всех моделей и выбирает следующую для вызова."""

    def __init__(
        self,
        registry: Registry,
        tierbook: TierBook,
        *,
        mode: Mode = Mode.AUTO,
        manual_ref: str | None = None,
        chain: list[str] | None = None,
        prefer_speed: bool = False,
        require_vision: bool = False,
        avoid_vpn: bool = False,
        vpn_only: set[str] | None = None,
    ) -> None:
        self.registry = registry
        self.tierbook = tierbook
        self.mode = mode
        self.manual_ref = manual_ref
        self.chain = list(chain or [])
        self.prefer_speed = prefer_speed
        self.require_vision = require_vision
        #: Понижать приоритет моделям, которым нужен VPN.
        self.avoid_vpn = avoid_vpn
        #: Множество ref'ов, доступных только через VPN.
        self.vpn_only = set(vpn_only or ())
        self.states: dict[str, ModelState] = {}

        for model in registry.chat_models:
            spec = tierbook.get(model.gateway_id, model.model_id)
            self.states[model.ref] = ModelState(
                ref=model.ref,
                gateway=model.gateway_id,
                model=model.model_id,
                tier=spec.tier,
            )

    # ------------------------------------------------------------- состояние

    def set_mode(self, mode: str | Mode, *, manual_ref: str | None = None,
                 chain: list[str] | None = None) -> None:
        self.mode = Mode(mode) if not isinstance(mode, Mode) else mode
        if manual_ref is not None:
            self.manual_ref = manual_ref
        if chain is not None:
            self.chain = list(chain)

    def record(self, ref: str, status: str, *, error: str | None = None,
               duration_ms: int = 0, penalize: bool = True) -> None:
        """Записать результат вызова и обновить карантин.

        `penalize=False` — результат записывается, но карантин не ставится.
        Нужен для случая «аккаунт исчерпан, а модель жива»: отказ относится
        к ключу, а не к модели, и уводить её из ротации на `COOLDOWN` —
        значит отказаться от неё надолго по причине, которая вот-вот
        кончится сама.
        """
        state = self.states.get(ref)
        if state is None:
            return
        now = time.time()
        state.last_status = status
        state.last_error = error
        state.last_used = now

        if status in ("ok", "slow"):
            state.fails = 0
            state.ok_count += 1
            state.cooldown_until = 0.0
            if duration_ms > 0:
                # Экспоненциальное среднее — не даёт одному выбросу испортить оценку.
                state.avg_ms = duration_ms if not state.avg_ms else (
                    state.avg_ms * 0.7 + duration_ms * 0.3
                )
            return

        if not penalize:
            # Отказ засчитан в счётчике, но карантина нет: модель остаётся
            # доступной сейчас же.
            state.cooldown_until = 0.0
            return

        state.fails += 1
        base = COOLDOWN.get(status, 60.0)
        # Чем чаще падает, тем длиннее откат. Потолок — час: блокировка провайдера
        # это не «подожди и повтори», но и не навсегда — за сутки её перепроверят.
        backoff = min(base * (1.5 ** (state.fails - 1)), MAX_COOLDOWN_S)
        state.cooldown_until = now + backoff

    # --------------------------------------------------------------- выбор

    def all_ordered(self) -> list[str]:
        """Все известные модели по приоритету — независимо от режима.

        Нужно для списка выбора в интерфейсе. Режим влияет на то, какая модель
        используется сейчас, а не на то, какие модели вообще есть: в ручном
        режиме пользователь обязан видеть весь список, иначе сменить модель
        можно только через возврат в auto.
        """
        models = self.registry.chat_models
        latencies = {
            ref: s.avg_ms / 1000.0 for ref, s in self.states.items() if s.avg_ms > 0
        }
        ranked = rank_models(
            models,
            self.tierbook,
            require_vision=self.require_vision,
            prefer_speed=self.prefer_speed,
            latencies=latencies,
        )
        return [m.ref for m in ranked]

    def ordered(self) -> list[str]:
        """Модели, из которых агент выбирает сейчас, в порядке приоритета.

        В ручном режиме и по цепочке порядок задаёт пользователь, и доступность
        из региона на него не влияет: он сам выбрал конкретную модель. В auto
        модели, требующие VPN, опускаются вниз списка — но не выкидываются,
        иначе при выключенном VPN не нашлось бы вообще ничего.
        """
        if self.mode is Mode.MANUAL and self.manual_ref:
            return [self.manual_ref]
        if self.mode is Mode.CHAIN and self.chain:
            return [ref for ref in self.chain if ref in self.states]

        models = self.registry.chat_models
        latencies = {
            ref: s.avg_ms / 1000.0 for ref, s in self.states.items() if s.avg_ms > 0
        }
        ranked = rank_models(
            models,
            self.tierbook,
            require_vision=self.require_vision,
            # Только модели, умеющие вызывать инструменты. Переключение при
            # отказе не должно приводить к модели, которая не выдаст вызов
            # инструмента: задача выглядела бы сделанной, а на деле агент
            # просто описал словами то, чего не сделал.
            require_tools=True,
            prefer_speed=self.prefer_speed,
            latencies=latencies,
        )
        refs = [m.ref for m in ranked]
        if self.avoid_vpn and self.vpn_only:
            # Сначала то, что работает без VPN, потом остальное — иначе при
            # выключенном VPN агент бессмысленно долбится в заблокированные.
            refs = [r for r in refs if r not in self.vpn_only] + \
                   [r for r in refs if r in self.vpn_only]
        return refs

    def next_model(self, *, exclude: set[str] | None = None,
                   allow_cooldown: bool = False) -> str | None:
        """Следующая модель для вызова или None, если все исчерпаны.

        exclude: ref'ы, которые только что не сработали в этом же вызове.
        allow_cooldown: не пропускать модели в карантине (ручной режим).
        """
        exclude = exclude or set()
        for ref in self.ordered():
            if ref in exclude:
                continue
            state = self.states.get(ref)
            if state is None:
                continue
            # Без исключения для `blocked`. Раньше здесь стояло
            # `and state.last_status != "blocked"`, и это отменяло карантин
            # именно у заблокированных моделей: `COOLDOWN["blocked"]` равен
            # часу, `usable()` и снимок состояния считали модель
            # недоступной, а `next_model()` возвращал её на каждом шаге.
            # Итог: один заведомо закрытый провайдером ключ стоил одного
            # бесполезного запроса на каждом шаге каждой задачи, а в
            # интерфейсе модель при этом показывалась как «в карантине».
            if not allow_cooldown and state.in_cooldown:
                continue
            return ref
        return None

    def candidates(self) -> list[dict[str, Any]]:
        """Снимок состояния для UI: отсортировано по приоритету.

        В ручном режиме показываются **все** модели, а не только выбранная.
        Иначе список выбора состоял бы из одной строки: выбрать другую
        модель было бы нечем, и единственным выходом оставался возврат в auto.
        """
        rows = []
        for ref in self.all_ordered():
            state = self.states.get(ref)
            if state is None:
                continue
            row = state.to_dict()
            spec = self.tierbook.get(state.gateway, state.model)
            row["vision"] = spec.vision
            row["notes"] = spec.notes
            row["selected"] = ref == self.current
            rows.append(row)
        return rows

    @property
    def current(self) -> str | None:
        if self.mode is Mode.MANUAL:
            return self.manual_ref
        return self.next_model()

    def stats(self) -> dict[str, Any]:
        """Сводка для дашборда."""
        total = len(self.states)
        cooling = sum(1 for s in self.states.values() if s.in_cooldown)
        blocked = sum(1 for s in self.states.values() if s.blocked)
        ok = sum(1 for s in self.states.values() if s.last_status in ("ok", "slow"))
        return {
            "mode": self.mode.value,
            "manual_ref": self.manual_ref,
            "total": total,
            "ok": ok,
            "cooling": cooling,
            "blocked": blocked,
            "unknown": sum(1 for s in self.states.values() if s.last_status == "unknown"),
            "current": self.current,
        }


@dataclass
class Attempt:
    """Результат одной попытки внутри call_with_failover."""

    ref: str
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    skipped: bool = False
