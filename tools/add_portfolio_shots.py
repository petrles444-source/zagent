r"""Добавить портфолио в список снимков каталога.

Зачем
----
В каталоге 52 карточки, снимки есть у 45. Семь портфолио — `aurum`,
`lumen`, `onyx`, `neon`, `paper`, `term`, `steel` — снимков не имели,
и вместо них рисовалась полоса из палитры. На скриншоте это и видно:
у карточек Aurum и Lumen вместо снимка серые полосы.

Причина простая: портфолио выкладывает отдельный загрузчик, а список
адресов для снимков живёт в `tools/make_shots.py` и этих семи там
не было. Никто их не добавлял.

Правка вносится в список, а не отдельным файлом: иначе через месяц
появится ещё один сайт и история повторится.

Запуск:
    .venv\\Scripts\\python.exe tools\\add_portfolio_shots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "tools" / "make_shots.py"

#: Портфолио и их названия. Порядок — как в каталоге.
PORTFOLIOS = (
    ("/aurum/", "Aurum"),
    ("/lumen/", "Lumen"),
    ("/onyx/", "Onyx"),
    ("/neon/", "Neon"),
    ("/paper/", "Paper"),
    ("/term/", "Term"),
    ("/steel/", "Steel"),
)


def main() -> int:
    body = SHOTS.read_text(encoding="utf-8")

    if '"/aurum/"' in body:
        print("  портфолио уже есть в списке — ничего не меняю")
        return 0

    # Список заканчивается последней строкой с `),`. Вставка идёт
    # перед ней.
    start = body.index("PAGES: tuple[tuple[str, str], ...] = (")
    end = body.index("\n)", start)

    # Куда вставлять: в начало списка или в конец. Ставим в конец,
    # чтобы порядок уже проверенных адресов не сдвигался и номера
    # в отчётах оставались прежними.
    added = []
    for path, title in PORTFOLIOS:
        added.append(f'    ("{path}", "{title}"),')
    block = ("\n    # Портфолио. Их выкладывает отдельный загрузчик, и в\n"
             "    # этом списке их не было — отсюда полосы из палитры вместо\n"
             "    # снимков на seven карточках.\n"
             + "\n".join(added) + "\n")

    body = body[:end] + "\n" + block.rstrip("\n") + body[end:]
    SHOTS.write_text(body, encoding="utf-8")

    import ast
    ast.parse(body)
    print(f"  добавлено портфолио: {len(PORTFOLIOS)}")
    print("  make_shots.py разбирается")
    return 0


if __name__ == "__main__":
    sys.exit(main())