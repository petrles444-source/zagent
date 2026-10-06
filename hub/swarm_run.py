"""Запуск роя: планирование, параллельная работа, подмена, сборка.

Отдельно от `hub/swarm.py`, где живут план и правила, потому что здесь
единственное место, где встречаются агент, `Guard` и очередь задач. План
можно проверить без сети и без агента, а здесь — нельзя.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from hub.agent import Agent, AgentConfig, make_guard
from hub.autonomy import AccessLevel
from hub.failover import AutoCaller
from hub.pacer import PacedCaller, Pacer
from hub.swarm import (
    MAX_CHECKERS,
    PARTIAL_EVERY_S,
    PARTIAL_STEPS,
    STAGGER_S,
    TAIL_PARTS,
    VERIFY_MIN_PARTS,
    VERIFY_STEPS,
    Plan,
    Slot,
    Swarm,
    build_slots,
    make_plan,
    slot_account,
)
from hub.subagents import (
    denied_for_all,
    globs_for_all,
    scope_paths,
)


#: Требование к разбиению для роя. Отличается от обычного тем, что частей
#: просят много: разбиение делается один раз, а части идут параллельно, и
#: крупная задача (сайт на много страниц, приложение с модулями) как раз
#: распадается на десяток-другой независимых кусков.
#:
#: Про совместимость сказано прямо: части, которые зависят друг от друга,
#: в рою работать не могут — их результат нужен обеим сразу, а рою
#: приходится ждать самой медленной из них перед сборкой.
HERD_SYSTEM = (
    "Ты разбиваешь большую задачу на независимые части для команды "
    "агентов, которые будут работать одновременно. "
    "Ответь ТОЛЬКО JSON, без пояснений и без блока ```json:\n"
    '{"parts": [{"title": "короткое имя", "brief": "что именно сделать", '
    '"files": ["путь/папка"]}]}\n'
    "\n"
    "Правила:\n"
    "- ЧАСТЕЙ_СКОЛЬКО\n"
    "- Части не должны трогать одни и те же файлы. У каждой свои files.\n"
    "- Части не должны зависеть друг от друга. Порядок не соблюдается: "
    "все стартуют одновременно, поэтому части, которой нужен результат "
    "другой, ждать придётся в конце.\n"
    "- files — то, что агент создаёт или правит: папка, файл или маска вида "
    "src/*.js. Читать можно всё, писать — только своё.\n"
    "- brief — задание для агента целиком: что сделать, каким должен быть "
    "результат. Пиши как заказчик, а не как программист.\n"
    "- Общие файлы (главная страница, индекс, манифест) не отдавай никому: "
    "их соберёт главный агент в конце.\n"
    "- Не дроби то, что дешевле сделать целиком: чтение одного файла, "
    "правку одной строки, ответ на вопрос."
)


def _mark_of(verdict: str) -> str:
    """Что на самом деле сказал проверяющий: «ГОТОВО», «ПРОБЛЕМА» или ничего.

    Ищется **внутри** строки, а не по началу. Вердикт приходит с именем
    части впереди («часть 1: ПРОБЛЕМА — файл пустой»), и проверка по началу
    объявляла бы любую проблему «проверка не удалась» — то есть сборщик
    получил бы неверную причину и пошёл бы чинить не то.
    """
    text = (verdict or "").upper()
    if "ПРОБЛЕМА" in text:
        return "ПРОБЛЕМА"
    if "ГОТОВО" in text:
        return "ГОТОВО"
    return ""


def _split_evenly(items: list[Any], groups: int) -> list[list[Any]]:
    """Разложить части по проверяющим поровну.

    Поровну, а не «пока не кончатся»: неравномерная делёжка означает, что
    один проверяющий сидит вдвое дольше другого, а время роя определяет
    самый долгий.
    """
    groups = max(1, min(groups, len(items)))
    out: list[list[Any]] = [[] for _ in range(groups)]
    for index, item in enumerate(items):
        out[index % groups].append(item)
    return [g for g in out if g]


def _verdict_for(text: str, part: Any) -> str:
    """Вытащить вердикт по одной части из ответа проверяющего.

    Ответ запрашивался построчно, но модель могла завернуть его в список,
    добавить нумерацию или вовсе ответить одной фразой. Здесь ищется строка с
    именем части; если её нет, берётся первая строка, похожая на вердикт, а
    если нет и её — весь ответ целиком. Ложное «ГОТОВО» хуже отсутствия
    вердикта, поэтому неизвестное никогда не превращается в «всё хорошо».
    """
    body = " ".join((text or "").split())
    if not body:
        return "не проверено: проверяющий не ответил"
    name = (part.name or "").strip()
    for line in (text or "").splitlines():
        clean = " ".join(line.split()).lstrip("-*0123456789. ")
        if name and clean.startswith(name):
            return clean[:300]
    for line in (text or "").splitlines():
        clean = " ".join(line.split()).lstrip("-*0123456789. ")
        if clean.startswith("ГОТОВО") or clean.startswith("ПРОБЛЕМА"):
            return clean[:300]
    return "не проверено: " + body[:240]


def files_ready(part: Any, base: Path, *, since: float = 0.0) -> list[str]:
    """Какие файлы части появились на диске — и не раньше `since`.

    Часть объявляет свои файлы при разбиении — иногда точно (`index.html`),
    иногда маской (`src/*.js`). И то и другое раскрывается на настоящем
    диске: иначе пришлось бы верить модели на слово, а модель может написать
    «готово» и ничего не создать.

    Время изменения обязательно. Воркспейс переиспользуется между
    задачами, и без этого чужой файл от прошлой задачи засчитывался
    провалившейся части: модель упала на первом запроске, файл от вчерашнего
    прогона лежит на месте — и часть объявлялась выполненной, причём с
    пустым отчётом и без единого шага. Ровно то, ради чего вердикт и берётся
    с диска, а не со слов.
    """
    out: list[str] = []
    for raw in getattr(part, "files", None) or []:
        rel = str(raw).strip().lstrip("./")
        if not rel:
            continue
        target = base / rel
        try:
            if any(ch in rel for ch in "*?["):
                for found in sorted(base.glob(rel)):
                    if found.is_file() and _fresh_enough(found, since):
                        out.append(str(found.relative_to(base).as_posix()))
            elif target.is_file() and target.stat().st_size:
                if _fresh_enough(target, since):
                    out.append(rel)
        except (OSError, ValueError):
            continue
    return out


def _fresh_enough(path: Path, since: float) -> bool:
    """Менялся ли файл после начала попытки части."""
    if since <= 0:
        return True
    try:
        return path.stat().st_mtime >= since - 2.0
    except OSError:
        return False


def system_of(agent: Agent) -> str:
    """Системный промт агента.

    Берётся из готового диалога, а не собирается заново: иначе главный агент
    получил бы другое окружение при сборке, чем при работе, и перестал бы
    видеть свои границы и правила. Если диалога ещё нет — пустая строка
    вместо падения: сборка не должна рушиться из-за того, что агент не
    начат.
    """
    for message in (agent.messages or []):
        if message.get("role") == "system":
            return str(message.get("content") or "")
    return ""


def herd_system(want: int) -> str:
    """Промт разбиения с настоящим числом частей.

    Без числа модель берёт «4–12» из инструкции и обычно выдаёт три: три
    страницы она видит, а тридцать аккаунтов — нет. Проблема не в том, что
    три части получились плохими, а в том, что половина флота молчит без
    причины. Число нужно сказать прямо.
    """
    return HERD_SYSTEM.replace(
        "ЧАСТЕЙ_СКОЛЬКО",
        f"Сейчас свободно аккаунтов под работу — выбирайте частей около {want}. "
        f"Больше {want} всё равно не встанет в строй: лишние части будут ждать "
        f"свободного аккаунта, а времени на это нет.",
    )


class SwarmRun:
    """Один прогон роя внутри задачи."""

    def __init__(self, *, worker: Any, agent: Agent, config: AgentConfig,
                 parts: list[Any], task: dict[str, Any],
                 task_context: str) -> None:
        self.worker = worker
        self.agent = agent
        self.config = config
        self.parts = parts
        self.task = task
        self.task_context = task_context
        self.task_id = int(task["id"])
        self.base = Path(config.base_dir)

        self.pacer = Pacer(max_parallel=max(2, len(parts)))
        self.events: list[dict[str, Any]] = []
        self.swarm: Swarm | None = None
        #: Результаты частей: имя → (ок, текст, ошибка).
        self.results: dict[str, dict[str, Any]] = {}
        #: Вердикты проверяющих: имя части → строка. Сборщику они вместо
        #: сырых отчётов: «ГОТОВО» или «ПРОБЛЕМА — что».
        self.verdicts: dict[str, str] = {}
        #: Чекпоинт каждой части — им продолжает подменяющий.
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.asyncio_tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------- события

    def emit(self, event: dict[str, Any]) -> None:
        event.setdefault("task_id", self.task_id)
        self.events.append(event)
        self.worker.emit(event)

    # ------------------------------------------------------------- запуск

    def build_plan(self) -> Plan:
        """Раздать свободные аккаунты: рабочие и резерв."""
        slots = build_slots(self.worker.selector, self.worker.gateways,
                            self.worker.keyring)
        plan = make_plan(slots, self.parts)
        for slot in slots:
            self.pacer.set_rpm(slot_account(slot.gateway, slot.key), slot.rpm)
        self.swarm = Swarm(plan=plan, pacer=self.pacer, task_id=self.task_id,
                           emit=self.emit)
        self.emit({"type": "swarm_plan", "task_id": self.task_id,
                   "plan": plan.to_dict()})
        return plan

    def make_agent(self, part: Any, slot: Slot, index: int,
                   denied: list[list[str]], globs: list[list[str]]) -> Agent:
        """Агент части на конкретном аккаунте.

        Закрепляются и модель, и аккаунт: ротация по кругу раздала бы части
        чужие ключи и упёрлась бы в лимит одного аккаунта.
        """
        guard = make_guard(self.config)
        guard.protected = list(getattr(self.agent.guard, "protected", []) or [])
        guard.set_workspace(
            str(self.base), None,
            granted=scope_paths(part.files, self.base),
            denied=denied[index],
            soft_boundary=bool(self.agent.guard.soft_boundary),
        )
        guard.denied_globs = globs[index]

        account = slot_account(slot.gateway, slot.key)
        caller = AutoCaller(self.worker.selector, timeout=self.config.step_timeout,
                            empty_retries=2)
        caller.pinned = slot.ref
        caller.pinned_key = slot.key

        # Конфиг у каждой части свой. Объект конфига общий, а `Agent.run()`
        # читает `max_steps` в каждом шаге, и главный агент во время
        # промежуточного взгляда уменьшает его на время своего прогона: все
        # живые части в этот момент получали бы лимит в два шага и обрывались
        # на середине работы. Копия стоит ничто и снимает класс ошибок целиком.
        part_agent = Agent(
            self.worker.selector, guard, replace(self.config),
            on_event=lambda event: self._on_part_event(part.name, event),
            caller=PacedCaller(caller, self.pacer, account, slot.rpm),
        )
        part_agent.part = part.name
        part_agent.trace_on = True
        return part_agent

    def _on_part_event(self, part_name: str, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("sub", part_name)
        self.worker.emit(payload)

    def part_task(self, part: Any) -> str:
        """Задание части: исходная задача плюс конкретный заказ.

        Без исходной задачи агент не знает, что делает часть общей работы, и
        выдаёт узкий кусок, не согласующийся с остальными.
        """
        if self.task_context:
            return self.task_context + "\n\n" + part.brief
        return part.brief

    async def run_one(self, part: Any, slot: Slot, index: int,
                      denied: list[list[str]], globs: list[list[str]],
                      attempt: int = 0) -> dict[str, Any]:
        """Одна попытка части. Отказ не роняет роя."""
        started = time.perf_counter()
        try:
            part_agent = self.make_agent(part, slot, index, denied, globs)
            part_agent.set_task(self.part_task(part))
            if attempt:
                # Подмена продолжает чекпоинт предыдущей попытки: работа не
                # начинается заново, если есть что продолжать.
                saved = self.checkpoints.get(part.name)
                if saved and part_agent.restore_checkpoint(saved):
                    self.emit({"type": "swarm_resumed", "task_id": self.task_id,
                               "sub": part.name,
                               "note": "продолжает с последнего шага"})
            outcome = await part_agent.run()
            self.checkpoints[part.name] = part_agent.checkpoint or {}
            elapsed = int((time.perf_counter() - started) * 1000)
            ok = bool(outcome.get("ok"))
            text = str(outcome.get("last") or "")[:1500]
            error = str(outcome.get("error") or "")
            tools = [getattr(s, "tool", None) for s in part_agent.steps]
            tools = [t for t in tools if t]
            models = sorted({s.model for s in part_agent.steps if s.model})
            steps = len(part_agent.steps)
            # Причина отказа берётся из первого шага с ошибкой. Основной путь
            # `Agent.run()` ключа `error` не отдаёт вовсе — причина живёт в
            # шагах, — и без этого подмена не включалась никогда: решала,
            # что отказа аккаунта не было. Берётся первый, а не последний:
            # после первого отказа все следующие повторяют «все модели
            # недоступны», и по последнему причина читалась бы как «агент
            # сломался».
            first_error = next((getattr(s, "error", None)
                               for s in part_agent.steps
                               if getattr(s, "error", None)), "")
            if not error and first_error:
                error = str(first_error)
        except Exception as exc:  # noqa: BLE001
            ok, text, error = False, "", f"{type(exc).__name__}: {exc}"
            tools, models, steps, elapsed = [], [], 0, 0

        # Вердикт с диска, а не от модели. Часть, которая написала свои
        # файлы, но не успела сказать «готово» (лимит шагов кончился на
        # последнем ответе), сделала работу. Обратное тоже верно: модель
        # может написать «готово» и ничего не создать.
        #
        # Без этого части, выполнившие задание, попадали в отчёт как
        # невыполненные, главный агент получал «НЕ СДЕЛАНО» по всем частям,
        # а подмена уводила на резервный аккаунт тех, кто уже закончил.
        made = files_ready(part, self.base, since=started)
        by_disk = bool(made) and not ok
        if by_disk:
            ok = True
            error = ""

        return {"ok": ok, "summary": text, "error": error, "tools": tools,
                "models": models, "steps": steps, "elapsed_ms": elapsed,
                "slot": slot, "attempt": attempt, "files": made,
                "by_disk": by_disk}

    async def run_part(self, part: Any, index: int, slot: Slot,
                       denied: list[list[str]],
                       globs: list[list[str]]) -> None:
        """Часть целиком: попытка, подмена при отказе, фиксация результата.

        Подмена происходит один раз и только если есть свободный резерв.
        Без резерва часть просто не выполнена — и это видно в отчёте, а не
        прячется попыткой запустить её на чужом аккаунте.
        """
        current = slot
        attempt = 0
        result: dict[str, Any] = {}
        while True:
            await asyncio.sleep(STAGGER_S * (1 + attempt))
            result = await self.run_one(part, current, index, denied, globs,
                                        attempt=attempt)
            if result["ok"]:
                break
            # Причина сюда идёт как есть, без замены на слова. Подмена на
            # «работа не завершена» означала бы, что самый частый отказ —
            # оборванный на первом шаге запрос — никогда не подменялся: в
            # тексте нет ни слова про аккаунт, и проверка решала, что дело
            # в модели.
            reason = str(result.get("error") or "")
            if not _worth_handoff(reason, int(result.get("steps") or 0)):
                break
            fresh = self.swarm.handoff(part.name, reason) if self.swarm else None
            if fresh is None:
                break
            current = fresh
            attempt += 1

        self.results[part.name] = result
        if result["ok"] and self.swarm:
            self.swarm.mark_done(part.name, result["summary"])
        elif self.swarm:
            self.swarm.mark_failed(part.name, result["error"] or "не выполнено")

    async def start_parts(self, plan: Plan, denied: list[list[str]],
                          globs: list[list[str]]) -> None:
        """Запустить части параллельно, но с разбросом стартов."""
        index_of = {id(p): i for i, p in enumerate(self.parts)}
        for part in self.parts:
            slot = None
            for candidate in plan.workers:
                if candidate.taken_by == part.name:
                    slot = candidate
                    break
            if slot is None:
                # Часть без аккаунта раньше просто не стартовала и
                # исчезала из отчёта: её не было ни в результатах, ни в
                # сводке, ни среди «не выполнено». Задача «разбита на
                # 10 частей, сделано 4» выглядела как «разбита неудачно».
                # Теперь такая часть попадает в результат и в сводку с
                # честной причиной.
                reason = ("не достался свободный аккаунт: частей больше, "
                          "чем могли занять рабочие")
                self.results[part.name] = {
                    "ok": False, "summary": "", "error": reason,
                    "tools": [], "models": [], "steps": 0,
                    "elapsed_ms": 0, "attempt": 0, "files": [],
                    "by_disk": False,
                }
                if self.swarm is not None:
                    self.swarm.mark_failed(part.name, reason)
                continue
            self.asyncio_tasks[part.name] = asyncio.create_task(
                self.run_part(part, index_of[id(part)], slot, denied, globs))

    async def wait_parts(self) -> None:
        if self.asyncio_tasks:
            await asyncio.gather(*self.asyncio_tasks.values(),
                                 return_exceptions=True)

    async def partial_round(self) -> str:
        """Показать главному агенту то, что уже готово.

        Главный агент не простаивает: он получает сводку и делает то, что
        можно сделать без недостающих файлов. Решение «ждать остальное» за
        ним: если без них нельзя, он так и пишет.

        Проход короткий и намеренно ограничен. Это взгляд «между делом», а
        не второй заход по задаче: полный прогон агента здесь съедал бы
        столько же запросов, сколько самая большая часть, и на коротких
        частях обход дороже работы. Замер 06.10.2026 это показал: на шести
        страницах рой ушёл в 183 с против 61 с у обычного режима, и треть
        времени ушла именно на промежуточные сборки.
        """
        swarm = self.swarm
        if swarm is None:
            return ""
        ready = swarm.ready()
        if not ready:
            return ""
        waiting = list(swarm.pending())
        if len(waiting) <= TAIL_PARTS:
            # Скоро финальная сборка, и она получит всё. Промежуточный взгляд
            # сейчас не нужен: он не даёт результата, которого не будет через
            # минуту, но стоит запросов.
            return ""
        self.agent.messages = [
            {"role": "system", "content": system_of(self.agent)},
            {"role": "user", "content": self.task_context},
            {"role": "user", "content":
                "Часть работы уже готова:\n\n" + ready +
                f"\n\nЕщё в работе: {', '.join(waiting)}."
                "\n\nСделай ОДНО действие прямо сейчас, не дожидаясь остальных: "
                "общий файл, проверка согласованности, то, что не "
                "принадлежит ни одной части. Одна попытка, не больше.\n"
                "Если без недостающих файлов задачу закрыть нельзя, так и "
                "напиши одной строкой: НУЖНО ЖДАТЬ."},
        ]
        self.agent._reset_cycle()
        outcome = await self._run_briefly(PARTIAL_STEPS)
        # Текст берётся из ответа агента, а не из последнего шага: ответ —
        # это то, что агент сам считает своим ответом, и шаг мог закончиться
        # вызовом инструмента без текста.
        last = str((outcome or {}).get("last") or "")
        if not last and self.agent.steps:
            last = self.agent.steps[-1].text or ""
        self.emit({"type": "swarm_partial", "task_id": self.task_id,
                   "done": list(swarm.done), "pending": waiting,
                   "note": last[:300]})
        return last

    async def _run_briefly(self, limit: int) -> dict[str, Any]:
        """Прогнать агента ограниченным числом шагов.

        Лимит меняется у агента, а не у конфига задачи: конфиг общий со всеми
        частями роя, а `Agent.run()` читает `max_steps` в каждом шаге, и
        уменьшение общего объекта на время промежуточного взгляда обрывало бы
        части, которые в этот момент работают. Части получают копию конфига
        в `make_agent`, а здесь меняется только поле агента — оно своё у
        каждого экземпляра.
        """
        agent_config = getattr(self.agent, "config", None)
        if agent_config is None:
            return await self.agent.run()
        saved = agent_config.max_steps
        try:
            agent_config.max_steps = min(saved, max(1, limit))
            return await self.agent.run()
        finally:
            agent_config.max_steps = saved

    async def supervise(self, denied: list[list[str]],
                        globs: list[list[str]]) -> None:
        """Ждать части, попутно показывая главному агенту готовность."""
        last = time.perf_counter()
        while True:
            finished = [t for t in self.asyncio_tasks.values() if t.done()]
            if len(finished) == len(self.asyncio_tasks):
                return
            done, _ = await asyncio.wait(
                [t for t in self.asyncio_tasks.values() if not t.done()],
                timeout=PARTIAL_EVERY_S, return_when=asyncio.FIRST_COMPLETED)
            now = time.perf_counter()
            if now - last >= PARTIAL_EVERY_S or done:
                last = now
                await self.partial_round()

    # ------------------------------------------------------------- проверка

    def make_checker(self, slot: Slot) -> Agent:
        """Проверяющий: свой агент, свой аккаунт, прав на запись нет.

        Права только на чтение — не из вежливости, а потому что проверка не
        имеет права чинить. Сборщик потом чинит всё сам и видит картину
        целиком; если проверяющий что-то поправит молча, в отчёте будет
        написано «всё хорошо», а правки не будет нигде.
        """
        config = replace(self.config, access=AccessLevel.READ,
                         max_steps=VERIFY_STEPS)
        guard = make_guard(config)
        guard.set_workspace(str(self.base), None)
        agent = Agent(self.worker.selector, guard, config,
                      on_event=lambda event: self._on_part_event("проверка",
                                                                event))
        agent.trace_on = False
        account = slot_account(slot.gateway, slot.key)
        caller = AutoCaller(self.worker.selector, timeout=self.config.step_timeout,
                            empty_retries=1)
        caller.pinned = slot.ref
        caller.pinned_key = slot.key
        agent.caller = PacedCaller(caller, self.pacer, account, slot.rpm)
        return agent

    def checker_prompt(self, batch: list[Any]) -> str:
        """Задание проверяющему на его долю частей.

        Ответ запрашивается коротким и построчным: сборщику нужны не отчёты
        о работе, а список того, что не так. Длинные объяснения здесь
        возвращаются в сборку целиком и съедают ровно то время, которое
        проверка должна была сэкономить.
        """
        rows = []
        for part in batch:
            files = ", ".join(part.files) or "(файлы не названы)"
            rows.append(f"- {part.name}: {part.brief} — ждём: {files}")
        return (
            "Проверь чужую работу. Ничего не правь, только посмотри.\n\n"
            "Части и их файлы:\n" + "\n".join(rows) + "\n\n"
            "Для каждой строки открой её файлы и ответь одной строкой:\n"
            "  <имя части>: ГОТОВО — если файлы есть и в них есть то, что "
            "просили;\n"
            "  <имя части>: ПРОБЛЕМА — <что не так> — если файла нет, он "
            "пустой или там заглушка вместо работы.\n"
            "Больше ничего не пиши: ни объяснений, ни похвалы, ни кода."
        )

    async def check_one(self, batch: list[Any], slot: Slot,
                        index: int) -> dict[str, str]:
        """Одна доля частей на одном проверяющем."""
        out: dict[str, str] = {}
        try:
            agent = self.make_checker(slot)
            agent.set_task(self.checker_prompt(batch))
            got = await agent.run()
            text = str(got.get("last") or "").strip()
            for part in batch:
                out[part.name] = _verdict_for(text, part)
        except Exception as exc:  # noqa: BLE001
            # Проверка не прошла — это не повод останавливать сборку. Сборщик
            # получит пометку и посмотрит сам, а не будет считать часть
            # проверенной, потому что проверить её не вышло.
            note = f"проверка не прошла ({type(exc).__name__}: {exc})"
            for part in batch:
                out[part.name] = note
        return out

    async def verify(self) -> dict[str, str]:
        """Проверить готовые части несколькими проверяющими сразу.

        Что здесь параллелится и почему именно это. Проверка частей
        независима: каждая смотрит свои файлы и ничего не решает. Сборка
        общих файлов и ответ человеку — не независима: один файл и один
        ответ пишутся целиком, и два сборщика не сделают это быстрее, а
        каждый прочитает всё заново и потратит на это вдвое больше.

        Поэтому проверяющих несколько, сборщик один и получает их короткие
        вердикты вместо сырых отчётов частей. Замер 06.10.2026: сборка была
        14 запросами из 44 на прогоне, то есть треть времени уходила на то,
        чтобы главный агент сам перечитывал всё сделанное.
        """
        swarm = self.swarm
        if swarm is None:
            return {}
        ready = [p for p in self.parts
                 if p.name in swarm.done or p.name in swarm.failed]
        if len(ready) < VERIFY_MIN_PARTS:
            # Проверять одну-две части дороже, чем сборщик посмотрит их сам.
            return {}

        # Слоты рабочих к этому моменту свободны: части закончились. Резерв
        # не трогается — он нужен на случай, если сборщик сам упрётся.
        free = [s for s in swarm.plan.workers if not s.taken_by]
        if not free:
            return {}

        batches = _split_evenly(ready, min(len(free), MAX_CHECKERS))
        started = time.perf_counter()
        results = await asyncio.gather(
            *(self.check_one(batch, free[i], i) for i, batch
              in enumerate(batches)),
            return_exceptions=True)
        verdicts: dict[str, str] = {}
        for got in results:
            if isinstance(got, dict):
                verdicts.update(got)

        self.emit({"type": "swarm_verified", "task_id": self.task_id,
                   "checked": len(verdicts), "checkers": len(batches),
                   "elapsed_ms": int((time.perf_counter() - started) * 1000),
                   "problems": [name for name, text in verdicts.items()
                                if _mark_of(text) == "ПРОБЛЕМА"],
                   "unknown": [name for name, text in verdicts.items()
                               if not _mark_of(text)]})
        return verdicts

    # -------------------------------------------------------------- запуск

    async def run(self) -> dict[str, Any]:
        denied = denied_for_all(self.parts, self.base)
        globs = globs_for_all(self.parts)
        plan = self.build_plan()
        started = time.perf_counter()

        await self.start_parts(plan, denied, globs)
        await self.supervise(denied, globs)
        await self.wait_parts()

        # Проверка идёт после частей и до сборки: сборщик получает вердикты
        # вместо сырых отчётов, и его работа сжимается до общих файлов и
        # ответа. Сами проверки параллельны, поэтому время роя почти не
        # растёт, а перечитывания исчезают.
        verdicts = await self.verify()

        elapsed = int((time.perf_counter() - started) * 1000)
        ok = sum(1 for r in self.results.values() if r["ok"])
        self.emit({
            "type": "swarm_done", "task_id": self.task_id,
            "parts": len(self.parts), "ok": ok, "elapsed_ms": elapsed,
            "reserve": len(plan.reserve),
            "handoffs": dict(self.swarm.handoffs) if self.swarm else {},
            "requests": self.pacer.report(),
            "verified": len(verdicts),
        })
        self.verdicts = verdicts
        return {"parts": len(self.parts), "ok": ok, "elapsed_ms": elapsed,
                "reserve": len(plan.reserve), "verified": len(verdicts)}


def _worth_handoff(reason: str, steps: int = 1) -> bool:
    """Стоит ли подменять аккаунт.

    Подмена чинит то, что связано с аккаунтом: кончился лимит, сеть, ключ
    отклонён. Она не чинит то, что связано с моделью или задачей: модель
    не вызвала инструмент, ответ не распарсился, контекст не влез. Второе
    означало бы потратить резервный аккаунт на заведомо повторяющийся
    результат — и не осталось бы ничего на настоящую подмену.

    Отдельно разобран обрыв без единого шага. Чаще всего это оборванный
    запрос: сети нет, ключ отвергнут, провайдер не ответил. Никакого текста
    об этом не остаётся, и по одному тексту такой отказ отличить нельзя —
    а по числу шагов можно: шагов нет, значит и дела не было, а значит есть
    что продолжать с нуля на другом аккаунте.

    Часть, которая отработала шаги и просто не успела, подмены не
    получает: новый аккаунт даст тот же самый лимит шагов и тот же самый
    обрыв. Резерв на это тратить незачем.
    """
    text = (reason or "").lower()
    signs = ("429", "лимит", "rate limit", "карантин", "недоступн",
             "сеть", "таймаут", "timeout", "503", "502", "504",
             "401", "403", "ключ отклонён", "connection", "прерван")
    if any(sign in text for sign in signs):
        return True
    if steps <= 0:
        # Ни одного шага: дело не в том, что модель сделала.
        return True
    if not text.strip():
        # Причина неизвестна, но работа шла. Скорее всего кончились шаги.
        return False
    return False