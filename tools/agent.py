#!/usr/bin/env python3
"""CLI агента: автономная работа, режим вопросов, инструменты, браузер.

Команды:
    run <задача>              запустить агента до конца
    step <задача>             один шаг (для отладки)
    plan <задача>             построить план и ждать одобрения
    consult <вопрос>          спросить N моделей и сравнить ответы
    ask <вопрос>              одиночный запрос через failover
    modes                     список моделей с тирами
    tools                     доступные инструменты при текущем уровне доступа
    read <файл>               прочитать файл
    write <файл>              записать содержимое из stdin
    edit <файл> <old> <new>   точечная замена
    grep <строка> [путь]      поиск по файлам
    shell <команда>           выполнить команду
    shot [файл]               снимок экрана
    fetch <url>               открыть страницу в браузере
    login <url>               окно браузера для ручного входа
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.agent import Agent, AgentConfig, make_guard, selector_from_registry  # noqa: E402
from hub.autonomy import AccessLevel, Autonomy, Escalation  # noqa: E402
from hub.config import ConfigError, load_gateways, project_root  # noqa: E402
from hub.failover import AutoCaller, FailoverError  # noqa: E402
from hub.registry import collect, probe_models  # noqa: E402
from hub.sanity import build_probe_prompt, evaluate  # noqa: E402
from hub.tools import run_tool  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent.py", description="Агент zagent")
    parser.add_argument("--base", default=".", help="рабочая директория агента")
    parser.add_argument("--access", type=int, default=2, choices=[1, 2, 3],
                        help="1=чтение, 2=запись, 3=полный")
    parser.add_argument("--autonomy", default="normal",
                        choices=["yolo", "normal", "strict", "plan"])
    parser.add_argument("--escalation", default="auto", choices=["off", "auto", "on"])
    parser.add_argument("--model", help="ручной выбор модели (gateway/model)")
    parser.add_argument("--speed", action="store_true", help="быстрые модели приоритетнее")
    parser.add_argument("--vision", action="store_true", help="только vision-модели")
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=120.0)

    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("run", "выполнить задачу до конца"),
        ("step", "один шаг"),
        ("plan", "построить план и ждать одобрения"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("task")

    consult = sub.add_parser("consult", help="спросить несколько моделей")
    consult.add_argument("question")
    consult.add_argument("-n", type=int, default=3)

    ask = sub.add_parser("ask", help="одиночный запрос")
    ask.add_argument("question")

    sub.add_parser("modes", help="список моделей с тирами")

    sanity = sub.add_parser("sanity", help="проверить адекватность моделей")
    sanity.add_argument("--model", help="одна модель, иначе все")
    sanity.add_argument("--lang", default="ru", choices=["ru", "en"])

    tools = sub.add_parser("tools", help="доступные инструменты")
    tools.add_argument("--access", type=int, choices=[1, 2, 3])

    read = sub.add_parser("read", help="прочитать файл")
    read.add_argument("path")

    write = sub.add_parser("write", help="записать stdin в файл")
    write.add_argument("path")

    edit = sub.add_parser("edit", help="заменить строку в файле")
    edit.add_argument("path")
    edit.add_argument("old")
    edit.add_argument("new")

    grep = sub.add_parser("grep", help="поиск по файлам")
    grep.add_argument("pattern")
    grep.add_argument("path", nargs="?", default=".")
    grep.add_argument("--glob", default="**/*")

    shell = sub.add_parser("shell", help="выполнить команду")
    shell.add_argument("command_text")

    shot = sub.add_parser("shot", help="снимок экрана")
    shot.add_argument("output", nargs="?", default="screenshots/screen.png")

    fetch = sub.add_parser("fetch", help="открыть страницу")
    fetch.add_argument("url")
    fetch.add_argument("--shot", action="store_true", help="сохранить скриншот")
    fetch.add_argument("--headless", action="store_true")

    login = sub.add_parser("login", help="окно браузера для ручного входа")
    login.add_argument("url")
    login.add_argument("--wait", type=float, default=180.0)

    return parser


def _config(args: argparse.Namespace) -> AgentConfig:
    return AgentConfig(
        access=AccessLevel(args.access),
        autonomy=Autonomy(args.autonomy),
        escalation=Escalation(args.escalation),
        base_dir=args.base,
        max_steps=args.max_steps,
        step_timeout=args.timeout,
        require_vision=args.vision,
    )


async def _registry(root: Path):
    gateways = load_gateways(root, env={})
    registry = await collect(gateways, root=root)
    return gateways, registry


async def _selector(args: argparse.Namespace, root: Path):
    gateways, registry = await _registry(root)
    selector = selector_from_registry(
        registry,
        mode="manual" if args.model else "auto",
        manual_ref=args.model,
        prefer_speed=args.speed,
        require_vision=args.vision,
        root=str(root),
    )
    return gateways, registry, selector


def _print_selector(selector) -> None:
    rows = selector.candidates()
    width = max((len(r["ref"]) for r in rows), default=10)
    print(f"Моделей: {len(rows)}  режим: {selector.mode.value}")
    print()
    for row in rows:
        flags = []
        if row["vision"]:
            flags.append("vision")
        if row["in_cooldown"]:
            flags.append(f"карантин {row['cooldown_left']}с")
        if row["status"] not in ("unknown",):
            flags.append(row["status"])
        suffix = "  [" + ", ".join(flags) + "]" if flags else ""
        print(f"  тир {row['tier']}  {row['ref']:<{width}}{suffix}")


# ------------------------------------------------------------------- команды


async def _cmd_run(args: argparse.Namespace, *, single_step: bool = False,
                   plan_only: bool = False) -> int:
    root = project_root()
    config = _config(args)
    if plan_only:
        config.autonomy = Autonomy.PLAN

    gateways, registry, selector = await _selector(args, root)
    if args.model and args.model not in selector.states:
        print(f"Модель не найдена: {args.model}", file=sys.stderr)
        return EXIT_ERROR

    guard = make_guard(config)
    events: list[str] = []

    def on_event(event: dict) -> None:
        kind = event.get("type")
        if kind == "step":
            step = event["step"]
            mark = "ok" if step["ok"] else "!!"
            print(f"  [{mark}] {step['phase']:<9} {step['text']}"
                  f"{' — ' + step['model'] if step.get('model') else ''}", flush=True)
        elif kind == "question":
            events.append(event["question"])
        elif kind == "done":
            events.append(event["text"])

    agent = Agent(selector, guard, config, on_event=on_event)

    print(f"Задача: {args.task}")
    print(f"Доступ: {guard.access.label} | автономия: {guard.autonomy.label} | "
          f"помощь: {guard.escalation.label}")
    print(f"Модель: {selector.current}")
    print("-" * 60, flush=True)

    if single_step:
        agent.set_task(args.task)
        agent.config.max_steps = 1
    else:
        agent.set_task(args.task)

    result = await agent.run()

    print("-" * 60)
    print(f"Фаза: {result['phase']}, шагов: {result['steps']}, "
          f"время: {result['duration_ms'] / 1000:.1f}с")
    if result.get("models_used"):
        print(f"Модели: {', '.join(result['models_used'])}")
    stats = result.get("selector", {})
    print(f"Моделей в реестре: {stats.get('total')}, ok: {stats.get('ok')}, "
          f"в карантине: {stats.get('cooling')}, заблокировано: {stats.get('blocked')}")

    if result.get("pending_question"):
        print(f"\nВОПРОС АГЕНТА: {result['pending_question']}")
        print("Ответьте: python tools/agent.py answer \"ваш ответ\"" if False else "")
        return EXIT_OK

    if result.get("last"):
        print(f"\nИтог: {result['last'][:800]}")
    return EXIT_OK if result["ok"] else EXIT_FAIL


async def _cmd_consult(args: argparse.Namespace) -> int:
    root = project_root()
    gateways, registry, selector = await _selector(args, root)
    config = _config(args)
    agent = Agent(selector, make_guard(config), config)

    print(f"Вопрос: {args.question}")
    print(f"Спрашиваю {args.n} моделей…\n", flush=True)

    opinions = await agent.consult(args.question, models=args.n)
    for index, opinion in enumerate(opinions, start=1):
        print("=" * 60)
        print(f"{index}. {opinion['ref']}  ({opinion['duration_ms']} мс)")
        print("-" * 60)
        print(opinion["error"] or opinion["text"] or "(пусто)")
        print()
    return EXIT_OK if opinions else EXIT_FAIL


async def _cmd_ask(args: argparse.Namespace) -> int:
    root = project_root()
    gateways, registry, selector = await _selector(args, root)
    caller = AutoCaller(selector, timeout=args.timeout)

    try:
        result = await caller.ask(
            [{"role": "user", "content": args.question}],
            include_attempts=True,
        )
    except FailoverError as exc:
        print(f"Все модели отказали: {exc}", file=sys.stderr)
        return EXIT_FAIL

    failed = [a for a in (result.get("attempts") or []) if not a.get("ok")]
    if failed:
        print("Переключился с: " + ", ".join(a["ref"] for a in failed), file=sys.stderr)

    print(result.get("text") or result.get("reasoning") or "(пусто)")
    print(f"\n— {result['model']} · {result['duration_ms']} мс · "
          f"{result['tokens_in']}+{result['tokens_out']} токенов", file=sys.stderr)
    return EXIT_OK


async def _cmd_modes(args: argparse.Namespace) -> int:
    root = project_root()
    gateways, registry, selector = await _selector(args, root)
    _print_selector(selector)
    return EXIT_OK


async def _cmd_sanity(args: argparse.Namespace) -> int:
    root = project_root()
    gateways, registry, selector = await _selector(args, root)
    system, user, token = build_probe_prompt(args.lang)

    from providers.openai_compat import OpenAICompatProvider
    import httpx

    targets = registry.chat_models
    if args.model:
        targets = [m for m in targets if m.ref == args.model]
        if not targets:
            print(f"Модель не найдена: {args.model}", file=sys.stderr)
            return EXIT_ERROR

    print(f"Проверяю {len(targets)} моделей…\n", flush=True)
    rows = []
    for model in targets:
        gateway = next((g for g in gateways if g["id"] == model.gateway_id), None)
        if gateway is None:
            continue
        async with httpx.AsyncClient(follow_redirects=True) as client:
            provider = OpenAICompatProvider(
                model.gateway_id, gateway["resolved_url"], gateway["api_key"],
                timeout=args.timeout, client=client,
            )
            result = await provider.chat(
                model.model_id,
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0, max_tokens=400,
            )

        duration = int(result.get("duration_ms") or 0)
        if result.get("error"):
            rows.append((model.ref, 0.0, "unreachable", duration,
                         str(result["error"])[:60], []))
        else:
            answer = str(result.get("text") or result.get("reasoning") or "")
            report = evaluate(model.ref, answer, question=user, token=token,
                              duration_ms=duration, lang=args.lang)
            rows.append((model.ref, report.score, report.verdict, duration, "",
                         [f"{'✔' if c.passed else '✘'} {c.name}" for c in report.checks]))

        line = rows[-1]
        print(f"  {line[2]:<10} {line[0]:<58} {line[1]:.2f}  {line[3]} мс "
              f"{line[4] or ' '.join(line[5])}", flush=True)
        await asyncio.sleep(1.5)

    good = sum(1 for r in rows if r[2] in ("good", "usable"))
    print(f"\nПригодных: {good} из {len(rows)}")
    return EXIT_OK if good else EXIT_FAIL


def _guard(args: argparse.Namespace):
    return make_guard(_config(args))


def _cmd_tools(args: argparse.Namespace) -> int:
    from hub.tools import available_tools

    access = AccessLevel(args.access or args.access_level)
    guard = make_guard(AgentConfig(access=access, base_dir=args.base))
    tools = available_tools(guard)
    print(f"Уровень доступа: {guard.access.label}")
    print(f"Инструментов доступно: {len(tools)}\n")
    for tool in tools:
        print(f"  {tool['signature']}")
        print(f"      {tool['description']}")
    return EXIT_OK


def _cmd_tool(args: argparse.Namespace, name: str, **kwargs) -> int:
    guard = _guard(args)
    base = Path(args.base).resolve()
    result = run_tool(name, guard, base=base, **kwargs)
    if not result.ok:
        print(f"Ошибка: {result.error}", file=sys.stderr)
        if result.needs_user:
            print(f"Нужна помощь: {result.question}", file=sys.stderr)
        return EXIT_FAIL
    data = result.data
    if isinstance(data, dict) and "content" in data:
        print(data["content"])
    elif isinstance(data, dict):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data)
    return EXIT_OK


async def _cmd_fetch(args: argparse.Namespace) -> int:
    from hub.browser import BrowserUnavailable, quick_fetch

    try:
        info = await quick_fetch(args.url, headless=args.headless, shot=args.shot)
    except BrowserUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR

    print(f"URL: {info.url}")
    print(f"Заголовок: {info.title}")
    print(f"Ссылки: {len(info.links)}, время: {info.duration_ms} мс")
    if info.screenshot:
        print(f"Скриншот: {info.screenshot}")
    if info.needs_login:
        print("\nПохоже, нужна авторизация. Войдите один раз:")
        print(f"  python tools/agent.py login {args.url}")
        print("Агент обходить капчу и антибот-проверки не будет.", file=sys.stderr)
    print("-" * 60)
    print(info.text[:4000])
    return EXIT_OK


async def _cmd_login(args: argparse.Namespace) -> int:
    from hub.browser import Browser, BrowserUnavailable

    try:
        browser = Browser(headless=False)
        await browser.start()
    except BrowserUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR

    print(f"Открываю {args.url} в окне браузера.")
    print("Войдите в аккаунт вручную. Жду завершения…\n")
    try:
        info = await browser.login(args.url, wait_seconds=args.wait)
    finally:
        await browser.close()

    print(f"Готово: {info.url}")
    print(f"Заголовок: {info.title}")
    print("Сессия сохранена в browser-profile/, повторно логиниться не придётся.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)

    # tools использует собственный --access, потому что он уже занят глобальным.
    if args.command == "tools":
        args.access_level = args.access

    try:
        if args.command in ("run", "step", "plan"):
            return asyncio.run(_cmd_run(
                args,
                single_step=args.command == "step",
                plan_only=args.command == "plan",
            ))
        if args.command == "consult":
            return asyncio.run(_cmd_consult(args))
        if args.command == "ask":
            return asyncio.run(_cmd_ask(args))
        if args.command == "modes":
            return asyncio.run(_cmd_modes(args))
        if args.command == "sanity":
            return asyncio.run(_cmd_sanity(args))
        if args.command == "tools":
            return _cmd_tools(args)
        if args.command == "read":
            return _cmd_tool(args, "read_file", path=args.path)
        if args.command == "write":
            return _cmd_tool(args, "write_file", path=args.path, content=sys.stdin.read())
        if args.command == "edit":
            return _cmd_tool(args, "edit_file", path=args.path, old=args.old, new=args.new)
        if args.command == "grep":
            return _cmd_tool(args, "search_text", pattern=args.pattern,
                             path=args.path, glob=args.glob)
        if args.command == "shell":
            return _cmd_tool(args, "run_shell", command=args.command_text)
        if args.command == "shot":
            return _cmd_tool(args, "capture_screen", output=args.output)
        if args.command == "fetch":
            return asyncio.run(_cmd_fetch(args))
        if args.command == "login":
            return asyncio.run(_cmd_login(args))
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        return EXIT_ERROR

    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
