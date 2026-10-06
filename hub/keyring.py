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


#: Окно, за которое считается расход. Ровно минута, потому что лимиты
#: «в минуту» считаются скользящим окном: запрос, ушедший 59 секунд назад,
#: освобождает место только что.
MINUTE_S = 60.0


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
    #: ключ → метки времени запросов за последнюю минуту. Свой счётчик нужен
    #: там, где провайдер остаток не сообщает: лимит известен из документации,
    #: а израсходовано — только отсюда.
    spent: dict[str, list[float]] = field(default_factory=dict)
    #: ключ → запросов в минуту на аккаунт. Переопределение для отдельного ключа;
    #: обычно лимит одинаков для всех, и тогда работает rpm_default.
    rpm: dict[str, int] = field(default_factory=dict)
    #: Запросов в минуту на аккаунт у всего шлюза (из config/gateways.json).
    #: Лимит принадлежит шлюзу, а не ключу: ключи у него меняются, а лимит
    #: остаётся. Если хранить его только на ключах, то ключ, добавленный
    #: позже, окажется без лимита — и именно на нём начнёт сыпаться 429.
    rpm_default: int = 0
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

    def note_spent(self, key: str, rpm: int | None = None) -> None:
        """Записать, что аккаунт потратил один запрос в текущей минуте.

        Нужно там, где провайдер остаток не сообщает. NVIDIA, например, не
        присылает заголовков квоты, а лимит у него жёсткий — 40 запросов в
        минуту на аккаунт. Без своего счётчика пришлось бы упираться в 429
        и узнавать о лимите постфактум; со счётчиком остаток известен заранее
        и часть можно не выдавать вовсе.

        Считается скользящее окно в минуту, потому что провайдер считает
        именно так: лимит не «обнуляется в начале минуты», а освобождается
        по мере истечения.
        """
        now = time.time()
        with self._lock:
            stamps = [t for t in self.spent.get(key, ()) if now - t < MINUTE_S]
            stamps.append(now)
            self.spent[key] = stamps
            if rpm:
                self.rpm_default = int(rpm)
            # Свой расход уменьшает и известный остаток из заголовков.
            # Иначе провайдер, присылающий остаток не на каждый ответ (или
            # один раз за сессию), давал бы вечное «48 осталось»: кольцо
            # считало бы по нему, части выдавались бы на несуществующую
            # квоту, и предостережение «ноль не то же самое, что неизвестно»
            # перестало бы работать в ту же секунду.
            row = self.quota.get(key)
            if row is not None:
                left = row.get("requests_remaining")
                if isinstance(left, (int, float)) and left > 0:
                    row["requests_remaining"] = left - 1

    def rpm_of(self, key: str) -> int:
        """Лимит в минуту для аккаунта. 0 — неизвестен."""
        return int(self.rpm.get(key) or self.rpm_default or 0)

    def set_rpm(self, rpm: int) -> None:
        """Запомнить лимит шлюза. Применяется ко всем аккаунтам сразу.

        Отдельным методом, а не записью по каждому ключу: ключ, добавленный
        позже, тоже обязан знать лимит, иначе именно на нём начнёт сыпаться
        429 — а выглядеть это будет как «NVIDIA выбивается», когда на самом
        деле выбился всего один аккаунт из четырёх.
        """
        with self._lock:
            self.rpm_default = int(rpm)

    def spent_in_minute(self, key: str) -> int:
        """Сколько запросов ушло по этому аккаунту за последнюю минуту."""
        now = time.time()
        with self._lock:
            stamps = [t for t in self.spent.get(key, ()) if now - t < MINUTE_S]
            self.spent[key] = stamps
            return len(stamps)

    def room(self, key: str, need: int = 1) -> tuple[bool, str]:
        """Хватит ли аккаунту `need` запросов в текущей минуте.

        Считается по собственному расходу и известному лимиту в минуту.
        Ограничение — не жёсткое: если все аккаунты исчерпаны, лучше рискнуть
        429, чем отказать в работе. Отказ приводит к тому, что задача не
        выполняется вовсе.
        """
        limit = self.rpm_of(key)
        if not limit:
            return True, ""
        used = self.spent_in_minute(key)
        left = limit - used
        if left < need:
            return False, (f"осталось {max(left, 0)} запросов из {limit} "
                           f"в минуту, нужно {need}")
        return True, f"осталось {left} из {limit} запросов в минуту"

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
            row = {
                "label": fingerprint(key),
                "used": self.used.get(key, 0),
                "blocked": until > now,
                "cooldown": max(0, int(until - now)) if until > now else 0,
                "reason": self.reason.get(key, ""),
            }
            # Остаток показывается рядом с лимитом: по одному числу
            # «израсходовано 38» непонятно, много это или мало, а по
            # «2 из 40» — сразу.
            if self.rpm_of(key):
                row["rpm_limit"] = self.rpm_of(key)
                row["rpm_spent"] = self.spent_in_minute(key)
                row["rpm_left"] = max(0, row["rpm_limit"] - row["rpm_spent"])
            rows.append(row)
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
        if "401" in text or "unauthorized" in text:
            # Ключ отозван или введён с ошибкой. Ждать бессмысленно.
            self.penalize(key, seconds=MAX_QUARANTINE, why="401")
            return
        if "429" in text or "rate limit" in text or "лимит" in text:
            self.penalize(key, why="429")
            return
        # Раньше сюда попадало и `if "invalid" in text`, и это была самая
        # дорогая ошибка в модуле: любая 400 вида
        # `invalid_request_error: max_tokens too large`, любой 404 или 500 с
        # словом «invalid» отправлял **рабочий** аккаунт в карантин на семь
        # суток, а в интерфейсе причиной значилось «401». Подстрока в тексте
        # ошибки ничего не значит: смысл в коде ответа, который в этот слой
        # не доходит, — поэтому спорные случаи оставляются как есть, а не
        # угадываются.


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
                # Остаток и расход — тоже: иначе смена набора ключей
                # выглядела бы как «аккаунты свежие», и часть выдалась бы
                # аккаунту, который на самом деле уже выбрал лимит.
                previous = ring or KeyRing()
                ring = KeyRing(keys=clean, used=dict(previous.used),
                               blocked_until=dict(previous.blocked_until),
                               reason=dict(previous.reason),
                               quota=dict(previous.quota),
                               spent={k: list(v) for k, v in previous.spent.items()},
                               rpm=dict(previous.rpm),
                               rpm_default=previous.rpm_default)
                self._rings[gateway_id] = ring
            return ring

    def existing(self, gateway_id: str) -> KeyRing | None:
        """Уже созданное кольцо шлюза, без создания и без ключей.

        Для чтения состояния. Создавать кольцо здесь нельзя: без списка
        ключей оно было бы пустым, и «свободных аккаунтов ноль» выглядело бы
        как правда там, где просто ничего не спрашивали.
        """
        return self._rings.get(str(gateway_id))

    def next_key(self, gateway: dict) -> str | None:
        """Ключ для вызова по данным шлюза из config."""
        keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
        ring = self.ring(str(gateway.get("id")), list(keys))
        key = ring.next_key()
        if key:
            return key
        # Все ключи в карантине. Возвращается `None`, а не «лучший из
        # худших»: выдача заведомо выбитого аккаунта означала бы, что каждый
        # хоп тратит запрос на ключ, который заведомо вернёт 429, — то есть
        # ровно то, ради чего карантин и нужен.
        #
        # `None` здесь значит две разные вещи: ключей нет вообще либо все
        # есть и все выбиты. Различать это должен вызывающий, иначе человек
        # получает ложь; `failover.py` смотрит на `stats["total"]`.
        stats = ring.stats()
        if not stats["total"]:
            return None
        if stats["available"] > 0:
            return ring.next_key()
        return None

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

    def note_spent(self, gateway: dict, key: str) -> None:
        """Отметить, что по аккаунту ушёл ещё один запрос.

        Счётчик свой, потому что провайдер может не сообщать остаток, а лимит
        при этом жёсткий. Знание о потраченном нужно и для показа в
        интерфейсе, и для решения, выдавать ли часть этому аккаунту.
        """
        keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
        self.ring(str(gateway.get("id")), list(keys)).note_spent(
            key, gateway.get("rpm_per_account"))

    def apply_limits(self, gateways: list[dict[str, Any]]) -> None:
        """Раздать кольцам известные лимиты из конфига.

        Заполняется при загрузке, а не по ходу работы: остаток аккаунта нужен
        до первого запроса, чтобы решить, выдавать ли часть. Если ждать первого
        ответа, решение примет уже факт отказа.
        """
        for gateway in gateways:
            rpm = gateway.get("rpm_per_account")
            if not rpm:
                continue
            keys = gateway.get("api_keys") or ([gateway["api_key"]] if gateway.get("api_key") else [])
            self.ring(str(gateway.get("id")), list(keys)).set_rpm(int(rpm))

    def keys_of(self, gateway: dict) -> list[str]:
        """Ключи шлюза из конфига — тот же список, что у кольца.

        Отдельный метод, чтобы не собирать его руками в каждом месте:
        расхождение между двумя списками означало бы, что кольцо считает не
        те аккаунты, с которыми работает агент, и лимит пересчитывается
        не по тем остаткам.
        """
        keys = gateway.get("api_keys") or (
            [gateway["api_key"]] if gateway.get("api_key") else [])
        return [str(k) for k in keys]

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