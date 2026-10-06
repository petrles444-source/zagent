"""Раздача ключей между аккаунтами одного провайдера.

Зачем это нужно. У OpenRouter лимит 50 запросов в сутки **на аккаунт**, а не
на ключ и не на IP. Один аккаунт — 50 запросов в день, и дальше `429` до
полуночи. Девять аккаунтов — 450 запросов, но только если трафик между ними
раскладывается, а не бьёт по первому.

Здесь две вещи:

* **выбор ключа по кругу** — чтобы запросы чередовались и лимит выбирался
  равномерно;
* **карантин ключа** — на ``429`` ключ выводится из ротации на время, указанное
  провайдером в заголовке ``Retry-After``. Без этого девять аккаунтов
  превращаются в девять последовательно выбитых: первый исчерпал лимит, второй
  тоже, и так далее.

Состояние живёт в памяти процесса и намеренно не сохраняется: после перезапуска
квоты всё равно восстанавливаются за сутки, а на диск состояние ротации
попадать не должно — там же лежат ключи.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

#: На сколько секунд отключить ключ, если провайдер не сказал Retry-After.
#: Для дневных лимитов OpenRouter это разумно: лучше не долбить до вечера.
DEFAULT_QUARANTINE = 3600.0

#: Верхняя граница карантина. Retry-After в 30 дней — это либо ошибка
#: провайдера, либо отказ навсегда, и такой ключ не должен блокировать шлюз.
MAX_QUARANTINE = 7 * 24 * 3600.0

#: Карантин аккаунта без денег. Ждать тут нечего: лимит не выбьется сам,
#: ключ заработает только после пополнения. Ставим почти максимум, чтобы
#: пустой аккаунт не занимал место в ротации, но освободился к утру, если
#: пользователь всё-таки пополнил.
EMPTY_ACCOUNT = MAX_QUARANTINE - 3600.0


def gateway_key(gateway: dict) -> str:
    """Ключ для разового вызова из данных шлюза.

    Одна строка вместо того, чтобы в каждом месте писать
    ``REGISTRY.next_key(gateway) or gateway["api_key"]``: если кольцо почему-то
    пустое, вызов не должен падать — в худшем случае пойдёт первый ключ.
    """
    keys = gateway.get("api_keys") or []
    if keys:
        return REGISTRY.next_key(gateway) or str(keys[0])
    return str(gateway.get("api_key") or "")


def note_gateway_error(gateway: dict, key: str, error: str) -> None:
    """Отметить ошибку ключа шлюза (429, 401) — короткое имя для вызовов."""
    REGISTRY.note_error(gateway, key, error)


def note_gateway_ok(gateway: dict, key: str) -> None:
    """Успешный ответ вернул ключ в ротацию."""
    REGISTRY.note_ok(gateway, key)


def fingerprint(key: str) -> str:
    """Короткая метка ключа для показа и логов.

    Сам ключ не выводится никогда: он попадает в отчёт, в stdout и в журнал,
    а там ему не место. 6 символов хвоста достаточно, чтобы человек узнал
    свой ключ в списке из девяти.
    """
    text = str(key or "")
    if not text:
        return "—"
    return "…" + text[-6:] if len(text) > 8 else text


@dataclass
class KeyRing:
    """Кольцо ключей одного шлюза с карантином по лимиту."""

    keys: list[str] = field(default_factory=list)
    #: ключ → время, до которого он не используется (0 — доступен)
    #: Ключи хранятся как есть: без ключа нельзя опознать аккаунт.
    blocked_until: dict[str, float] = field(default_factory=dict)
    #: Счётчик запросов на ключ — виден в интерфейсе, чтобы понимать, куда
    #: реально уходит трафик.
    used: dict[str, int] = field(default_factory=dict)
    #: ключ → что провайдер сообщил об остатке: осталось запросов, токенов,
    #: когда сброс. Заполняется из заголовков ответа.
    quota: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Почему ключ отключён: "429" или "401". Разные причины требуют разного
    #: решения: 429 ждёт времени, 401 — чинить ключ.
    reason: dict[str, str] = field(default_factory=dict)
    _cursor: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def empty(self) -> bool:
        return not self.keys

    def available(self) -> list[str]:
        """Ключи, которыми можно пользоваться прямо сейчас."""
        now = time.time()
        return [k for k in self.keys if self.blocked_until.get(k, 0.0) <= now]

    def note_quota(self, key: str, limits: dict[str, Any] | None) -> None:
        """Запомнить, сколько у аккаунта осталось.

        Без этого лимит известен только постфактум: агент получает 429 на
        середине части работы, и часть приходится начинать заново. С
        остатком известно заранее, и поручать аккаунту двадцать шагов при
        двух оставшихся запросах просто нельзя.
        """
        if not key or not limits:
            return
        clean = {k: v for k, v in limits.items() if v is not None}
        if not clean:
            return
        with self._lock:
            previous = self.quota.get(key) or {}
            merged = dict(previous)
            merged.update(clean)
            self.quota[key] = merged

    def quota_of(self, key: str) -> dict[str, Any]:
        """Что известно об остатке аккаунта. Пусто — провайдер не сообщает."""
        with self._lock:
            return dict(self.quota.get(key) or {})

    def capacity(self, key: str, need: int = 1) -> tuple[bool, str]:
        """Хватит ли аккаунту `need` запросов. False + причина.

        Считается по остатку запросов, а не по факту блокировки: аккаунт
        может быть не в карантине и при этом иметь ноль запросов на эту
        минуту — это разные вещи, и второе надо уметь предвидеть.
        """
        with self._lock:
            if self.blocked_until.get(key, 0.0) > time.time():
                return False, "в карантине"
            quota = self.quota.get(key) or {}
        remaining = quota.get("requests_remaining")
        if remaining is None:
            return True, ""  # провайдер не сообщает — судим по факту блокировки
        try:
            left = int(remaining)
        except (TypeError, ValueError):
            return True, ""
        if left < need:
            return False, f"осталось {left} запросов, нужно {need}"
        return True, f"осталось {left} запросов"

    def best_key(self, need: int = 1) -> tuple[str | None, str]:
        """Ключ с наибольшим известным остатком.

        Возвращает `(None, причина)`, если ни один аккаунт не выдержит `need`
        запросов. Причина перечисляет, чего не хватило: по ней решается, надо
        ли ждать минуту или это бессмысленно (например, осталось 0 у всех).
        """
        best: tuple[str | None, str] = (None, "нет доступных ключей")
        best_left = -1
        thin: list[str] = []
        for key in self.available():
            ok, note = self.capacity(key, need)
            if not ok:
                thin.append(note)
                continue
            left = (self.quota_of(key) or {}).get("requests_remaining")
            try:
                score = int(left)
            except (TypeError, ValueError):
                score = self.used.get(key, 0)
            if score > best_left:
                best_left = score
                best = (key, note)
        if best[0] is None and thin:
            best = (None, "; ".join(thin[:4]))
        return best

    def next_key(self) -> str | None:
        """Следующий доступный ключ по кругу.

        Возвращает ``None``, если доступных ключей нет: вызывающий код должен
        тогда не повторять попытку, а сообщить, что лимит исчерпан у всех
        аккаунтов сразу.
        """
        with self._lock:
            now = time.time()
            for offset in range(len(self.keys)):
                index = (self._cursor + offset) % len(self.keys)
                key = self.keys[index]
                if self.blocked_until.get(key, 0.0) <= now:
                    self._cursor = (index + 1) % max(1, len(self.keys))
                    self.used[key] = self.used.get(key, 0) + 1
                    return key
        return None

    def penalize(self, key: str, *, seconds: float | None = None,
                 why: str = "") -> float:
        """Отключить ключ на время: лимит кончился или ключ отозван.

        Возвращает, на сколько секунд ключ выведен из ротации.

        Короткие интервалы не поднимаются до секунды: иначе «подожди и
        попробуй снова через полсекунды» растягивалось бы на секунду, и в
        тестах, и по-настоящему при быстром переборе аккаунтов.
        """
        if not key:
            return 0.0
        with self._lock:
            wait = DEFAULT_QUARANTINE if seconds is None else float(seconds)
            wait = max(0.0, min(wait, MAX_QUARANTINE))
            if wait > 0:
                self.blocked_until[key] = time.time() + wait
            else:
                self.blocked_until.pop(key, None)
            if why:
                self.reason[key] = why
            return wait

    def release(self, key: str) -> None:
        """Вернуть ключ в ротацию — пришёл успешный ответ."""
        if not key:
            return
        with self._lock:
            self.blocked_until.pop(key, None)
            self.reason.pop(key, None)

    def is_blocked(self, key: str) -> bool:
        return self.blocked_until.get(key, 0.0) > time.time()

    def cooldown_left(self, key: str) -> int:
        """Сколько секунд ключ ещё недоступен (0 — доступен)."""
        return max(0, int(self.blocked_until.get(key, 0.0) - time.time()))

    def stats(self) -> dict[str, object]:
        """Сводка по кольцу для интерфейса.

        Ключи не выводятся: видны метки, счётчики и время ожидания. Этого
        достаточно, чтобы понять «один аккаунт выбит» или «выбиты все».
        """
        now = time.time()
        rows = []
        for key in self.keys:
            until = self.blocked_until.get(key, 0.0)
            rows.append({
                "label": fingerprint(key),
                "used": self.used.get(key, 0),
                "blocked": until > now,
                "cooldown": max(0, int(until - now)) if until > now else 0,
                "reason": self.reason.get(key, ""),
            })
        blocked = sum(1 for r in rows if r["blocked"])
        return {
            "total": len(self.keys),
            "available": len(self.keys) - blocked,
            "blocked": blocked,
            "keys": rows,
        }

    def note_error(self, key: str, error: str) -> None:
        """Отключить ключ по тексту ошибки от провайдера.

        Разбор текста вместо проверки кода: код ответа в этом слое уже
        потерян, а провайдеры пишут про лимит по-разному.

        Отдельно отличается «нет денег» от «кончился лимит». Оба приходят как
        429, но ждать в первом случае бесполезно: аккаунт пуст, и он останется
        пустым до пополнения. Помечать такой ключ как выбитый по лимиту
        нельзя — иначе через час выбитым окажется весь провайдер, а в отчёте
        будет написано «429», и человек пойдёт искать лимит там, где его нет.
        """
        text = str(error or "").lower()
        if not key or not text:
            return

        if ("insufficient" in text or "no resource" in text or "recharge" in text
                or "нет баланса" in text or "пополните" in text):
            self.penalize(key, seconds=EMPTY_ACCOUNT, why="нет баланса")
            return
        if "401" in text or "unauthorized" in text or "invalid" in text:
            # Ключ отозван или введён с ошибкой. Ждать бессмысленно.
            self.penalize(key, seconds=MAX_QUARANTINE, why="401")
            return
        if "429" in text or "rate limit" in text or "лимит" in text:
            self.penalize(key, why="429")


class KeyRegistry:
    """Кольца ключей для всех шлюзов.

    Живёт один на процесс: состояние между вызовами общее, иначе каждый
    запрос создавал бы своё кольцо и лимит выбивался бы по первому же ключу
    снова и снова.
    """

    def __init__(self) -> None:
        self._rings: dict[str, KeyRing] = {}
        self._lock = threading.Lock()

    def ring(self, gateway_id: str, keys: list[str]) -> KeyRing:
        """Кольцо шлюза, создаётся при первом обращении.

        Список ключей перечитывается при каждом вызове: файл секретов можно
        править на ходу, и после правки должен подхватиться новый ключ, а не
        старый из памяти.
        """
        clean = [str(k or "").strip() for k in keys if str(k or "").strip()]
        with self._lock:
            ring = self._rings.get(gateway_id)
            if ring is None or ring.keys != clean:
                # Набор ключей изменился: состояние прошлого кольца больше не
                # имеет смысла, но счётчики запросов хотелось бы сохранить.
                previous = ring or KeyRing()
                ring = KeyRing(keys=clean, used=dict(previous.used),
                               blocked_until=dict(previous.blocked_until),
                               reason=dict(previous.reason))
                self._rings[gateway_id] = ring
            return ring

    def next_key(self, gateway: dict) -> str | None:
        """Ключ для вызова по данным шлюза из config."""
        keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
        ring = self.ring(str(gateway.get("id")), list(keys))
        key = ring.next_key()
        if key:
            return key
        # Все ключи в карантине — берём лучший из худших, чтобы дать провайдеру
        # шанс: вдруг лимит уже снят, а мы его считаем не истёкшим.
        stats = ring.stats()
        if not stats["total"]:
            return None
        return ring.keys[self._least_used(ring)]

    def _least_used(self, ring: KeyRing) -> int:
        with ring._lock:
            if not ring.used:
                return 0
            return min(range(len(ring.keys)),
                       key=lambda i: ring.used.get(ring.keys[i], 0))

    def note_error(self, gateway: dict, key: str, error: str) -> None:
        """Отметить ошибку по ключу конкретного шлюза."""
        keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
        ring = self.ring(str(gateway.get("id")), list(keys))
        ring.note_error(key, error)

    def note_quota(self, gateway: dict, key: str,
                 limits: dict[str, Any] | None) -> None:
        """Передать кольцу остаток квоты, если провайдер его сообщил."""
        keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
        self.ring(str(gateway.get("id")), list(keys)).note_quota(key, limits)

    def note_ok(self, gateway: dict, key: str) -> None:
        keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
        ring = self.ring(str(gateway.get("id")), list(keys))
        # Ключ, которым реально ответили, вновь свободен — даже если до этого
        # он был помечен «нет баланса». Пополнение могло уже произойти, и
        # ждать семь дней после успешного ответа незачем.
        ring.release(key)

    def stats(self, gateway_id: str) -> dict[str, object]:
        ring = self._rings.get(gateway_id)
        if ring is None:
            return {"total": 0, "available": 0, "blocked": 0, "keys": []}
        return ring.stats()

    def snapshot(self) -> dict[str, dict[str, object]]:
        return {gid: ring.stats() for gid, ring in self._rings.items()}


#: Общее кольцо на процесс. Потокобезопасно: запросы идут из разных потоков
#: HTTP-обработчиков и из цикла воркера.
REGISTRY = KeyRegistry()