#!/usr/bin/env python
"""Кто из моделей действительно работает агентом: замер на настоящей задаче.

Зачем это, когда уже есть `check_tool_models.py`. Тот спрашивает «умеет ли
модель напечатать вызов инструмента в правильном формате». Это вопрос про
формат. А агент работает с другим: он должен, получив задачу и каталог из
шести инструментов, **сам дойти до вызова**, **создать файл** и **сказать об
этом**. Между «печатает JSON» и «делает» расстояние огромное, и проверка
формата его не проходит.

Поэтому здесь настоящий агент, настоящий Guard, настоящая папка и проверка
результата на диске. Модели отвечают на одинаковую задачу по очереди, у
каждой своя папка, чтобы не мешать друг другу.

**Задача намеренно маленькая.** Задача на двадцать шагов измеряет не модель,
а терпение: одна справится, другая не дойдёт до конца просто из-за размера, и
сравнение станет бессмысленным. Здесь важен факт «создал файл с нужным
содержимым», а он проверяется однозначно.

**Вердикт только из файла.** Что модель написала в ответе текстом — не
показатель: она может сказать «готово» и ничего не сделать. Файл либо есть и
содержит ожидаемое, либо нет. Иначе самый убедительный способ испортить
замер — поверить модели на слово.

**Причины неудачи разделены.** «Не сделала из-за лимита аккаунта» и «не
умеет вызывать инструмент» — разные вещи. Первое пройдёт само, второе надо
убирать из ротации. Сводить их к «модель плохая» нельзя, иначе из вывода
следует вывод, которого не делали.

Замер сделан 06.10.2026, результаты — `docs/model-works.md`.

Запуск:
    .venv\\Scripts\\python.exe tools\\check_agent_works.py
    .venv\\Scripts\\python.exe tools\\check_agent_works.py --model groq/qwen/qwen3.8-27b
    .venv\\Scripts\\python.exe tools\\check_agent_works.py --gateways nvidia --steps 6
    .venv\\Scripts\\python.exe tools\\check_agent_works.py --json tmp/agent_works.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from hub.agent import Agent, AgentConfig, make_guard, selector_from_registry  # noqa: E402
from hub.autonomy import AccessLevel, Autonomy  # noqa: E402
from hub.config import load_gateways  # noqa: E402
from hub.failover import AutoCaller  # noqa: E402
from hub.keyring import REGISTRY  # noqa: E402
from hub.registry import collect  # noqa: E402
from hub.select import Mode  # noqa: E402

TASK = "Создай файл hello.txt в текущей папке с единственной строкой: Привет"

#: Что должно оказаться в файле. Сравнение без учёта регистра и лишних
#: пробелов: агент вправе добавить перевод строки в конце, и требовать
#: побайтового совпадения было бы требованием к формату, а не к работе.
EXPECT = "привет"

#: Шагов хватает на задачу с запасом и не хватает на бесконечное топтание.
MAX_STEPS = 6

#: Причины, по которым задача не выполнена, и что с каждой делать.
#:
#: Ключи — подстроки текста ошибки от провайдера, значения — вывод, который
#: по этой причине делать можно. Порядок важен: сначала более специфичные
#: причины, потом общая «лимит». Код ответа у всех один и тот же (429), и
#: разбирать приходится по тексту.
WHY_TOO_LARGE = ("request too large", "context length", "too long",
                 "maximum context")
WHY_NO_TOOL = ("tool choice is none", "tool_call_not_available")
WHY_LIMIT = ("429", "лимит запросов", "rate limit")
WHY_OFFLINE = ("недоступны", "в карантине", "прерван", "502", "503", "504")


def _why(note: str) -> str:
    """Разобрать причину неудачи по тексту провайдера."""
    text = (note or "").lower()
    if any(mark in text for mark in WHY_TOO_LARGE):
        return ("промпт не влез в контекст — лечится сокращением промпта, "
                "а не заменой модели")
    if any(mark in text for mark in WHY_NO_TOOL):
        return "провайдер запретил вызов инструмента — модель не умеет действовать"
    if any(mark in text for mark in WHY_LIMIT):
        return "лимит у аккаунта — модель тут ни при чём, попробовать позже"
    if any(mark in text for mark in WHY_OFFLINE):
        return "модель упала или ушла в карантин после первого отказа"
    return ""


def _resolve_ref(selector, ref: str) -> str:
    """Найти в реестре модель по тому, как её назвал человек.

    У части провайдеров идентификатор модели сам начинается с имени шлюза
    (`nvidia/nemotron-…`), а ref в реестре добавляет префикс ещё раз, и
    получается `nvidia/nvidia/nemotron-…`. На выбор модели это не влияет, но
    вводить модель по имени руками неудобно.

    Сначала точное совпадение, потом — с префиксом шлюза, потом — по хвосту
    имени. Пустой результат означает «нет в реестре», и это честнее, чем
    молча проверить не ту модель.
    """
    ref = str(ref or "").strip()
    if ref in selector.states:
        return ref
    gateway = ref.split("/", 1)[0]
    prefixed = f"{gateway}/{ref}"
    if prefixed in selector.states:
        return prefixed
    tail = ref.rsplit("/", 1)[-1]
    near = [r for r in selector.states if r.rsplit("/", 1)[-1] == tail]
    if len(near) == 1:
        return near[0]
    if near:
        raise ValueError(
            "модель названа неоднозначно: " + ", ".join(near[:4])
            + " — укажите с префиксом шлюза")
    return ""


def _run_bounded(agent: Agent, limit: int) -> None:
    """Ограничить агента числом шагов снаружи.

    Общий таймаут на все модели ставить нельзя: у медленной модели он
    истечёт на первом шаге, и в таблице будет «не уложилась» вместо «не
    смогла». Здесь считаются шаги, и каждый получает ровно столько попыток.
    """

    async def run() -> dict[str, Any]:
        while len(agent.steps) < limit and not agent.finished:
            await agent._one_step()
        return {
            "ok": agent.finished,
            "steps": len(agent.steps),
            "tools_used": [s.tool for s in agent.steps if s.tool],
        }

    agent.run = run  # type: ignore[method-assign]


async def run_one(selector, ref: str, *, timeout: float,
                  workdir: Path, steps: int) -> dict[str, Any]:
    """Одна модель на настоящей задаче. Вердикт — из файла."""
    # Папка своя у каждой модели: иначе первая создаст файл, а остальные
    # получат «готово» просто потому, что файл уже на месте.
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        ref = _resolve_ref(selector, ref)
    except ValueError as exc:
        return _blank(ref, "неоднозначно", str(exc))
    state = selector.states.get(ref)
    if state is None:
        return _blank(ref, "нет в реестре", "модель не найдена в реестре")

    # Состояние модели тоже снимается: у свежего селектора avg_ms равен нулю,
    # а нулевая задержка читается как «есть замер, и он мгновенный». Раньше
    # из-за этого все модели выпадали из выдачи ещё до первого запроса, и
    # замер показывал «все модели недоступны» вместо результата.
    if not state.avg_ms:
        state.avg_ms = 500
    # `blocked` — вычисляемое свойство, присваивать его нельзя: состояние
    # чинится через last_status и cooldown_until, как это делает сам селектор
    # после успешного ответа.
    if state.last_status not in ("ok", "slow"):
        state.last_status = "ok"
    state.cooldown_until = 0.0
    state.fails = 0

    # Ручной режим: агент не переключится на другую модель, и в таблице
    # будет честно, кто именно не справился. Иначе «модель не работает»
    # означало бы «модель не работает, но переключился на соседнюю».
    selector.mode = Mode.MANUAL
    selector.manual_ref = ref

    config = AgentConfig(
        base_dir=str(workdir),
        access=AccessLevel.FULL,
        autonomy=Autonomy.YOLO,
        max_steps=steps,
        max_tokens=2048,
        step_timeout=timeout,
    )
    guard = make_guard(config)
    guard.set_workspace(str(workdir), None)

    agent = Agent(selector, guard, config,
                  caller=AutoCaller(selector, manual_only=True, timeout=timeout))
    _run_bounded(agent, steps)
    agent.set_task(TASK)

    loop = asyncio.get_running_loop()
    started = loop.time()
    count = 0
    used: list[str] = []
    note = ""
    try:
        got = await agent.run()
        count = int(got.get("steps") or 0)
        used = [str(t) for t in (got.get("tools_used") or []) if t]
    except Exception as exc:  # noqa: BLE001
        note = f"{type(exc).__name__}: {exc}"
        count = len(agent.steps)
        used = [s.tool for s in agent.steps if s.tool]

    # Причина неудачи берётся из первого шага с ошибкой, а не из
    # последнего: после первого отказа все следующие шаги повторяют «все
    # модели недоступны», и по последнему шагу причина читалась бы как «агент
    # сломан».
    first_error = next((s.error for s in agent.steps if s.error), note)
    result: dict[str, Any] = {
        "ref": ref, "ok": False, "verdict": "ошибка",
        "note": first_error or note,
        "why": _why(first_error or note),
        "steps": count, "tools": used,
        "seconds": round(loop.time() - started, 1),
        "wrote": None,
    }

    # Вердикт ставится по файлу. Ответ модели в счёт не идёт: сказать
    # «готово» можно и ничего не сделав, и именно это отличает «работает»
    # от «говорит, что работает».
    target = workdir / "hello.txt"
    if target.is_file():
        body = target.read_text(encoding="utf-8", errors="replace").strip().lower()
        result["wrote"] = body[:120]
        result["why"] = ""
        if EXPECT in body:
            result.update(ok=True, verdict="сделала", note=body[:60])
        else:
            result.update(verdict="не то", note=f"в файле: {body[:60]!r}")
    elif not result["why"]:
        # Отдельный случай, который легко пропустить: модель могла создать
        # файл с другим именем. Это уже частичная работа, и счёт «не
        # сделала» был бы несправедлив — смотрим, что появилось вообще.
        made = sorted(p.name for p in workdir.glob("*"))
        result.update(
            verdict="не сделала",
            why=("модель ответила текстом, но инструмент не вызвала"
                 if not used else
                 "инструменты вызывала, но нужного файла не создала"),
            note=f"файла нет; вызвала: {', '.join(used) or 'ни одного'}; "
                 f"в папке: {', '.join(made) or 'пусто'}")
    else:
        # «Не по её вине» только когда виноват аккаунт. Промпт не влез —
        # это вина измерения, а не модели, и называть так нельзя: причина
        # лечится сокращением промпта, а заменой модели — нет.
        result["verdict"] = ("не по её вине" if "лимит у аккаунта" in result["why"]
                             else "не смогла")
    return result


def _blank(ref: str, verdict: str, note: str) -> dict[str, Any]:
    return {"ref": ref, "ok": False, "verdict": verdict, "note": note,
            "why": "", "steps": 0, "tools": [], "seconds": 0.0, "wrote": None}


def _write_markdown(results: list[dict[str, Any]], path: Path) -> None:
    """Выгрузить замер так, чтобы его можно было прочитать и в гит."""
    ok = sorted([r for r in results if r["ok"]], key=lambda r: r["seconds"])
    bad_by_why: dict[str, list[str]] = {}
    for r in results:
        if not r["ok"]:
            bad_by_why.setdefault(r.get("why") or "причина неясна", []).append(r["ref"])

    lines = [
        "# Кто из моделей работает агентом",
        "",
        "Замер настоящего агента на настоящей задаче: создать файл с заданным",
        "содержимым. Вердикт ставится по файлу на диске, а не по тому, что модель",
        "написала в ответе: сказать «готово» можно и ничего не сделав.",
        "",
        f"Задача: `{TASK}`",
        "",
        f"Измерено {len(results)} моделей, выполнили {len(ok)}.",
        "",
        "## Выполнили",
        "",
        "| Модель | Секунд | Шагов | Инструменты |",
        "|---|---|---|---|",
    ]
    for r in ok:
        lines.append(f"| `{r['ref']}` | {r['seconds']} | {r['steps']} | "
                     f"{', '.join(r['tools']) or '—'} |")

    lines += ["", "## Не выполнили", ""]
    if not bad_by_why:
        lines.append("Неудачных нет.")
    for why, refs in sorted(bad_by_why.items(), key=lambda kv: -len(kv[1])):
        lines += [f"**{why}** ({len(refs)})", ""]
        lines += [f"- `{ref}`" for ref in refs]
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Замер моделей на настоящей задаче агента.")
    parser.add_argument("--model", help="одна модель по ref")
    parser.add_argument("--gateways", help="только эти шлюзы через запятую")
    parser.add_argument("--limit", type=int, default=0, help="первые N моделей")
    parser.add_argument("--timeout", type=float, default=90.0,
                        help="таймаут одного запроса к модели, сек")
    parser.add_argument("--steps", type=int, default=MAX_STEPS,
                        help=f"шагов на модель (по умолчанию {MAX_STEPS})")
    parser.add_argument("--json", help="выгрузить результаты в JSON")
    parser.add_argument("--markdown", help="выгрузить сводку в Markdown")
    parser.add_argument("--keep", action="store_true",
                        help="не удалять папки с результатами работ")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    gateways = load_gateways(root, env={})
    # Лимиты — до первого запроса: иначе замер сам станет причиной отказа.
    REGISTRY.apply_limits(gateways)
    registry = await collect(gateways, root=root)
    selector = selector_from_registry(registry, mode="auto", root=str(root))

    if args.model:
        refs = [args.model]
    elif args.gateways:
        wanted = set(args.gateways.split(","))
        refs = [ref for ref in selector.states
                if ref.split("/", 1)[0] in wanted]
    else:
        # Все модели реестра, а не только измеренные: у свежего запуска
        # замеров ещё нет вовсе, и фильтр «только с avg_ms» молча оставлял
        # ноль моделей — замер не выполнялся, а выглядел как «все не
        # справились». Порядок — по рангу из tiers.json: сначала те, кому
        # агент доверится первыми, чтобы ограничение по числу отсекало худших.
        refs = sorted(selector.states,
                      key=lambda r: (selector.states[r].tier,
                                     selector.states[r].avg_ms))
    if args.limit:
        refs = refs[:args.limit]

    print(f"Задача: {TASK}")
    print(f"Модели к проверке: {len(refs)}")
    print(f"Шагов на модель: {args.steps}\n")
    if not refs:
        print("Нет моделей к проверке. Проверьте --gateways или --model.")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="zagent-works-"))
    results: list[dict[str, Any]] = []
    try:
        for index, ref in enumerate(refs, start=1):
            got = await run_one(selector, ref, timeout=args.timeout,
                                workdir=tmp / f"m{index}", steps=args.steps)
            results.append(got)
            mark = "сделала" if got["ok"] else got["verdict"]
            print(f"  [{index}/{len(refs)}] {mark:11} {ref}")
            print(f"            шагов {got['steps']}, {got['seconds']} с, "
                  f"вызовы: {', '.join(got['tools']) or '—'}")
            if got["why"]:
                print(f"            причина: {got['why']}")
            if got["note"]:
                print(f"            {got['note'][:150]}")
            # Пауза между моделями: лимит считается на аккаунт, и замер не
            # должен сам стать причиной отказа по лимиту.
            await asyncio.sleep(1.5)
    finally:
        if args.keep:
            print(f"\nПапки оставлены: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    done = [r for r in results if r["ok"]]
    # Разбор по причинам обязателен: «не выполнила задачу» из-за лимита
    # аккаунта и из-за неумения вызвать инструмент — разные вещи. Первое
    # пройдёт само, второе надо убирать из ротации.
    by_why: dict[str, list[str]] = {}
    for r in results:
        if not r["ok"]:
            by_why.setdefault(r.get("why") or "причина неясна", []).append(r["ref"])

    print("\n" + "=" * 62)
    print(f"выполнили задачу: {len(done)} из {len(results)}")
    for why, refs_list in sorted(by_why.items(), key=lambda kv: -len(kv[1])):
        print(f"\n  {why} ({len(refs_list)}):")
        for ref in refs_list:
            print(f"    {ref}")

    if done:
        print("\nМожно назначать агента:")
        for r in sorted(done, key=lambda r: r["seconds"]):
            print(f"  {r['seconds']:>5} с  {r['ref']}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"\nJSON: {args.json}")
    if args.markdown:
        _write_markdown(results, Path(args.markdown))
        print(f"Сводка: {args.markdown}")

    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))