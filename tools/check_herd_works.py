#!/usr/bin/env python
"""Рой на настоящих моделях: работает ли он быстрее и не врёт ли про аккаунты.

Зачем это, когда есть `check_agent_works.py`. Тот отвечает на вопрос «умеет ли
модель работать агентом». Этот — на вопросы, которые важны именно для роя и
которые нельзя увидеть на заглушках:

* **действительно ли части идут на разных аккаунтах.** Главное утверждение роя.
  Ротация по кругу раздала бы двум частям один ключ, и это выглядело бы
  исправно, пока части не упрутся в лимит;
* **действительно ли держится темп.** Ограничитель на заглушке всегда
  «работает», потому что заглушка не отвечает провайдеру;
* **быстрее ли он обычного режима** на той же задаче. Если нет, то весь рой —
  лишние запросы и лишний риск;
* **выполняет ли он задачу** — проверяется по файлам на диске, как и в
  `check_agent_works.py`, а не по словам модели.

**Инструмент не выдумывает успех.** Провайдер отвечает мгновенно на любой
запрос, а не на тот, который нужен. Если части не сделали работу, в таблице
будет «не сделала», даже если части отчитались «готово».

**Подмена проверяется честно.** Один аккаунт намеренно портится: в его слот
кладётся ключ, который не пройдёт. Это не проверка «механизм работает» — это
проверка того, что на живых моделях отказ действительно приводит к подмене и
часть докачивается на резервном аккаунте, а не выпадает из задачи.

Запуск:
    .venv\\Scripts\\python.exe tools\\check_herd_works.py
    .venv\\Scripts\\python.exe tools\\check_herd_works.py --pages 4 --steps 8
    .venv\\Scripts\\python.exe tools\\check_herd_works.py --break 1
    .venv\\Scripts\\python.exe tools\\check_herd_works.py --json tmp/herd.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from hub.agent import Agent, AgentConfig, make_guard, selector_from_registry  # noqa: E402
from hub.autonomy import AccessLevel, Autonomy  # noqa: E402
from hub.config import load_gateways  # noqa: E402
from hub.keyring import REGISTRY  # noqa: E402
from hub.registry import collect  # noqa: E402
from hub.worker import Worker  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: Задача намеренно распадается на независимые куски: страницы не знают друг
#: о друге, и это единственное условие, при котором рой имеет смысл.
#:
#: Сделать из неё одну страницу с одним файлом нельзя: тогда рой разбиение
#: сделает вхолостую, и замер будет измерять не рой.
def task_text(pages: int) -> str:
    lines = [f"Сделай сайт из {pages} страниц в текущей папке."]
    lines.append(f"Страницы: {', '.join(f'page{i}.html' for i in range(1, pages + 1))}.")
    lines.append("Каждая страница — отдельный файл со своим заголовком <h1>.")
    lines.append("Общие стили вынеси в style.css.")
    lines.append("Ничего кроме HTML не делай.")
    return " ".join(lines)


class Recorder:
    """Кто ходил, когда и куда. Считается из самого реестра ключей.

    `note_spent` вызывается перед каждым запросом и получает именно тот ключ,
    которым пойдёт запрос. Это единственное место, где видно настоящее
    распределение по аккаунтам: если бы части делили ключ, здесь бы стояло
    одно и то же имя много раз подряд.
    """

    def __init__(self) -> None:
        self.events: list[tuple[float, str, str]] = []
        self.real = REGISTRY.note_spent

    def install(self) -> None:
        outer = self

        def hooked(gateway: dict, key: str) -> None:
            gid = str(gateway.get("id") or "")
            outer.events.append((time.monotonic(), gid, str(key)[-6:]))
            outer.real(gateway, key)

        REGISTRY.note_spent = hooked  # type: ignore[method-assign]

    def remove(self) -> None:
        REGISTRY.note_spent = self.real  # type: ignore[method-assign]

    def per_account(self) -> dict[tuple[str, str], list[float]]:
        out: dict[tuple[str, str], list[float]] = defaultdict(list)
        for stamp, gateway, tail in self.events:
            out[(gateway, tail)].append(stamp)
        return out

    def only(self, accounts: set[tuple[str, str]]) -> "Recorder":
        """Оставить только запросы перечисленных аккаунтов.

        Главный агент работает вне ограничителя роя: он обращается к моделям
        через общий выбор, а не через слоты. Это осознанно — его запросов
        единицы, — но в таблице они смешиваются с запросами частей, и
        ограничение темпа перестаёт быть видно. Разделено, чтобы не
        приписывать ограничителю то, чего он не делал.
        """
        cut = Recorder()
        cut.events = [e for e in self.events if (e[1], e[2]) in accounts]
        return cut

    def busiest(self) -> int:
        """Максимум запросов с одного аккаунта за весь прогон."""
        return max((len(v) for v in self.per_account().values()), default=0)

    def busiest_account(self) -> tuple[str, str] | None:
        rows = self.per_account()
        return max(rows.items(), key=lambda kv: len(kv[1]))[0] if rows else None


def pace_report(rec: Recorder) -> dict[str, Any]:
    """Как распределены запросы по аккаунтам и как выдержан темп."""
    rows = rec.per_account()
    if not rows:
        return {"accounts": 0}
    gaps: list[float] = []
    for stamps in rows.values():
        ordered = sorted(stamps)
        gaps.extend(b - a for a, b in zip(ordered, ordered[1:]))
    gaps.sort()
    return {
        "accounts": len(rows),
        "requests": len(rec.events),
        "max_per_account": max((len(v) for v in rows.values()), default=0),
        "min_gap_s": round(gaps[0], 2) if gaps else 0.0,
        "median_gap_s": round(gaps[len(gaps) // 2], 2) if gaps else 0.0,
        "max_gap_s": round(gaps[-1], 2) if gaps else 0.0,
        "bursty": bool(gaps and gaps[0] < 0.05),
    }


class Bench:
    """Подмена воркера: те же настоящие методы, меньше обвязки.

    Методы `_run_herd`, `_assemble`, `_run_with_images` и `_free_accounts`
    берутся у настоящего `Worker` и вызываются на этом объекте. Это важно:
    замеряется ровно тот код, который работает у человека, а не его копия в
    инструменте. Если метод разойдётся с этим подменой, тесты упадут — но
    замер в любом случае идёт по настоящей копии.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.gateways = load_gateways(root, env={})
        self.registry = None
        self.selector = None
        self.keyring = REGISTRY
        self.events: list[dict[str, Any]] = []
        self._run_herd = Worker._run_herd.__get__(self)
        self._assemble = Worker._assemble.__get__(self)
        self._run_with_images = Worker._run_with_images.__get__(self)
        self._free_accounts = Worker._free_accounts.__get__(self)

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def _attach_images(self, agent: Agent, images: list[Any] | None) -> None:
        return None

    async def boot(self, *, require_tools: bool = True) -> None:
        self.registry = await collect(self.gateways, root=self.root)
        REGISTRY.apply_limits(self.gateways)
        self.selector = selector_from_registry(
            self.registry, mode="auto", manual_ref=None,
            prefer_speed=True, require_vision=False, root=str(self.root),
        )
        # Модели без замера в рое не берутся: поручать часть той, о чём
        # ничего не известно, хуже, чем подождать. Для замера это значит
        # «не выбрана» вместо «выбрана и сразу отвалилась».
        for state in self.selector.states.values():
            if not getattr(state, "avg_ms", 0):
                state.avg_ms = 600
            if getattr(state, "last_status", "") not in ("ok", "slow"):
                state.last_status = "ok"
            state.cooldown_until = 0.0

    def config(self, workdir: Path, steps: int) -> AgentConfig:
        return AgentConfig(
            base_dir=str(workdir),
            access=AccessLevel.FULL,
            autonomy=Autonomy.YOLO,
            max_steps=steps,
            max_tokens=2048,
            step_timeout=120.0,
        )

    def agent(self, config: AgentConfig) -> Agent:
        guard = make_guard(config)
        guard.set_workspace(str(config.base_dir), None)
        return Agent(self.selector, guard, config)


