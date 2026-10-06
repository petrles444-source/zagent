"""Рой агентов: большую задачу делают many работающих сразу.

Обычные субагенты берут столько аккаунтов, сколько попросили, и всё.
Рой отличается тремя вещами, и каждая стоила отдельного решения.

**Занять 70–80%, а не всё.** Свободный аккаунт — это единственный ресурс,
который тратится. Если раздать все, то при первом же отказе подменять
нечем, и задача встаёт там, где могла бы продолжиться. Резерв держится
намеренно: он не «запас про запас», а то, чем заменяют выбывшего
рабочего.

**Подмена выбывшего.** Часть может остаться без аккаунта, без лимита или
упасть целиком. Тогда она переходит на резервный аккаунт, и — что важнее —
получает чекпоинт предыдущего: продолжает с последнего шага, а не заново.
Если продолжить нечем, часть начинается с нуля: это честнее, чем делать
вид, что работа продолжается.

**Не выглядеть атакой.** Рой по природе шлёт много запросов сразу, и это
ровно то, что система защиты видит первым. Темп ограничен `hub/pacer.py`:
на аккаунт, по скользящей минуте, с разбросом при старте.

Главный агент при этом не простаивает. Пока части работают, он получает
то, что уже готово, и делает то, что можно делать без недостающих файлов.
Решение «ждать остальное» остаётся за ним: если без них нельзя, он так и
пишет, и сборка откладывается до их готовности.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hub.assign import Candidate, estimated_requests, needs_tools, needs_vision

#: Какую долю свободных аккаунтов занимают рабочие.
#:
#: Не 100%: без резерва подменять выбывшего нечем, и первая же потеря
#: аккаунта останавливает часть. Не 50%: это уже не рой, а обычные
#: субагенты. 75% — то, что оставляет резерв, способный закрыть треть
#: рабочих, и при этом реально грузит машину.
DUTY = 0.75

#: Сколько раз часть может быть переведена на другой аккаунт.
#:
#: Две, а не одна: подменённый аккаунт тоже может оказаться выбит, и одна
#: попытка оставила бы часть невыполненной при полном резерве. Больше двух
#: бессмысленно — три отказа подряд означают, что дело не в аккаунтах.
MAX_HANDOFF = 2

#: Как часто главному агенту показывают промежуточный результат, секунд.
#: Каждая передача — это запрос к модели, а модель не бесплатна; при этом
#: слишком редко главный агент простаивает впустую.
PARTIAL_EVERY_S = 45.0

#: Шагов на промежуточный взгляд.
#:
#: Взгляд между делом, а не второй заход по задаче. Полный прогон агента
#: стоил бы столько же запросов, сколько самая большая часть, и на коротких
#: частях обход дороже самой работы: замер 06.10.2026 на шести страницах дал
#: 183 с у роя против 61 с у обычного режима, и заметная доля ушла именно
#: на промежуточные сборки.
PARTIAL_STEPS = 2

#: Пока столько частей в работе, промежуточный взгляд не делается.
#:
#: Скоро финальная сборка, а она получит всё. Взгляд сейчас не даст ничего,
#: чего не будет через минуту, но запросы потратит.
TAIL_PARTS = 2

#: Проверяющих на финальной сборке.
#:
#: Проверка независима, поэтому её можно развести по аккаунтам: каждый
#: смотрит свою долю частей и ничего не решает. А вот сборка общих файлов и
#: ответ человеку не независима — один файл и один ответ пишутся целиком, и
#: два сборщика не сделают это быстрее, а каждый прочитает всё заново и
#: потратит вдвое больше. Поэтому проверяющих несколько, сборщик один.
#:
#: Три — потому что проверка идёт параллельно и упирается в лимиты
#: аккаунтов, а не в скорость: больше означает больше запросов при том же
#: результате.
MAX_CHECKERS = 3

#: Шагов проверяющему. Он читает файлы и отвечает одной строкой на часть.
#: Больше не нужно, а лишние запросы — ровно то, что проверка должна была
#: сэкономить.
VERIFY_STEPS = 4

#: Сколько частей нужно, чтобы проверка была отдельным этапом. Одна-две
#: части дешевле посмотреть сборщику, чем поднимать проверяющих.
VERIFY_MIN_PARTS = 3

#: Минимальная пауза между двумя запусками частей, секунд. Разброс нужен,
#: чтобы запросы разошлись по времени: пачка одинаковых запросов в одну
#: миллисекунду — самый заметный признак автоматизации.
STAGGER_S = 0.8


@dataclass
class Slot:
    """Один аккаунт с моделью, готовый принять часть работы."""

    gateway: str
    key: str
    ref: str
    model: str
    tier: int
    avg_ms: int
    vision: bool
    tools: bool
    rpm: int
    #: Имя части, которой аккаунт выдан. Пусто — свободен.
    taken_by: str = ""
    #: Почему аккаунт выпал: видно в интерфейсе, иначе резерв выглядит
    #: беспричинным набором пустых мест.
    note: str = ""
    #: Помечен как отказавший. Ставится снаружи — по живому отказу провайдера,
    #: — и нужен для замера: сам тест не должен решать за систему, кого
    #: считать отказавшим.
    blocked: bool = False

    @property
    def free(self) -> bool:
        return not self.taken_by

    def label(self) -> str:
        """Как показывать слот человеку: модель, шлюз и хвост аккаунта.

        Хвост ключа обязателен. Модель и шлюз у резервного и рабочего слотов
        одинаковы по определению — резерв это тот же шлюз, просто другой
        аккаунт. Без хвоста подмена выглядит как перевод с аккаунта на сам
        себя, и понять, куда перевели, невозможно.
        """
        return f"{self.ref} на {self.gateway} (…{self.key[-6:]})" if self.key \
            else self.ref

    def to_dict(self) -> dict[str, Any]:
        # Хвост ключа в интерфейсе обязателен: у рабочих и резервных слотов
        # одного шлюза модель и шлюз совпадают, и без хвоста они выглядят
        # одинаковыми. По хвосту же видно, что подмена ушла на другой
        # аккаунт, а не на соседний слот того же шлюза.
        return {"gateway": self.gateway, "ref": self.ref,
                "taken_by": self.taken_by, "rpm": self.rpm,
                "note": self.note,
                "key_tail": self.key[-6:] if self.key else ""}


@dataclass
class Plan:
    """Разбивка роя: кому какая часть и на каком аккаунте."""

    workers: list[Slot] = field(default_factory=list)
    reserve: list[Slot] = field(default_factory=list)
    #: Части, которым не досталось аккаунта: ждут резерва.
    unassigned: list[str] = field(default_factory=list)
    #: Почему столько рабочих и столько в резерве — показывается в интерфейсе.
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "workers": [s.to_dict() for s in self.workers],
            "reserve": [s.to_dict() for s in self.reserve],
            "unassigned": list(self.unassigned),
            "note": self.note,
        }


def slot_account(gateway: str, key: str) -> str:
    """Ключ, по которому ограничитель темпа считает этот аккаунт."""
    return f"{gateway}:{key[-8:]}"


def build_slots(selector: Any, gateways: list[dict], keyring: Any) -> list[Slot]:
    """Слоты: по одному на свободный аккаунт, с лучшей моделью его шлюза.

    Именно аккаунт, а не модель. Модель на шлюзе может быть десятки, а
    аккаунт один, и «раздать десять моделей на один ключ» — это не
    параллельная работа, а десять потребителей одного лимита.

    Ранг и задержка выбирают модель внутри шлюза: самая быстрая и самая
    близкая к началу списка. Модели без замера не берутся — поручать работу
    той, о чём ничего не известно, хуже, чем подождать.
    """
    rows: list[list[Slot]] = []
    states = getattr(selector, "states", {}) or {}
    tierbook = getattr(selector, "tierbook", None)
    seen: set[str] = set()

    for gateway in gateways:
        gateway_id = str(gateway.get("id") or "")
        ring = keyring.existing(gateway_id) if hasattr(keyring, "existing") \
            else keyring.ring(gateway_id)
        if ring is None:
            continue
        rpm = _rpm_of(gateway)
        best: dict[str, Slot] = {}
        for ref, state in states.items():
            if getattr(state, "gateway", "") != gateway_id:
                continue
            if not state.avg_ms or state.last_status not in ("ok", "slow"):
                continue
            spec = tierbook.get(state.gateway, state.model) if tierbook else None
            if spec is None or not spec.tools:
                # Модель без инструментов в рою бесполезна: часть, отданная
                # ей, не сделает ничего, а её слот сгорит впустую.
                continue
            key = ref
            slot = best.get(key)
            score = state.tier + state.avg_ms / 2000.0
            if slot is None or score < slot.tier + slot.avg_ms / 2000.0:
                best[key] = Slot(gateway=gateway_id, key="", ref=ref,
                                 model=state.model, tier=spec.tier,
                                 avg_ms=int(state.avg_ms), vision=spec.vision,
                                 tools=True, rpm=rpm)

        if not best:
            continue
        # Одна модель на шлюз: брать вторую незачем, аккаунты считаются, а
        # модель на одном аккаунте всё равно одна в момент времени.
        chosen = sorted(best.values(), key=lambda s: (s.tier, s.avg_ms))[0]

        made: list[Slot] = []
        for key in ring.available():
            # Аккаунт — это пара «шлюз, ключ», а не сам ключ. Один и тот же
            # ключ на двух шлюзах — это два разных аккаунта с разными
            # лимитами, и сверка по одному ключу молча выбрасывала бы второй.
            pair = (gateway_id, key)
            if pair in seen:
                continue
            seen.add(pair)
            made.append(Slot(gateway=gateway_id, key=key, ref=chosen.ref,
                             model=chosen.model, tier=chosen.tier,
                             avg_ms=chosen.avg_ms, vision=chosen.vision,
                             tools=True, rpm=rpm))
        if made:
            rows.append(made)
    return _interleave(rows)


def _interleave(rows: list[list[Slot]]) -> list[Slot]:
    """Перемешать слоты по шлюзам, чтобы рой не встал на одного провайдера.

    Порядок шлюзов в конфиге — это порядок объявления, а не готовность.
    Если просто идти по нему, то шлюз с наибольшим числом ключей заберёт
    почти все слоты, и части разойдутся по одному провайдеру. Дальше два
    неприятных следствия, и оба серьёзные.

    **Отказ одного провайдера убивает весь рой.** Части стоят на разных
    аккаунтах одного шлюза — отказ у провайдера общий для всех, и подменять
    нечем: резерв лежит там же.

    **Весь расход уходит на провайдера с наименее известными лимитами.**
    Именно у него чаще всего нет заголовков квоты, и рой идёт наугад.

    Перебор по кругу даёт каждому шлюзу сопоставимую долю, а уже из неё
    планирование возьмёт нужное число рабочих. Лишние слоты того же шлюза
    остаются в резерве — они и должны быть резервом.
    """
    out: list[Slot] = []
    depth = max((len(r) for r in rows), default=0)
    for i in range(depth):
        for row in rows:
            if i < len(row):
                out.append(row[i])
    return out


def _rpm_of(gateway: dict) -> int:
    try:
        return int(gateway.get("rpm_per_account") or 0)
    except (TypeError, ValueError):
        return 0


def make_plan(slots: list[Slot], parts: list[Any], *,
              duty: float = DUTY, workers: int | None = None) -> Plan:
    """Раздать слоты под части, остальные оставить резервом.

    Частей больше, чем рабочих, — норма: лишние части ждут освободившегося
    аккаунта, и это лучше, чем запускать их на одном ключе и получать отказ
    на середине.
    """
    pool = [s for s in slots if s.free]
    if workers is None:
        # Рабочих столько, сколько нужно частям, но не больше доли пула:
        # жадность здесь означает отсутствие резерва.
        workers = min(len(parts), int(len(pool) * duty))
        # Хотя бы один рабочий, если аккаунт вообще есть. Без этого
        # `int(1 * 0.75)` даёт ноль, и единственный свободный аккаунт уходил
        # в резерв, а задача выполнялась одним агентом — то есть режим
        # молча превращался в обычный, нигде не сказав об этом.
        if pool and workers == 0:
            workers = 1
    workers = min(workers, len(pool))

    plan = Plan()
    plan.workers = pool[:workers]
    plan.reserve = pool[workers:]
    _fix_sufficiency(plan, parts)

    # Назначение по годности, а не по порядку: часть с картинкой обязана
    # получить слот со зрением, иначе она потратит аккаунт впустую.
    order = sorted(range(len(parts)), key=lambda i: (
        0 if needs_tools(parts[i].brief, parts[i].files) else 1,
        0 if needs_vision(parts[i].brief, parts[i].files) else 1,
        -len(parts[i].files),
    ))
    for index in order:
        part = parts[index]
        slot = _pick(plan.workers, part)
        if slot is None:
            plan.unassigned.append(part.name)
            continue
        slot.taken_by = part.name

    busy = sum(1 for s in plan.workers if not s.free)
    spare = len(plan.reserve)
    if busy >= len(parts) and plan.unassigned == []:
        # Все части получили аккаунт, а свободные остались незанятыми. Это не
        # «плохо заполнено» и не недоделка: частей в задаче столько, сколько
        # получилось, и выдумывать работу ради занятости мощности нельзя.
        plan.note = (f"занято {busy} из {len(slots)} свободных аккаунтов, "
                     f"резерв {spare} — задача дала {len(parts)} частей, "
                     f"заняты все")
    else:
        plan.note = (f"занято {busy} из {len(slots)} свободных аккаунтов, "
                     f"резерв {spare}")
    return plan


def _fix_sufficiency(plan: Plan, parts: list[Any]) -> None:
    """Заменить рабочий слот на годный, если часть без него невозможна.

    Аккаунт с обычной моделью бесполезен для части, которой нужно зрение:
    он сгорит впустую, заняв и время, и место. Меняем его на годный из
    резерва — количество рабочих и резерва не меняется, меняется только
    годность. Именно «не меняется»: раздавать резерв под обычные части
    нельзя, иначе его не останется ровно тогда, когда он нужен.
    """
    for index, part in enumerate(parts):
        if _pick(plan.workers, part) is not None:
            continue
        want_vision = needs_vision(part.brief, part.files)
        want_tools = needs_tools(part.brief, part.files)
        spare = _pick(plan.reserve, part)
        if spare is None:
            continue
        # Место уступки: худший рабочий, которым эта часть всё равно не
        # могла бы заняться.
        worst = None
        for slot in plan.workers:
            if slot.taken_by:
                continue
            if want_vision and not slot.vision:
                worst = slot
                break
            if want_tools and not slot.tools:
                worst = slot
                break
            if worst is None or (slot.tier, slot.avg_ms) > (worst.tier,
                                                            worst.avg_ms):
                worst = slot
        if worst is None:
            continue
        plan.workers.remove(worst)
        worst.taken_by = ""
        worst.note = "уступил место годному под часть со зрением"
        plan.reserve.remove(spare)
        spare.note = "из резерва: рабочий слот не годен этой части"
        plan.workers.append(spare)


def _pick(pool: list[Slot], part: Any) -> Slot | None:
    """Слот для части: годный, а из годных — лучший."""
    want_vision = needs_vision(part.brief, part.files)
    want_tools = needs_tools(part.brief, part.files)
    for slot in pool:
        if not slot.free:
            continue
        if want_tools and not slot.tools:
            continue
        if want_vision and not slot.vision:
            continue
        return slot
    return None


def free_reserve(plan: Plan, gateway: str | None = None) -> Slot | None:
    """Взять свободный аккаунт из резерва.

    Предпочтение — тот же шлюз, где отказали: у другого шлюза может не быть
    модели, подходящей части, и подмена сменит не только аккаунт, но и
    качество работы.
    """
    for slot in plan.reserve:
        if slot.free and (gateway is None or slot.gateway == gateway):
            return slot
    for slot in plan.reserve:
        if slot.free:
            return slot
    return None


class Swarm:
    """Оркестратор роя.

    Держит части, слоты, резерв и то, что уже готово. Сам агент не запускает
    — запуск передаётся наружу (`run_part`), потому что агент, Guard и
    цикл остаются в воркере: оркестратору они не нужны, а дублировать их
    значило бы держать две копии одного цикла.
    """

    def __init__(self, *, plan: Plan, pacer: Any, task_id: int = 0,
                 emit: Any = None, max_handoff: int = MAX_HANDOFF) -> None:
        self.plan = plan
        self.pacer = pacer
        self.task_id = task_id
        self.emit = emit or (lambda event: None)
        self.max_handoff = max_handoff
        #: Готово: имя части → текст результата.
        self.done: dict[str, str] = {}
        #: Что готово, но с ошибкой.
        self.failed: dict[str, str] = {}
        #: Подмены: часть → сколько раз.
        self.handoffs: dict[str, int] = {}
        self.started = time.perf_counter()

    def slot_of(self, part_name: str) -> Slot | None:
        """Аккаунт, за которым сейчас числится часть.

        Ищется и в рабочих, и в резерве: после подмены часть стоит на
        резервном слоте, и поиск только по рабочим возвращал бы «никого» —
        а дальше подмена выглядела бы невозможной при полном резерве.
        """
        for slot in self.plan.workers:
            if slot.taken_by == part_name:
                return slot
        for slot in self.plan.reserve:
            if slot.taken_by == part_name:
                return slot
        return None

    def ready(self) -> str:
        """Сводка по готовым частям — для главного агента.

        Готовое и неготовое различаются явно: главный агент должен видеть,
        что часть не выполнена, а не считать задачу закрытой.
        """
        lines = []
        for name, text in self.done.items():
            lines.append(f"- {name}: сделано\n{text}")
        for name, error in self.failed.items():
            lines.append(f"- {name}: НЕ СДЕЛАНО ({error})")
        return "\n".join(lines)

    def pending(self) -> list[str]:
        out = []
        for slot in self.plan.workers:
            name = slot.taken_by
            if name and name not in self.done and name not in self.failed:
                out.append(name)
        return out

    def mark_done(self, part_name: str, summary: str) -> None:
        self.done[part_name] = summary
        self.emit({"type": "swarm_part_done", "task_id": self.task_id,
                   "sub": part_name, "summary": summary[:600]})

    def mark_failed(self, part_name: str, error: str) -> None:
        self.failed[part_name] = error
        self.emit({"type": "swarm_part_failed", "task_id": self.task_id,
                   "sub": part_name, "error": error[:300]})

    def handoff(self, part_name: str, reason: str) -> Slot | None:
        """Передать часть на резервный аккаунт. None — резерв кончился.

        Прежний слот освобождается: он либо исчерпан, либо сломался, и
        держать его занятым незачем — но если у него просто кончился лимит
        на минуту, он вернётся в строй через минуту сам.
        """
        if self.handoffs.get(part_name, 0) >= self.max_handoff:
            return None
        old = self.slot_of(part_name)
        gateway = old.gateway if old else None
        fresh = free_reserve(self.plan, gateway)
        if fresh is None:
            return None
        self.handoffs[part_name] = self.handoffs.get(part_name, 0) + 1
        if old is not None:
            old.taken_by = ""
            old.note = f"уступил часть «{part_name}»: {reason[:80]}"
        fresh.taken_by = part_name
        fresh.note = f"подхватил «{part_name}»: {reason[:80]}"
        self.emit({"type": "swarm_handoff", "task_id": self.task_id,
                   "sub": part_name, "reason": reason[:200],
                   "from": old.label() if old else "", "to": fresh.label()})
        return fresh