"""Запуск роя: планирование, параллельная работа, подмена, сборка.

Отдельно от `hub/swarm.py`, где живут план и правила, потому что здесь
единственное место, где встречаются агент, `Guard` и очередь задач. План
можно проверить без сети и без агента, а здесь — нельзя.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from hub.agent import Agent, AgentConfig, make_guard
from hub.failover import AutoCaller
from hub.pacer import PacedCaller, Pacer
from hub.swarm import (
    PARTIAL_EVERY_S,
    PARTIAL_STEPS,
    STAGGER_S,
    TAIL_PARTS,
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


def files_ready(part: Any, base: Path) -> list[str]:
    """Какие файлы части появились на диске.

    Часть объявляет свои файлы при разбиении — иногда точно (`index.html`),
    иногда маской (`src/*.js`). И то и другое раскрывается на настоящем
    диске: иначе пришлось бы верить модели на слово, а модель может написать
    «готово» и ничего не создать.
    """
    out: list[str] = []
    for raw in getattr(part, "files", None) or []:
        rel = str(raw).strip().lstrip("./")
        if not rel:
            continue
        target = base / rel
        try:
            if any(ch in rel for ch in "*?["):
                out.extend(str(p.relative_to(base).as_posix())
                           for p in sorted(base.glob(rel))
                           if p.is_file())
            elif target.is_file() and target.stat().st_size:
                out.append(rel)
        except (OSError, ValueError):
            continue
    return out


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

        part_agent = Agent(
            self.worker.selector, guard, self.config,
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
        made = files_ready(part, self.base)
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
        index_of = {p.name: i for i, p in enumerate(self.parts)}
        for part in self.parts:
            slot = None
            for candidate in plan.workers:
                if candidate.taken_by == part.name:
                    slot = candidate
                    break
            if slot is None:
                continue
            self.asyncio_tasks[part.name] = asyncio.create_task(
                self.run_part(part, index_of[part.name], slot, denied, globs))

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

        Лимит ставится на конфиг и снимается сразу после: агент читает его в
        каждом шаге, а менять настройку навсегда нельзя — после сборки у
        главного агента должен остаться его обычный бюджет.
        """
        saved = self.config.max_steps
        try:
            self.config.max_steps = min(saved, max(1, limit))
            return await self.agent.run()
        finally:
            self.config.max_steps = saved

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

    # -------------------------------------------------------------- запуск

    async def run(self) -> dict[str, Any]:
        denied = denied_for_all(self.parts, self.base)
        globs = globs_for_all(self.parts)
        plan = self.build_plan()
        started = time.perf_counter()

        await self.start_parts(plan, denied, globs)
        await self.supervise(denied, globs)
        await self.wait_parts()

        elapsed = int((time.perf_counter() - started) * 1000)
        ok = sum(1 for r in self.results.values() if r["ok"])
        self.emit({
            "type": "swarm_done", "task_id": self.task_id,
            "parts": len(self.parts), "ok": ok, "elapsed_ms": elapsed,
            "reserve": len(plan.reserve),
            "handoffs": dict(self.swarm.handoffs) if self.swarm else {},
            "requests": self.pacer.report(),
        })
        return {"parts": len(self.parts), "ok": ok, "elapsed_ms": elapsed,
                "reserve": len(plan.reserve)}


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