def break_slot(run: Any, index: int) -> str:
    """Испортить ключ у рабочего слота — чтобы отказ был настоящим.

    Ключ подменяется на заведомо нерабочий. Модель после него не ответит, и
    часть вернётся с ошибкой провайдера. Только так проверяется подмена на
    живых моделях: искусственно поставленный `ok=False` не проходит по
    `PacedCaller`, по ограничителю темпа и по настоящему провайдеру.
    """
    plan = getattr(getattr(run, "swarm", None), "plan", None)
    busy = [s for s in (plan.workers if plan else []) if not s.free]
    if index >= len(busy):
        return ""
    slot = busy[index]
    where = f"{slot.gateway}:…{slot.key[-6:]}"
    slot.key = "sk-" + "0" * 48  # отвергнет любой провайдер
    return where


def install_break(run_cls: type, index: int) -> dict[str, str]:
    """Вклиниться между планом и запуском частей.

    Класс правится снаружи и только на время замера: так измеряется настоящий
    `_run_herd`, а не его копия в инструменте. Подмена точечная — один
    слот, — иначе проверка перестала бы проверять подмену, а показывала бы
    «всё упало».

    Возвращается ячейка, а не значение: слот становится известен только в
    момент запуска, то есть уже внутри прогона.
    """
    real = run_cls.start_parts
    state: dict[str, str] = {"where": ""}

    async def hooked(self: Any, plan: Any, denied: Any, globs: Any) -> None:
        state["where"] = break_slot(self, index)
        await real(self, plan, denied, globs)

    run_cls.start_parts = hooked  # type: ignore[method-assign]
    return state


