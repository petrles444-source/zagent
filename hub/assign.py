"""Выбор модели для части работы.

Это самая ответственная строка во всей схеме с субагентами. Ошибка здесь
выглядит как «работа идёт медленно» или «работа не идёт», и обе неприятны.

Четыре требования, которые выбор обязан выполнять одновременно.

**1. Выбор должен быть осознанным, а не первым попавшимся.**
Раньше каждая часть брала модель из общего списка по порядку, и все части
брали первую. Это не параллельная работа, это очередь: девять аккаунтов
работают на одну и ту же модель по одному ключу, и лимит кончается на всех
сразу. Части получают разные модели намеренно, и выбор записан так, чтобы
человек мог его прочитать.

**2. Проверять, вывезет ли аккаунт задачу, ДО её выдачи.**
Провайдеры сообщают остаток в заголовках ответа. Если у аккаунта осталось
три запроса, а части нужно двадцать, выдать ему эту часть — значит
потерять её на середине. Такие части уходят другому аккаунту или ждут.

**3. Модель должна уметь то, что требуется части.**
Инструменты нужны всем, кроме чисто текстовых. Картинки нужны одной части,
и та часть обязана получить модель со зрением — остальные получают обычные,
потому что зрящие модели медленнее.

**4. При исчерпании лимита работа не теряется.**
Модель, у которой кончился лимит, выходит из ротации, запрос идёт к
следующей, а диалог остаётся целым: следующая модель продолжает с того же
места, а не с нуля. Если не вывезла ни одна — часть возвращается главному
агенту со всем, что успела сделать, и он доделывает сам.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

#: Сколько запросов к модели приблизительно уходит на один шаг работы части.
#:
#: Агент с инструментами делает на каждое полезное действие два-три запроса:
#: один, чтобы решить, какой инструмент вызвать, и по одному на каждый вызов.
#: Занизить это число опасно: аккаунт закончится на середине части, и работа
#: пропадёт. Завысить — тогда аккаунтов хватит на всё и мы начнём ждать лимит
#: там, где можно было работать.
REQUESTS_PER_STEP = 2.5

#: Сколько шагов хватает части на среднюю задачу. Это оценка сверху: лучше
#: дать части запас, чем упереться в лимит на середине.
STEPS_PER_PART = 14

#: Насколько дорого брать модель, которая уже занята другой частью.
#:
#: В единицах ранга, а не «запрещено»: иначе при нехватке моделей часть
#: уходила к единственной свободной — как бы она ни была медленной — и задача
#: растягивалась в разы. Два штрафа за повтор обходятся быстрее, чем одна
#: тридцатисекундная модель.
REUSE_PENALTY = 2.0


@dataclass
class Assignment:
    """Кому какая модель и почему."""

    ref: str
    why: str
    gateway: str = ""
    #: Хватило ли аккаунта. False — часть не выдана, ждёт.
    admitted: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "why": self.why, "gateway": self.gateway,
                "admitted": self.admitted, "note": self.note}


@dataclass
class Candidate:
    """Модель, которую можно выдать части, с её характеристиками."""

    ref: str
    gateway: str
    model: str
    tier: int
    vision: bool
    tools: bool
    avg_ms: int
    free_keys: int
    #: Максимум запросов, который гарантированно есть в этом шлюзе.
    #: ``None`` — провайдер остаток не сообщает. Это не то же самое, что
    #: ноль: ноль означает «работать нельзя», а неизвестность — «решаем по
    #: карантину». Путать их опасно, потому что аккаунт с нулём запросов
    #: выглядит как «сведений нет» и получает часть, которая сгорит на
    #: первом же запросе.
    spare: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "gateway": self.gateway, "model": self.model,
                "tier": self.tier, "vision": self.vision, "tools": self.tools,
                "avg_ms": self.avg_ms, "free_keys": self.free_keys,
                "spare": self.spare}


def needs_vision(brief: str, files: list[str]) -> bool:
    """Нужна ли части модель со зрением.

    Слова из заданий и расширения картинок: картинка может прийти и без
    слова «посмотри», просто как приложенный файл.
    """
    text = (brief or "").lower()
    if any(word in text for word in (
            "по картинке", "по скриншоту", "по изображению", "скриншот",
            "картинк", "фото", "макет из картинки", "дизайн на фото")):
        return True
    return any(str(f).lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
               for f in files)


def needs_tools(brief: str, files: list[str]) -> bool:
    """Нужны ли части инструменты.

    Почти всегда да. Исключение — часть, которая только пишет текст: там
    вызов инструмента не нужен, и модель без инструментов справится быстрее.

    Проверяется наличие файлов, а не только слово: текстовая часть может
    попросить «напиши описание для index.html», и там инструмент нужен.
    """
    if files:
        return True
    text = (brief or "").lower()
    if any(word in text for word in (
            "напиши текст", "придумай текст", "сформулируй", "напиши описание",
            "придумай названия", "придумай слоган", "напиши письмо",
            "напиши тексты", "придумай сюжет")):
        return False
    return True


def estimated_requests(steps: int = STEPS_PER_PART) -> int:
    """Сколько запросов к модели уйдёт на часть такого размера."""
    return max(1, int(steps * REQUESTS_PER_STEP))


def collect_candidates(selector: Any, keyring: Any) -> list[Candidate]:
    """Живые модели с их задержкой и тем, сколько запросов у них есть.

    Считается из того, что уже измерено: задержка из последнего ответа,
    остаток из заголовков. Непроверенное не попадает в список вовсе —
    поручать работу модели, о которой ничего не известно, хуже, чем подождать.
    """
    out: list[Candidate] = []
    tierbook = getattr(selector, "tierbook", None)
    for ref, state in getattr(selector, "states", {}).items():
        if not state.avg_ms or state.cooldown_left:
            continue
        # Проверка именно на None: пустая книга рангов — это не отсутствие
        # книги. Ранги выводятся по названию модели, и это лучше, чем не
        # выдавать части вообще.
        spec = tierbook.get(state.gateway, state.model) if tierbook is not None else None
        if spec is None:
            continue
        if getattr(state, "last_status", "") not in ("ok", "slow"):
            continue
        gateway = ref.split("/", 1)[0]
        ring = _ring_of(keyring, state.gateway)
        # Считается то, что кольцо само считает свободным. Свой подсчёт
        # «не заблокирован» был обратным по смыслу и давал ноль свободных
        # аккаунтов у полностью свободного шлюза — то есть отказ выдавать
        # части там, где работать можно.
        free = len(ring.available()) if ring is not None else 0
        spare = _spare_requests(keyring, state.gateway)
        out.append(Candidate(
            ref=ref, gateway=state.gateway, model=state.model, tier=spec.tier,
            vision=spec.vision, tools=spec.tools, avg_ms=int(state.avg_ms),
            free_keys=free, spare=spare,
        ))
    return out


def _ring_of(keyring: Any, gateway_id: str) -> Any:
    """Кольцо ключей шлюза. Принимается и реестр, и готовое кольцо.

    И то и другое встречается по делу: в работе передаётся реестр со всеми
    шлюзами, в проверках — одно кольцо. Разница только в том, откуда его
    взять, и незаметив её, легко получить «ноль свободных аккаунтов» у
    единственного шлюза и выдать вывод о том, что работать некому.

    У реестра спрашивается уже созданное кольцо, а не создаётся новое: чтобы
    его создать, нужен список ключей, а читать здесь нужно состояние.
    """
    existing = getattr(keyring, "existing", None)
    if callable(existing):
        return existing(gateway_id)
    if getattr(keyring, "keys", None):
        return keyring
    return None


def _spare_requests(keyring: Any, gateway_id: str) -> int | None:
    """Сколько запросов гарантированно есть хотя бы у одного аккаунта.

    ``None`` — остаток неизвестен. Это честнее, чем угадывать: неизвестность
    и ноль запросов требуют разных решений.

    Если провайдер заголовков не присылает, но лимит в минуту известен из
    документации (так у NVIDIA — 40 запросов на аккаунт), остаток вычисляется
    из собственного счётчика расхода. Иначе решение принималось бы только
    после отказа, а часть к тому моменту уже половину работы потеряла.
    """
    ring = _ring_of(keyring, gateway_id)
    if ring is None:
        return None
    available = ring.available()
    if not available:
        return 0
    best: int | None = 0
    for key in available:
        left = (ring.quota_of(key) or {}).get("requests_remaining")
        if left is None:
            rpm = ring.rpm_of(key)
            if rpm:
                try:
                    left = int(rpm) - ring.spent_in_minute(key)
                except Exception:  # noqa: BLE001
                    left = None
        if left is None:
            # Хотя бы один аккаунт остаток не сообщает: сколько запросов
            # есть на самом деле, неизвестно, и сводить это к нулю нельзя —
            # тогда ни одна часть не была бы выдана.
            return None
        try:
            best = max(best if best is not None else 0, int(left))
        except (TypeError, ValueError):
            return None
    return best


def assign(candidates: list[Candidate], part: Any, *,
           need: int = 0, taken: dict[str, int] | None = None) -> Assignment | None:
    """Выбрать модель для части. None — подходящих нет.

    Порядок выбора отвечает на вопрос «какой модели поручить», а не «какая
    первая попалась»:

    1. годность — умеет инструменты, видит картинки, если они нужны;
    2. вывезет ли аккаунт — остаток запросов против оценки;
    3. скорость — она же и есть причина выбрать именно эту;
    4. ранг — последним, как разрешение равенства.

    Повторяющиеся модели не выдаются подряд: части одной задачи должны
    работать на разных аккаунтах, иначе параллельность только видимость.
    """
    taken = taken if taken is not None else {}
    need = need or estimated_requests()

    want_vision = needs_vision(part.brief, part.files)
    want_tools = needs_tools(part.brief, part.files)

    pool = [c for c in candidates
            if (not want_tools or c.tools)
            and (not want_vision or c.vision)
            and c.free_keys > 0]
    if not pool:
        return None

    # Хватает ли аккаунтов. Не выдаём часть, которая упрётся в лимит.
    # `spare is None` — сведений нет, судим по карантину; `spare == 0` —
    # запросов нет, и это уже известно, поэтому часть ждёт.
    able = [c for c in pool if c.spare is None or c.spare >= need]
    if not able:
        known = [c.spare for c in pool if c.spare is not None]
        best = max(known) if known else 0
        top = sorted(pool, key=lambda c: (c.tier, c.avg_ms))[0]
        return Assignment(
            ref=top.ref, gateway=top.gateway, admitted=False,
            # Часть не выдана, но и не потеряна: она ждёт, когда аккаунт
            # отдохнёт. Причина обязана быть названа — иначе непонятно,
            # чего ждать и почему задача встала.
            why=(f"модель {top.ref} не выдана: подходящего аккаунта с запасом "
                 f"на {need} запросов нет"),
            note=(f"нет аккаунта с запасом на {need} запросов; "
                  f"максимум {best}. Часть подождёт."))

    # Повторное использование модели штрафуется, но не запрещается. Раньше
    # действовало жёсткое «сначала незанятые»: когда все быстрые модели уже
    # заняты, а свободной осталась одна тридцатисекундная, часть уходила
    # к ней — и задача, которую можно было сделать за минуту, делалась за
    # двадцать. Штраф позволяет сравнивать честно: переиспользовать быструю
    # модель почти всегда лучше, чем взять очень медленную.
    ordered = sorted(
        able,
        key=lambda c: (c.tier + c.avg_ms / 2000.0 + REUSE_PENALTY * taken.get(c.ref, 0),
                       c.ref),
    )

    top = ordered[0]
    taken[top.ref] = taken.get(top.ref, 0) + 1

    reasons = [f"ранг {top.tier}"]
    if top.avg_ms:
        reasons.append(f"отвечает за {top.avg_ms / 1000:.2f} с")
    if top.free_keys > 1:
        reasons.append(f"свободных аккаунтов {top.free_keys}")
    if top.spare is not None:
        reasons.append(f"запас {top.spare} запросов, нужно ~{need}")
    if want_vision:
        reasons.append("видит картинки")
    if not want_tools:
        reasons.append("инструменты не нужны, берём самую быструю")

    return Assignment(ref=top.ref, gateway=top.gateway, why=", ".join(reasons),
                      admitted=True)


def assign_all(candidates: list[Candidate], parts: list[Any], *,
               steps: int = STEPS_PER_PART) -> list[Assignment | None]:
    """Назначить модель каждой части. Части без назначения ждут.

    Бюджет аккаунта расходуется по ходу. Без этого четыре части на одном
    аккаунте с сотней запросов обещают по тридцать пять — то есть сто
    сорок, — и лимит кончается на середине последней части. Проверка остатка
    идёт с учётом того, что уже обещано предыдущим частям.

    Обход — от самой «тяжёлой» части к самой лёгкой: если аккаунтов
    не хватает, лучше не выдать лёгкую часть (её главный агент доделает сам за
    пару шагов), чем тяжёлую, которую пришлось бы начинать заново.
    """
    need = estimated_requests(steps)
    order = sorted(
        range(len(parts)),
        key=lambda i: (0 if needs_tools(parts[i].brief, parts[i].files) else 1,
                       -len(parts[i].files), -len(parts[i].brief)),
    )
    taken: dict[str, int] = {}
    out: list[Assignment | None] = [None] * len(parts)
    # Что уже обещано каждой модели. Считается в запросах, а не в частях:
    # часть из двадцати шагов съедает заметно больше, чем часть из трёх.
    promised: dict[str, int] = {}
    for index in order:
        left = [replace(c, spare=_left(c, promised.get(c.ref, 0)))
                for c in candidates]
        got = assign(left, parts[index], need=need, taken=taken)
        out[index] = got
        if got is not None and got.admitted:
            promised[got.ref] = promised.get(got.ref, 0) + need
    return out


def _left(candidate: Candidate, promised: int) -> int | None:
    """Сколько запросов останется у модели после уже обещанных частей.

    ``None`` остаётся ``None``: когда провайдер не сообщает остаток,
    вычитать нечего, и получилась бы выдуманная точность — часть,
    которой хватило бы, вовсе не была бы выдана.
    """
    if candidate.spare is None:
        return None
    return candidate.spare - promised