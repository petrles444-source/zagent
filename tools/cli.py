#!/usr/bin/env python3
"""Точка входа zagent — реестр бесплатных LLM-моделей.

Команды:
    scan                 собрать реестр из config/gateways.json + живых каталогов
    ping                 живой пинг всех бесплатных моделей, записать отчёт
    list                 показать последний отчёт (или собрать, если его нет)
    export <формат>      вывести конфиг для opencode | codex | zed | cline | kilocode | plain
    health               старая команда: пинг моделей из config/models.json
    ask / swarm          спросить одну роль / все модели

Примеры:
    python tools/cli.py ping --write
    python tools/cli.py list --only ok
    python tools/cli.py export opencode > opencode.jsonc
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import exporters, report  # noqa: E402
from hub.config import (  # noqa: E402
    ConfigError,
    NO_KEY_MESSAGE,
    load_api_key,
    load_gateways,
    load_models,
    project_root,
)
from hub.health import SLOW_AFTER_S, check_all, format_reports  # noqa: E402
from hub.registry import collect, probe_models  # noqa: E402
from providers.openai_compat import DEFAULT_TIMEOUT, OpenAICompatProvider  # noqa: E402
from providers.zen import ZenProvider  # noqa: E402

EXIT_OK = 0
EXIT_DOWN = 1
EXIT_ERROR = 2


def _force_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="zagent — реестр бесплатных LLM-моделей и генератор конфигов.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="собрать реестр бесплатных моделей")
    scan.add_argument("--json", action="store_true", help="вывести полный JSON в консоль")
    scan.add_argument("--write", action="store_true", help="записать docs/free-models.{json,md}")

    ping = subparsers.add_parser("ping", help="живой пинг всех бесплатных моделей")
    ping.add_argument("--timeout", type=float, default=60.0, help="таймаут запроса, сек")
    ping.add_argument("--max-tokens", type=int, default=256, help="лимит токенов ответа")
    ping.add_argument("--concurrency", type=int, default=6, help="сколько запросов параллельно")
    ping.add_argument("--write", action="store_true", help="записать docs/free-models.{json,md}")
    ping.add_argument("--slow-after", type=float, default=SLOW_AFTER_S, help="порог slow, сек")
    ping.add_argument(
        "--pause", type=float, default=1.5, help="пауза между пачками одного шлюза, сек"
    )
    ping.add_argument("--no-retry", action="store_true", help="не повторять модели после 429")

    listing = subparsers.add_parser("list", help="показать последний отчёт")
    listing.add_argument("--only", help="только эти статусы через запятую: ok,slow,empty,down")
    listing.add_argument("--gateway", help="только один шлюз")
    listing.add_argument("--refresh", action="store_true", help="пересобрать отчёт с нуля")

    exp = subparsers.add_parser("export", help="вывести конфиг для другого инструмента")
    exp.add_argument(
        "format",
        choices=sorted(exporters.EXPORTERS),
        help="opencode | codex | zed | cline | kilocode | plain",
    )
    exp.add_argument("--gateway", help="только один шлюз")
    exp.add_argument(
        "--verified-only",
        action="store_true",
        help="исключить модели со статусом blocked/down из последнего отчёта",
    )

    health = subparsers.add_parser("health", help="пинг моделей из config/models.json")
    health.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    health.add_argument("--slow-after", type=float, default=SLOW_AFTER_S)

    ask = subparsers.add_parser("ask", help="спросить одну модель по роли")
    ask.add_argument("question")
    ask.add_argument("--role", default="coder", help="роль: coder | architect | reviewer")
    ask.add_argument("--gateway", default="openrouter", help="шлюз для ask")

    swarm = subparsers.add_parser("swarm", help="спросить все модели шлюза параллельно")
    swarm.add_argument("question")
    swarm.add_argument("--gateway", default="openrouter", help="шлюз для swarm")
    swarm.add_argument("--limit", type=int, default=5, help="сколько моделей опросить")

    return parser


# --------------------------------------------------------------------- scan


async def _run_scan(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        gateways = load_gateways(root)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return EXIT_ERROR

    registry = await collect(gateways, root=root)
    snapshot = report.build_snapshot(registry)

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(f"Собрано моделей: {snapshot['total_chat_models']}")
        print()
        print(report.render_table(snapshot))
        print()
        print("Статусы пустые — это только сбор каталога. Для проверки ответов: `ping --write`.")
        for gateway_id, error in sorted(registry.errors.items()):
            print(f"  ! {gateway_id}: {error}", file=sys.stderr)

    if args.write:
        json_path = report.write_json(snapshot, root)
        md_path = report.write_markdown(snapshot, root)
        if not args.json:
            print()
            print(f"Записано: {json_path.relative_to(root)}, {md_path.relative_to(root)}")

    return EXIT_OK


# --------------------------------------------------------------------- ping


async def _run_ping(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        gateways = load_gateways(root)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return EXIT_ERROR

    usable = [g for g in gateways if g.get("has_key") or not g.get("needs_key")]
    if not usable:
        print(NO_KEY_MESSAGE)
        return EXIT_ERROR

    missing = [g["id"] for g in gateways if g.get("needs_key") and not g.get("has_key")]
    if missing:
        print(f"Пропускаю шлюзы без ключа: {', '.join(missing)}", file=sys.stderr)

    print("Собираю реестр...", file=sys.stderr)
    registry = await collect(gateways, root=root)
    print(f"Моделей к проверке: {len(registry.chat_models)}", file=sys.stderr)

    print("Пингую...", file=sys.stderr)
    probes = await probe_models(
        gateways,
        registry.chat_models,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        concurrency=args.concurrency,
        per_gateway_pause=args.pause,
        retry_on_limit=not args.no_retry,
    )

    snapshot = report.build_snapshot(registry, probes, slow_after_ms=int(args.slow_after * 1000))
    print(report.render_table(snapshot))
    print()
    print(report.render_summary(snapshot))
    print()
    print(report.render_legend())

    if registry.errors:
        print(file=sys.stderr)
        for gateway_id, error in sorted(registry.errors.items()):
            print(f"  ! {gateway_id}: {error}", file=sys.stderr)

    if args.write:
        json_path = report.write_json(snapshot, root)
        md_path = report.write_markdown(snapshot, root)
        print()
        print(f"Записано: {json_path.relative_to(root)}, {md_path.relative_to(root)}")

    counts = snapshot.get("status_counts") or {}
    alive = sum(counts.get(status, 0) for status in report.ALIVE_STATUSES)
    return EXIT_OK if alive else EXIT_DOWN


# --------------------------------------------------------------------- list


def _load_snapshot(root: Path) -> dict | None:
    path = root / report.CATALOG_JSON
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _filter_snapshot(snapshot: dict, args: argparse.Namespace) -> dict:
    models = snapshot.get("models", [])
    if getattr(args, "gateway", None):
        models = [m for m in models if m.get("gateway") == args.gateway]
    if getattr(args, "only", None):
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        models = [m for m in models if m.get("status") in wanted]
    filtered = dict(snapshot)
    filtered["models"] = models
    counts: dict[str, int] = {}
    for model in models:
        counts[model.get("status")] = counts.get(model.get("status"), 0) + 1
    filtered["status_counts"] = counts
    filtered["total_chat_models"] = len(models)
    return filtered


async def _run_list(args: argparse.Namespace) -> int:
    root = project_root()
    snapshot = None if args.refresh else _load_snapshot(root)
    if snapshot is None:
        print("Отчёта нет, собираю...", file=sys.stderr)
        defaults = {
            "write": True,
            "timeout": 60.0,
            "max_tokens": 256,
            "concurrency": 6,
            "slow_after": SLOW_AFTER_S,
            "pause": 1.5,
            "no_retry": False,
        }
        return await _run_ping(argparse.Namespace(**{**defaults, **vars(args)}))
    print(f"Снимок от {snapshot.get('generated_at')}")
    print()
    print(report.render_table(_filter_snapshot(snapshot, args)))
    print()
    print(report.render_summary(_filter_snapshot(snapshot, args)))
    return EXIT_OK


# ------------------------------------------------------------------- export


async def _run_export(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        gateways = load_gateways(root)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return EXIT_ERROR

    registry = await collect(gateways, root=root)

    statuses = None
    if args.verified_only:
        snapshot = _load_snapshot(root)
        if snapshot is None:
            print(
                "Нет отчёта docs/free-models.json — сначала выполните `ping --write`.",
                file=sys.stderr,
            )
            return EXIT_ERROR
        statuses = {m["ref"]: m["status"] for m in snapshot.get("models", [])}
        dead = sum(1 for s in statuses.values() if s in ("blocked", "down"))
        print(f"Исключаю {dead} моделей со статусом blocked/down", file=sys.stderr)

    model_ids = None
    if args.gateway:
        model_ids = [m.ref for m in registry.for_gateway(args.gateway)]
        if not model_ids:
            print(f"У шлюза '{args.gateway}' нет бесплатных моделей", file=sys.stderr)
            return EXIT_ERROR

    try:
        output = exporters.export(args.format, registry, model_ids=model_ids, statuses=statuses)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    if args.format == "zed":
        print(exporters.ZED_KEY_HINT, file=sys.stderr)
    # Предупреждение о нескольких аккаунтах: экспорт отдаёт один ключ, и
    # без этого предупреждения человек решит, что вынес все девять.
    note = exporters.multi_key_note(registry.gateways)
    if note:
        print(note, file=sys.stderr)
    print(output)
    return EXIT_OK


# ------------------------------------------------------------------- health


async def _run_health(args: argparse.Namespace) -> int:
    """Старая команда: пинг моделей из config/models.json через OpenCode Zen."""
    root = project_root()
    try:
        config = load_models(root)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return EXIT_ERROR

    api_key = load_api_key(root)
    if not api_key:
        print("Ключ Zen не задан. Используйте `ping` — он работает без ключа Zen.")
        return EXIT_ERROR

    async with ZenProvider(config["base_url"], api_key, timeout=args.timeout) as provider:
        reports = await check_all(
            provider, config["models"], slow_after=args.slow_after, root=root
        )
    print(format_reports(reports))
    print()
    alive = sum(1 for r in reports if r.alive)
    print(f"Доступно моделей: {alive} из {len(reports)}")
    return EXIT_OK if alive == len(reports) else EXIT_DOWN


# ---------------------------------------------------------------- ask/swarm


async def _run_ask(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        gateways = load_gateways(root)
        gateway = next(g for g in gateways if g["id"] == args.gateway)
    except (ConfigError, StopIteration) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if gateway.get("needs_key") and not gateway.get("has_key"):
        print(f"У шлюза '{args.gateway}' нет ключа — добавьте его в config/secrets.local.json")
        return EXIT_ERROR

    registry = await collect([gateway], root=root)
    models = registry.chat_models
    if not models:
        print(f"У шлюза '{args.gateway}' нет бесплатных моделей", file=sys.stderr)
        return EXIT_ERROR

    async with OpenAICompatProvider(
        gateway["id"], gateway["resolved_url"], gateway["api_key"]
    ) as provider:
        result = await provider.chat(models[0].model_id, [{"role": "user", "content": args.question}])

    if result.get("error"):
        print(f"Ошибка: {result['error']}", file=sys.stderr)
        return EXIT_DOWN
    print(result.get("text") or result.get("reasoning") or "(пустой ответ)")
    print(f"\n— {models[0].ref}, {result.get('duration_ms', 0)} мс", file=sys.stderr)
    return EXIT_OK


async def _run_swarm(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        gateways = load_gateways(root)
        gateway = next(g for g in gateways if g["id"] == args.gateway)
    except (ConfigError, StopIteration) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return EXIT_ERROR

    registry = await collect([gateway], root=root)
    models = registry.chat_models[: args.limit]
    if not models:
        print(f"У шлюза '{args.gateway}' нет бесплатных моделей", file=sys.stderr)
        return EXIT_ERROR

    print(f"Спрашиваю {len(models)} моделей шлюза {args.gateway}...", file=sys.stderr)

    from hub.bus import gather_chats

    async with OpenAICompatProvider(
        gateway["id"], gateway["resolved_url"], gateway["api_key"]
    ) as provider:
        results = await gather_chats(
            provider, [m.model_id for m in models], [{"role": "user", "content": args.question}]
        )

    for model, result in zip(models, results):
        print("=" * 60)
        print(f"{model.ref}  ({result.get('duration_ms', 0)} мс, "
              f"{result.get('tokens_in', 0)}+{result.get('tokens_out', 0)} токенов)")
        print("-" * 60)
        text = result.get("text") or result.get("reasoning") or ""
        print(text if text else f"(пусто: {result.get('error')})")
        print()

    alive = sum(1 for r in results if r.get("error") is None)
    return EXIT_OK if alive else EXIT_DOWN


# ---------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    args = build_parser().parse_args(argv)

    try:
        if args.command == "scan":
            return asyncio.run(_run_scan(args))
        if args.command == "ping":
            return asyncio.run(_run_ping(args))
        if args.command == "list":
            return asyncio.run(_run_list(args))
        if args.command == "export":
            return asyncio.run(_run_export(args))
        if args.command == "health":
            return asyncio.run(_run_health(args))
        if args.command == "ask":
            return asyncio.run(_run_ask(args))
        if args.command == "swarm":
            return asyncio.run(_run_swarm(args))
    except KeyboardInterrupt:
        print("Прервано", file=sys.stderr)
        return EXIT_ERROR

    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