def break_gateway(run: Any, gateway: str) -> list[str]:
    """Уронить провайдера целиком: заблокировать все его аккаунты.

    Один испорченный ключ рой переживает сам: `AutoCaller` роняет закрепление
    и берёт другой ключ того же шлюза, диалог остаётся целым, и подмена даже
    не начинается. Проверить подмену на живых моделях можно только снятием
    всего шлюза — тогда части остаются без аккаунта по-настоящему, и это
    ровно тот случай, для которого резерв и существует.

    Возвращает список аккаунтов, которые были заблокированы.
    """
    plan = getattr(getattr(run, "swarm", None), "plan", None)
    hits = [s for s in (plan.workers if plan else [])
            if s.gateway == gateway and s.key]
    for slot in hits:
        slot.blocked = True
    return [f"{s.gateway}:…{s.key[-6:]}" for s in hits]


def install_gateway_break(run_cls: type, gateway: str) -> dict[str, Any]:
    """Вклиниться между планом и запуском частей.

    Класс правится снаружи и только на время замера: так измеряется настоящий
    `_run_herd`, а не его копия в инструменте.

    Возвращается ячейка, а не значение: слоты известны только в момент
    запуска, то есть уже внутри прогона.
    """
    real = run_cls.start_parts
    state: dict[str, Any] = {"which": [], "note": ""}

    async def hooked(self: Any, plan: Any, denied: Any, globs: Any) -> None:
        which = break_gateway(self, gateway)
        state["which"] = which
        state["note"] = (f"у шлюза {gateway} слотов в работе: {len(which)}"
                         if which else f"у шлюза {gateway} слотов не было")
        # Слоты помечены сломанными; их ключи убираются из выдачи, чтобы
        # failover внутри части тоже не смог обойти отказ.
        for slot in plan.workers + plan.reserve:
            if slot.gateway == gateway and not slot.blocked:
                continue
            if slot.gateway != gateway:
                continue
            slot.key = "sk-" + "0" * 48
        await real(self, plan, denied, globs)

    run_cls.start_parts = hooked  # type: ignore[method-assign]
    return state


def uninstall_break(run_cls: type) -> None:
    """Вернуть настоящий метод: иначе следующий прогон в том же процессе
    будет измерять уже сломанный слот."""
    real = getattr(run_cls, "_real_start_parts", None)
    if real is not None:
        run_cls.start_parts = real  # type: ignore[method-assign]


