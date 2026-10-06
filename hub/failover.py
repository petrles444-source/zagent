"""Вызов модели с автоматическим переключением при отказе.

Центральная процедура агента: дать задачу, получить ответ. Если выбранная модель
упала (лимит, блокировка, сеть), берём следующую по приоритету и пробуем снова.
Каждая попытка записывается в состояние Selector, поэтому карантин накапливается:
агент не будет снова ломиться в модель, которая только что отдала 429.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Sequence

import httpx

from hub.select import Attempt, Mode, Selector
from hub.keyring import REGISTRY
from hub.tiers import TierBook
from providers.openai_compat import OpenAICompatProvider

Messages = Sequence[dict[str, Any]]

#: Сколько разных моделей пробовать за один вызов.
MAX_HOPS = 6

#: Тип отказа -> статус для state machine.
_STATUS_MAP = {
    "ok": "ok",
    "slow": "slow",
    "empty": "empty",
    "limited": "limited",
    "blocked": "blocked",
    "down": "down",
}


class FailoverError(RuntimeError):
    """Все модели в цепочке отказали."""

    def __init__(self, attempts: list[Attempt]) -> None:
        self.attempts = attempts
        summary = "; ".join(
            f"{a.ref}: {a.error or 'ошибка'}" + (" [пропущена]" if a.skipped else "")
            for a in attempts
        )
        super().__init__(f"Все модели недоступны. {summary}")


async def _classify(provider: OpenAICompatProvider, result: dict[str, Any]) -> str:
    """Перевести нормализованный результат провайдера в статус селектора."""
    error = result.get("error")
    http = result.get("status")
    if error is None:
        text = str(result.get("text") or "")
        reasoning = str(result.get("reasoning") or "")
        return "ok" if (text.strip() or reasoning.strip()) else "empty"

    message = str(error)
    if http == 429 or "Лимит запросов" in message:
        return "limited"
    if http in (401, 403):
        return "blocked"
    return "down"


class AutoCaller:
    """Обёртка над Selector: одна попытка = один вызов с переключением."""

    def __init__(
        self,
        selector: Selector,
        *,
        timeout: float = 90.0,
        max_hops: int = MAX_HOPS,
        manual_only: bool = False,
        slow_after_ms: int = 5000,
        empty_retries: int = 1,
    ) -> None:
        self.selector = selector
        self.timeout = timeout
        self.max_hops = max_hops
        #: manual_only: в ручном режиме не переключаться на другую модель.
        self.manual_only = manual_only
        self.slow_after_ms = slow_after_ms
        #: Сколько раз повторить запрос к той же модели при пустом ответе.
        #: Reasoning-модели иногда съедают весь max_tokens на размышление.
        self.empty_retries = empty_retries
        #: Закреплённая модель. Её выбирают заранее и осознанно (субагент
        #: получил часть именно потому, что эта модель подходит), поэтому
        #: первой пробуется именно она. Но «закреплена» не значит «единственная»:
        #: если у неё кончился лимит, запрос уходит к следующей, и диалог
        #: остаётся целым — работа продолжается с того же места, а не заново.
        self.pinned: str | None = None
        #: Закреплённый аккаунт. Лимит у провайдера считается на аккаунт, и
        #: части, работающие параллельно, обязаны стоять на разных: иначе
        #: восемь частей на одном ключе съедают его лимит за минуту и
        #: получают отказ. Ротация по кругу для этого не годится — она
        #: специально перемешивает запросы между аккаунтами.
        #:
        #: Закрепление снимается при отказе: если у этого аккаунта лимит
        #: кончился, следующая попытка идёт на любой свободный.
        self.pinned_key: str | None = None

    async def ask(
        self,
        messages: Messages,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        images: list[str] | None = None,
        include_attempts: bool = False,
    ) -> dict[str, Any]:
        """Выполнить вызов с переключением. Бросает FailoverError, если все отказали."""
        registry = self.selector.registry
        by_gateway = {g["id"]: g for g in registry.gateways}
        tried: set[str] = set()
        attempts: list[Attempt] = []

        # Картинки добавляются к последнему сообщению в формате OpenAI vision.
        payload_messages = _attach_images(messages, images)

        for _ in range(self.max_hops):
            # Закреплённая модель пробуется первой, дальше — обычная ротация.
            # Именно так теряется меньше работы: если у закреплённой модели
            # кончился лимит, диалог цел и следующая модель продолжает с
            # последнего шага, а не начинает часть заново.
            ref = (self.pinned if self.pinned and self.pinned not in tried
                   else self.selector.next_model(exclude=tried))
            if ref is None:
                # Всё в карантине. В ручном режиме пробуем выбранную модель любой ценой.
                if self.selector.mode is Mode.MANUAL and self.selector.manual_ref:
                    ref = self.selector.manual_ref
                    state = self.selector.states.get(ref)
                    if state and not state.blocked and state.cooldown_left:
                        attempts.append(
                            Attempt(ref=ref, ok=False, skipped=True,
                                    error=f"в карантине, осталось {state.cooldown_left} с")
                        )
                        break
                else:
                    break

            if ref in tried:
                break
            tried.add(ref)

            state = self.selector.states.get(ref)
            if state is None:
                continue

            gateway = by_gateway.get(state.gateway)
            if gateway is None:
                continue

            client = httpx.AsyncClient(follow_redirects=True)
            try:
                # Аккаунт закреплён — берём именно его: части в рое стоят на
                # своих ключах, и ротация по кругу это разрушила бы. Если
                # закреплённый аккаунт исчерпан, закрепление снимается и
                # работа продолжается на любом свободном — так теряется
                # меньше, чем при ожидании.
                if self.pinned_key:
                    ring = REGISTRY.ring(str(gateway.get("id")), REGISTRY.keys_of(gateway))
                    if ring.is_blocked(self.pinned_key):
                        self.pinned_key = None
                api_key = self.pinned_key or REGISTRY.next_key(gateway)
                # Расход отмечается до запроса: при отказе по лимиту неизвестно,
                # учтён ли этот запрос провайдером, и счётчик расползается.
                # Точнее нельзя — провайдер отвечает постфактум, а решение
                # нужно до запроса.
                if api_key:
                    REGISTRY.note_spent(gateway, api_key)
                if not api_key:
                    # Причина, по которой ключа не выдалось, разная, и
                    # сказать «карантин» мимо неё — значит отправить человека
                    # искать лимит там, где его нет. В нашем случае это стоило
                    # прогона: у шлюза не было ни одного ключа, а сообщение
                    # уверяло, что ключи есть и все выбиты по лимиту.
                    ring = REGISTRY.ring(
                        str(gateway.get("id")), REGISTRY.keys_of(gateway))
                    total = int(ring.stats().get("total") or 0)
                    attempts.append(
                        Attempt(ref=ref, ok=False,
                                error=("у шлюза нет ни одного ключа"
                                       if total == 0 else
                                       "все ключи провайдера в карантине по лимиту"))
                    )
                    break
                provider = OpenAICompatProvider(
                    state.gateway,
                    gateway["resolved_url"],
                    api_key,
                    timeout=self.timeout,
                    client=client,
                    extra_body=gateway.get("extra_body") or None,
                )
                result = await provider.chat(
                    state.model,
                    payload_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            finally:
                await client.aclose()

            duration_ms = int(result.get("duration_ms") or 0)
            status = await _classify(provider, result)

            # Лимит считается на аккаунт, поэтому исчерпание одного ключа не
            # должно уводить модель в карантин: другой аккаунт ещё свободен.
            # Остаток из заголовков запоминаем всегда, даже при успехе:
            # именно он позволяет до запроса решить, выдержит ли аккаунт
            # порученную часть из двадцати шагов.
            REGISTRY.note_quota(gateway, api_key, result.get("limits"))
            if status == "limited":
                REGISTRY.note_error(gateway, api_key, result.get("error") or "429")
            elif status == "ok":
                REGISTRY.note_ok(gateway, api_key)

            # Пустой ответ у reasoning-модели — не отказ модели, а нехватка
            # токенов. Повторяем с увеличенным лимитом, прежде чем считать отказом.
            empty_attempts = 0
            while status == "empty" and empty_attempts < self.empty_retries:
                empty_attempts += 1
                grown = _grow_budget(max_tokens)
                if grown is None:
                    break
                client = httpx.AsyncClient(follow_redirects=True)
                try:
                    # Повтор после пустого ответа идёт тем же ключом: он уже
                    # ответил и своё дело сделал. Брать другой незачем — так
                    # девять аккаунтов используются неравномерно.
                    # Счётчик расхода пополняется: повтор — тоже запрос,
                    # и без этого аккаунт выглядит потратившим меньше, чем
                    # потратил.
                    REGISTRY.note_spent(gateway, api_key)
                    provider = OpenAICompatProvider(
                        state.gateway, gateway["resolved_url"], api_key,
                        timeout=self.timeout, client=client,
                        extra_body=gateway.get("extra_body") or None,
                    )
                    result = await provider.chat(
                        state.model, payload_messages,
                        temperature=temperature, max_tokens=grown,
                    )
                finally:
                    await client.aclose()
                duration_ms = int(result.get("duration_ms") or 0)
                status = await _classify(provider, result)
                max_tokens = grown

                # Повтор мог упереться в лимит — аккаунт тогда надо пометить.
                REGISTRY.note_quota(gateway, api_key, result.get("limits"))
                if status == "limited":
                    REGISTRY.note_error(
                        gateway, api_key, result.get("error") or "429"
                    )
                elif status == "ok":
                    REGISTRY.note_ok(gateway, api_key)

            if status == "ok" and duration_ms >= self.slow_after_ms:
                status = "slow"

            self.selector.record(ref, status, error=result.get("error"),
                                 duration_ms=duration_ms)

            if status in ("ok", "slow"):
                answer = dict(result)
                answer.update(
                    model=ref,
                    status=status,
                    attempts=[_attempt_dict(a) for a in attempts] if include_attempts else None,
                    hops=len(attempts),
                )
                if include_attempts:
                    answer["attempts"] = [
                        *(_attempt_dict(a) for a in attempts),
                        {"ref": ref, "ok": True, "duration_ms": duration_ms},
                    ]
                return answer

            attempts.append(
                Attempt(
                    ref=ref,
                    ok=False,
                    error=result.get("error"),
                    duration_ms=duration_ms,
                )
            )

            # Модель ответила «лимит»: у этого шлюза есть другие аккаунты,
            # значит модель на самом деле жива. Не уводим её в карантин и
            # пробуем ту же модель ещё раз — с другим ключом.
            #
            # Два действия нужны, а стояло одно. `continue` без снятия отметки
            # в `tried` вёл на *другую* модель (следующая итерация берёт
            # `next_model(exclude=tried)`), а карантин при этом всё равно
            # ставился — `record` вызывался выше по коду безусловно. То есть
            # один исчерпанный аккаунт из девяти уводил живую модель в
            # пяти­минутный карантин вместо поворота на соседний аккаунт, и
            # хоп тратился впустую. Если других моделей нет, `next_model`
            # отдавал `None` и вызывался отказ, хотя свободные ключи были.
            if status == "limited" and self._has_free_key(gateway):
                tried.discard(ref)
                self.selector.record(ref, status, error=result.get("error"),
                                     duration_ms=duration_ms, penalize=False)
                continue

            if self.selector.mode is Mode.MANUAL and self.manual_only:
                break
            if self.selector.mode is Mode.MANUAL:
                # Ручной выбор: пользователь просил конкретную модель.
                # Не подменяем её молча — но даём шанс, если карантин истёк.
                break

            await asyncio.sleep(0.4)

        raise FailoverError(attempts)

    @staticmethod
    def _has_free_key(gateway: dict[str, Any]) -> bool:
        """Есть ли у шлюза ещё не выбитый ключ."""
        keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
        if len(keys) < 2:
            return False
        ring = REGISTRY.ring(str(gateway.get("id")), list(keys))
        return bool(ring.available())


#: Потолок лимита токенов при повторе после пустого ответа.
MAX_TOKENS_CEILING = 32768


def _grow_budget(max_tokens: int | None) -> int | None:
    """Увеличить лимит токенов для повтора. None — расти больше некуда."""
    if max_tokens is None:
        return 8192
    if max_tokens >= MAX_TOKENS_CEILING:
        return None
    return min(max_tokens * 2, MAX_TOKENS_CEILING)


def _attach_images(messages: Messages, images: list[str] | None) -> list[dict[str, Any]]:
    """Прикрепить base64-картинки к последнему сообщению в формате OpenAI vision.

    images: список data-URL вида "data:image/png;base64,..." или http(s)-ссылок.
    """
    prepared = [dict(m) for m in messages]
    if not images:
        return prepared

    if not prepared:
        prepared = [{"role": "user", "content": ""}]

    last = prepared[-1]
    content = last.get("content")
    if isinstance(content, str):
        parts: list[dict[str, Any]] = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        parts = list(content)
    else:
        parts = [{"type": "text", "text": ""}]

    for url in images:
        parts.append({"type": "image_url", "image_url": {"url": url}})

    last["content"] = parts
    return prepared


def _attempt_dict(attempt: Attempt) -> dict[str, Any]:
    return {
        "ref": attempt.ref,
        "ok": attempt.ok,
        "error": attempt.error,
        "duration_ms": attempt.duration_ms,
        "skipped": attempt.skipped,
    }


def build_selector(
    registry: Any,
    *,
    mode: str = "auto",
    manual_ref: str | None = None,
    chain: list[str] | None = None,
    prefer_speed: bool = False,
    require_vision: bool = False,
    root: str | None = None,
) -> Selector:
    """Собрать Selector с загруженным tiers.json."""
    return Selector(
        registry,
        TierBook.load(root),
        mode=Mode(mode) if isinstance(mode, str) else mode,
        manual_ref=manual_ref,
        chain=chain,
        prefer_speed=prefer_speed,
        require_vision=require_vision,
    )
