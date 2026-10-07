#!/usr/bin/env python
"""Проверить, какие модели реестра умеют вызывать инструменты.

Зачем это отдельным скриптом, а не частью пинга: обычный пинг спрашивает
«отвечает ли модель», а агент спрашивает «умеет ли модель вызвать
инструмент». Расходятся эти два свойства сильно.

Замер на всём реестре показал: из 38 моделей вызов инструмента корректно
делает одна. Остальные ведут себя тремя разными способами:

* отказ по лимиту провайдера — вопрос времени, а не свойства модели;
* ``{"error": "tool_call_not_available"}`` — модель прямо отказывается;
* JSON без ключа ``tool`` — модель отвечает, но не тем форматом.

Первый случай починится ожиданием, второй и третий — выбором другой модели.
Склеивать их в один «модель плохая» нельзя, поэтому скрипт их разделяет.

Запуск:
    .venv\\Scripts\\python.exe tools\\check_tool_models.py
    .venv\\Scripts\\python.exe tools\\check_tool_models.py --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from hub.agent import parse_tool_calls, selector_from_registry  # noqa: E402
from hub.config import load_gateways  # noqa: E402
from hub.failover import AutoCaller  # noqa: E402
from hub.registry import collect  # noqa: E402
from hub.selector import Mode  # noqa: E402

#: Промпт должен быть таким же, какой видит агент на первом шаге. Соблазн
#: написать «Вызови инструмент list_dir…» не сработало: модель отвечала
#: содержимым каталога текстом, то есть выполняла просьбу вместо того, чтобы
#: её кодировать. С примером формата — работает.
PROMPT = (
    "Вызови инструмент list_dir с path '.'.\n"
    "Ответь ТОЛЬКО JSON в блоке ```json и больше ничем:\n"
    '```json\n{"tool": "list_dir", "args": {"path": "."}}\n```'
)

#: Ответ без вызова инструмента, который модель отдаёт вместо запрошенного
#: формата. По нему видно, что модель поняла задачу, но не формат.
WRONG_SHAPE = {
    "tool_call_not_available": "модель прямо отказывается вызывать инструменты",
    "[]": "пустой список вместо вызова",
}


async def probe(selector, ref: str, *, timeout: float) -> tuple[str, str]:
    """Одна модель. Возвращает (вердикт, пояснение)."""
    selector.mode = Mode.MANUAL
    selector.manual_ref = ref
    caller = AutoCaller(selector, manual_only=True, timeout=timeout)
    try:
        result = await caller.ask(
            [{"role": "user", "content": PROMPT}], max_tokens=2048
        )
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "Лимит запросов" in text:
            return "лимит", "провайдер отклонил по лимиту — вопрос времени"
        if "Tool choice is none" in text:
            return "отказ", "вызвала инструмент при запрещённом вызове"
        return "отказ", text[:90]

    text = str(result.get("text") or "")
    if parse_tool_calls(text):
        return "да", str(result.get("model") or ref)

    for needle, meaning in WRONG_SHAPE.items():
        if needle in text:
            return "нет", meaning
    if "```json" in text or text.strip().startswith("{"):
        return "нет", "ответ не в формате вызова инструмента"
    return "нет", f"пустой или нечитаемый ответ: {text[:60]!r}"


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка умения вызывать инструменты у моделей реестра."
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="проверить только первые N моделей")
    parser.add_argument("--timeout", type=float, default=40.0,
                        help="таймаут одной модели в секундах")
    parser.add_argument("--model", help="проверить одну модель по ref")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    registry = await collect(load_gateways(root, env={}), root=root)
    selector = selector_from_registry(registry, mode="auto", root=str(root))

    if args.model:
        refs = [args.model]
    else:
        refs = list(selector.states)
        if args.limit:
            refs = refs[:args.limit]

    print(f"Моделей к проверке: {len(refs)}\n")
    tally = {"да": 0, "нет": 0, "отказ": 0, "лимит": 0}
    rows: list[tuple[str, str, str]] = []
    for index, ref in enumerate(refs, start=1):
        verdict, note = await probe(selector, ref, timeout=args.timeout)
        tally[verdict] = tally.get(verdict, 0) + 1
        rows.append((ref, verdict, note))
        print(f"  [{index}/{len(refs)}] {verdict:5} {ref}\n           {note}")

    print("\n" + "=" * 60)
    print(f"вызывают инструмент: {tally['да']}")
    print(f"не вызывают:         {tally['нет']}")
    print(f"отказ провайдера:    {tally['отказ']}")
    print(f"лимит запросов:      {tally['лимит']}")

    usable = [ref for ref, verdict, _ in rows if verdict == "да"]
    if usable:
        print("\nМожно назначить агента:")
        for ref in usable:
            print(f"  {ref}")
        if len(usable) < 3:
            print("\nМало моделей справляется: на резервную модель опираться не на что.")
            print("Повторите позже — часть моделей сейчас отсеяна по лимиту.")
    else:
        print("\nНи одна модель не вызвала инструмент: агент не справится.")
        print("Подождите сброса лимитов и повторите.")
    return 0 if usable else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))