async def run_herd(bench: Bench, workdir: Path, *, pages: int, steps: int,
                   break_index: int, break_gateway: str = "") -> dict[str, Any]:
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    text = task_text(pages)
    config = bench.config(workdir, steps)
    agent = bench.agent(config)
    agent.set_task(text)

    from hub.swarm_run import SwarmRun

    broke: dict[str, Any] = {"where": ""}
    if break_index >= 0:
        SwarmRun._real_start_parts = SwarmRun.start_parts  # type: ignore[attr-defined]
        broke = install_break(SwarmRun, break_index)
    if break_gateway:
        SwarmRun._real_start_parts = SwarmRun.start_parts  # type: ignore[attr-defined]
        broke = install_gateway_break(SwarmRun, break_gateway)

    recorder = Recorder()
    recorder.install()
    started = time.monotonic()
    result: dict[str, Any] = {}
    info: dict[str, Any] = {}
    note = ""
    try:
        result = await bench._run_herd({"id": 1, "task": text}, agent, config)
        info = dict(result.get("herd") or {})
    except Exception as exc:  # noqa: BLE001
        note = f"{type(exc).__name__}: {exc}"
    finally:
        recorder.remove()
        if break_index >= 0 or break_gateway:
            uninstall_break(SwarmRun)
    elapsed = time.monotonic() - started

    made = sorted(p.name for p in workdir.glob("*") if p.is_file())
    pages_done = [n for n in made if n.startswith("page")]
    kinds = [e.get("type") for e in bench.events]
    plan = next((e.get("plan") or {} for e in bench.events
                 if e.get("type") == "swarm_plan"), {})

    # Темп частей и темп главного агента считаются раздельно. Части стоят
    # на слотах роя и проходят через ограничитель; главный агент — нет.
    worker_accounts = {
        (str(row.get("gateway") or ""), str(row.get("key_tail") or ""))
        for row in list(plan.get("workers") or []) + list(plan.get("reserve") or [])
        if row.get("key_tail")
    }
    parts_pace = pace_report(recorder.only(worker_accounts))

    # По части виден исход: без него «3 из 6» не сказать почему, а именно
    # разбор по частям — то, ради чего прогон делается.
    per_part: list[dict[str, Any]] = []
    for row in info.get("results", {}).values() if isinstance(
            info.get("results"), dict) else []:
        per_part.append(row)

    return {
        "mode": "рой",
        "ok_parts": int(info.get("ok") or 0),
        "parts": int(info.get("parts") or 0),
        "reserve": int(info.get("reserve") or 0),
        "handoffs": info.get("handoffs") or {},
        "seconds": round(elapsed, 1),
        "pages_made": len(pages_done),
        "pages_want": pages,
        "files": made,
        "breached": bool(parts_pace.get("bursty")),
        "pace": parts_pace,
        "all_pace": pace_report(recorder),
        "plan": plan,
        "broke": broke.get("where", ""),
        "broke_note": broke.get("note", ""),
        "note": note,
        "kinds": sorted(set(k for k in kinds if k)),
        "per_part": per_part,
        "handoff_events": [
            {"sub": e.get("sub"), "from": e.get("from"), "to": e.get("to"),
             "reason": e.get("reason")}
            for e in bench.events if e.get("type") == "swarm_handoff"
        ],
        "answer": str(result.get("last") or "")[:400],
    }


async def run_plain(bench: Bench, workdir: Path, *, pages: int,
                    steps: int) -> dict[str, Any]:
    """Тот же агент, тот же вопрос, но без роя. С чем сравнивать.

    Запускается отдельным процессом, а не вторым прогоном в том же. Иначе
    сравнение врёт дважды: кольцо ключей помнит расход роя и отдаёт обычному
    режиму пустые аккаунты, а селектор — покалеченные модели. Тогда обычный
    режим возвращается с нулём шагов за ноль секунд и выглядит как
    «сорвался», хотя сорвался не он.

    Бюджет шагов — сумма шагов всех частей роя, а не бюджет одной части.
    Иначе сравнение бессмысленно: обычному режиму выдают на шесть страниц
    столько же попыток, сколько одной части роя, он честно не успевает и
    проигрывает не по скорости работы, а по несправедливости.
    """
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    text = task_text(pages)
    config = bench.config(workdir, steps)
    agent = bench.agent(config)
    agent.set_task(text)

    recorder = Recorder()
    recorder.install()
    started = time.monotonic()
    try:
        await agent.run()
    finally:
        recorder.remove()
    elapsed = time.monotonic() - started

    made = sorted(p.name for p in workdir.glob("*") if p.is_file())
    return {
        "mode": "обычный",
        "seconds": round(elapsed, 1),
        "pages_made": len([n for n in made if n.startswith("page")]),
        "pages_want": pages,
        "files": made,
        "requests": len(recorder.events),
    }


