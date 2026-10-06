"""Замерить доступность моделей из текущей сети и записать в regions.json.

Ключевая оговорка, из-за которой команда требует явного режима:

    geo --direct   запускать с ВЫКЛЮЧЕННЫМ VPN
    geo --vpn      запускать с ВКЛЮЧЕННЫМ VPN

Замер с включённым VPN ничего не говорит о доступности из России: через VPN
доступно почти всё. Поэтому вердикт «работает без VPN» ставится только по
замеру `--direct`, и один прогон с `--vpn` не портит уже известный результат.

Пример двух прогонов, после которых вердикт становится честным:

    zagent geo --direct     # VPN выключить перед запуском
    zagent geo --vpn        # VPN включить и повторить
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.config import load_gateways, project_root  # noqa: E402
from hub.regions import (  # noqa: E402
    MODE_DIRECT,
    MODE_VPN,
    RU_LABELS,
    RegionBook,
    summarize,
)
from hub.registry import collect, probe_models  # noqa: E402

#: Статусы пинга, которые считаем «модель ответила».
ALIVE = ("ok", "slow", "empty")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zagent geo",
        description="Проверить доступность моделей из текущей сети",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--direct", action="store_true",
                       help="замер без VPN (VPN должен быть выключен)")
    group.add_argument("--vpn", action="store_true",
                       help="замер с включённым VPN")
    parser.add_argument("--gateway", action="append", default=[],
                        help="ограничить одним шлюзом (можно повторять)")
    parser.add_argument("--root", default=None, help="корень проекта")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать результат, не записывая в regions.json")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--pause", type=float, default=1.5,
                        help="пауза между пачками одного шлюза, сек")
    return parser


async def run(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else project_root()
    mode = MODE_VPN if args.vpn else MODE_DIRECT

    print(f"Режим замера: {'VPN включён' if args.vpn else 'БЕЗ VPN'}")
    if args.vpn:
        print("  Внимание: с VPN доступно почти всё. Этот замер НЕ доказывает,")
        print("  что модель работает из России — для этого нужен --direct.")
    else:
        print("  Убедитесь, что VPN действительно выключен, иначе замер врёт.")

    gateways = load_gateways(root, env={})
    if args.gateway:
        wanted = set(args.gateway)
        gateways = [g for g in gateways if g["id"] in wanted]
        if not gateways:
            print(f"Нет таких шлюзов: {', '.join(wanted)}", file=sys.stderr)
            return 2

    registry = await collect(gateways, root=root)
    models = list(registry.chat_models)
    if not models:
        print("Реестр пуст: нет моделей для проверки", file=sys.stderr)
        return 1

    print(f"Проверяю {len(models)} моделей в {len(gateways)} шлюзах…\n")
    probes = await probe_models(
        gateways, models, timeout=args.timeout, per_gateway_pause=args.pause
    )

    book = RegionBook.load(root)
    by_gateway: dict[str, int] = {}
    for model in models:
        probe = probes.get(model.ref) or {}
        status = str(probe.get("status") or "down")
        note = book.record(model.ref, mode, status)
        mark = {"ok": "✔", "vpn": "🔒", "blocked": "✘", "unknown": "?"}[note.status]
        label = RU_LABELS[note.status]
        by_gateway[model.gateway_id] = by_gateway.get(model.gateway_id, 0) + (
            1 if status in ALIVE else 0
        )
        print(f"  {mark} {model.ref:<48} пинг={status:<8} → {label}")

    stats = summarize(book)
    print(f"\nСводка: проверено {stats['measured']}, "
          f"без VPN {stats['counts']['ok']}, "
          f"нужен VPN {stats['counts']['vpn']}, "
          f"недоступно {stats['counts']['blocked']}, "
          f"неизвестно {stats['counts']['unknown']}")

    if args.dry_run:
        print("\n--dry-run: файл не изменён")
        return 0

    path = book.save()
    print(f"\nЗаписано: {path}")
    if mode == MODE_VPN and stats["counts"]["ok"] == 0:
        print("Подсказка: вердикт «без VPN» появится после `zagent geo --direct`.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nПрервано", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