def report(rows: list[dict[str, Any]]) -> str:
    out: list[str] = []
    out.append("режим    части  готово  страниц  время  с  запросов  аккаунтов")
    out.append("-" * 62)
    for row in rows:
        out.append(
            f"{row['mode']:<8} {row.get('parts', '-'):>4}  {row.get('ok_parts', '-'):>5}"
            f"  {row.get('pages_made', 0):>5}/{row['pages_want']:<3}"
            f"  {row['seconds']:>5} с  {row.get('requests', row.get('pace', {}).get('requests', '-')):>2}"
            f"  {row.get('pace', {}).get('accounts', 1):>2}")
    return "\n".join(out)


async def pace_probe(rpm: int = 20, take: int = 10) -> dict[str, Any]:
    """Проверить ограничитель темпа отдельно от моделей.

    Живой прогон показал, что при пяти запросах на часть «короткий разбег»
    покрывает почти всё, и ограничитель не срабатывает. Это не дефект: пять
    запросов от аккаунта никто не посчитает злоупотреблением. Но из этого
    следует, что замер роя ничего не доказывает о темпе — доказать его может
    только сам ограничитель под нагрузкой.

    Модели здесь не нужны: измеряется время между разрешениями выдать
    запрос, а не сами запросы. Проверка бесплатна и повторяема.
    """
    from hub.pacer import BURST, Pacer

    pacer = Pacer()
    pacer.set_rpm("probe:k0", rpm)
    marks: list[float] = []

    async def scenario() -> None:
        for _ in range(take):
            await pacer.acquire("probe:k0")
            marks.append(time.monotonic())

    started = time.monotonic()
    await scenario()
    elapsed = time.monotonic() - started
    gaps = [round(b - a, 2) for a, b in zip(marks, marks[1:])]
    expect_gap = 60.0 / rpm
    # Разбег — это и есть его назначение, а не ошибка. Проверяются только
    # интервалы после него: там темп обязан держаться по лимиту. Иначе
    # проверка ругалась бы на то, что ограничитель делает правильно.
    after = gaps[BURST - 1:] if len(gaps) >= BURST else []
    steady = [g for g in after if g > 0]
    slowest_steady = min(steady, default=0.0)
    return {
        "rpm": rpm, "took": take, "burst": BURST,
        "elapsed_s": round(elapsed, 2),
        "gaps": gaps,
        "expected_gap_s": round(expect_gap, 2),
        "steady_from_s": after[0] if after else 0,
        "ok": bool(after and slowest_steady >= expect_gap * 0.8),
        "note": ("разбег не прошёл, всё ушло быстрее лимита — "
                 "ограничитель не сработал" if not after else ""),
    }


async def main_async(args: argparse.Namespace) -> int:
    if args.mode == "plain":
        return await main_plain(args)
    return await main_herd(args)


async def main_plain(args: argparse.Namespace) -> int:
    """Обычный режим отдельным процессом — см. объяснение в `run_plain`."""
    bench = Bench(ROOT)
    await bench.boot()
    work = Path(args.work or (ROOT / "tmp" / "herd-plain"))
    plain = await run_plain(bench, work, pages=args.pages, steps=args.steps)
    plain["budget_steps"] = args.steps
    print(f"обычный режим: {plain['pages_made']} из {args.pages} страниц за "
          f"{plain['seconds']} с, запросов {plain['requests']}, "
          f"лимит шагов {args.steps}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({"rows": [plain]},
                                              ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"записано: {args.json}")
    return 0


async def main_herd(args: argparse.Namespace) -> int:
    bench = Bench(ROOT)
    if args.pace_only:
        probe = await pace_probe()
        print(f"ограничитель: {probe['rpm']} запросов в минуту, "
              f"разбег {probe['burst']}")
        print(f"интервалы, с: {probe['gaps']}")
        print(f"первый настоящий интервал после разбега: {probe['steady_from_s']} с, "
              f"ждать надо было ~{probe['expected_gap_s']} с")
        print(f"вышло {probe['elapsed_s']} с — {'верно' if probe['ok'] else 'НЕВЕРНО'}")
        if probe["note"]:
            print(f"замечание: {probe['note']}")
        return 0 if probe["ok"] else 1

    await bench.boot()
    if bench.selector is None:
        print("реестр моделей не загрузился")
        return 1

    free = sum(int(s.get("available") or 0)
               for s in REGISTRY.snapshot().values())
    print(f"свободных аккаунтов: {free}")

    out: dict[str, Any] = {"pages": args.pages, "steps": args.steps,
                           "rows": []}

    work = Path(args.work or (ROOT / "tmp" / "herd-run"))
    herd = await run_herd(bench, work, pages=args.pages, steps=args.steps,
                          break_index=args.break_slot,
                          break_gateway=args.break_gateway)
    out["rows"].append(herd)

    if args.compare:
        # Сравнение — отдельный процесс: см. объяснение в `run_plain`.
        plain_json = Path(str(args.json or "tmp/herd_plain.json"))
        budget = max(args.steps, args.steps * max(1, herd["parts"]))
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--mode", "plain",
             "--pages", str(args.pages), "--steps", str(budget),
             "--json", str(plain_json)],
            check=False)
        if plain_json.is_file():
            plain = json.loads(plain_json.read_text(encoding="utf-8"))["rows"][0]
            plain["budget_steps"] = budget
            out["rows"].append(plain)
            if plain["seconds"] > 0:
                out["speedup"] = round(plain["seconds"] / max(herd["seconds"], 0.1), 2)

    print(report(out["rows"]))
    print()
    print(f"всего запросов на прогон: {herd['all_pace'].get('requests', 0)} по "
          f"{herd['all_pace'].get('accounts', 0)} аккаунтам")
    print(f"из них запросы частей (через ограничитель): "
          f"{herd['pace'].get('requests', 0)} по "
          f"{herd['pace'].get('accounts', 0)} слотам, больше всего на одном — "
          f"{herd['pace'].get('max_per_account', 0)}")
    print(f"частый интервал между запросами одной части: "
          f"{herd['pace'].get('min_gap_s', 0)} с "
          f"(медиана {herd['pace'].get('median_gap_s', 0)} с)")
    print("остальное — главный агент: он ходит через общий выбор моделей, "
          "ограничителем роя не проходит, его запросов единицы")
    if herd["breached"]:
        print("ВНИМАНИЕ: запросы частей шли пачкой — рой выглядит как автоматизация")
    if herd["handoffs"]:
        print(f"подмены: {herd['handoffs']}")
    if herd["broke_note"]:
        print(f"подготовка отказа: {herd['broke_note']}")
    if herd["broke"]:
        print(f"намеренно испорчены аккаунты: {herd['broke']}")
    if herd["note"]:
        print(f"прогон прервался: {herd['note']}")
    print(f"страниц на диске: {herd['pages_made']} из {herd['pages_want']}")
    if "speedup" in out:
        plain = out["rows"][1]
        print(f"обычный режим (отдельный процесс, {plain.get('budget_steps')} шагов): "
              f"{plain['pages_made']} из {args.pages} страниц за "
              f"{plain['seconds']} с")
        print(f"ускорение против обычного режима: ×{out['speedup']}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"записано: {args.json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Замер роя на настоящих моделях")
    parser.add_argument("--pages", type=int, default=4,
                        help="сколько страниц в задаче")
    parser.add_argument("--steps", type=int, default=8,
                        help="шагов на часть и на главного агента")
    parser.add_argument("--compare", action="store_true",
                        help="дополнительно прогнать обычный режим")
    parser.add_argument("--break-slot", type=int, default=-1,
                        help="испортить ключ у этого рабочего (с нуля)")
    parser.add_argument("--break-gateway", default="",
                        help="уронить шлюз целиком (id из config/gateways.json)")
    parser.add_argument("--work", default="", help="папка для результата")
    parser.add_argument("--pace-only", action="store_true",
                        help="проверить только ограничитель темпа, без моделей")
    parser.add_argument("--mode", choices=("herd", "plain"), default="herd",
                        help="что именно прогонять")
    parser.add_argument("--json", default="", help="куда записать отчёт")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())