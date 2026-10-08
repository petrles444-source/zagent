r"""Перенести тесты, уехавшие вместе с инструментами.

Зачем
----
Инструменты сайтов переехали в отдельный проект. Тесты на них
остались в агенте и упали на самом сборе: `test_shrink_images.py`
подгружает `tools/shrink_images.py`, которого в агенте больше нет.

Падение происходило на импорте, то есть **до первого теста** — весь
прогон останавливался целиком. Проверялось это сразу и заметно:
одна уехавшая строчка блокирует 1783 остальных.

Поэтому тесты переезжают вместе со своим инструментом, туда же, где
лежат их данные.

Запуск:
    .venv\\Scripts\\python.exe tools\\move_site_tests.py
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT.parent / "portfolio"
AGENT_TESTS = ROOT / "tests"
PORTFOLIO_TESTS = PORTFOLIO / "tests"


def main() -> int:
    if not PORTFOLIO.is_dir():
        print("папки проекта сайтов нет — нечего переносить", file=sys.stderr)
        return 1

    agent_tools = {p.name for p in (ROOT / "tools").glob("*.py")}
    portfolio_tools = {p.name for p in
                       (PORTFOLIO / "tools").glob("*.py")} \
        if (PORTFOLIO / "tools").is_dir() else set()

    print("=== ищем тесты, которым нужен уехавший инструмент ===")
    moved = 0
    for test in sorted(AGENT_TESTS.rglob("test_*.py")):
        try:
            body = test.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Инструмент подгружается по имени файла рядом со словом tools.
        needed = {m.group(1) for m in re.finditer(r"TOOLS\s*/\s*[\"']?([a-z0-9_]+\.py)", body)}
        missing = needed & portfolio_tools
        if not missing:
            continue

        target = PORTFOLIO_TESTS / test.relative_to(AGENT_TESTS)
        print(f"  {test.name:<34} нужен {', '.join(sorted(missing))}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(test), str(target))
        moved += 1

    print()
    print(f"перенесено тестов: {moved}")

    # Проверка: агент больше не падает на сборе.
    print()
    print("=== проверка сбора тестов агента ===")
    import subprocess
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    result = subprocess.run(
        [str(python), "-m", "pytest", "--collect-only", "-q"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600)
    tail = (result.stdout or result.stderr).strip().splitlines()
    for line in tail[-3:]:
        print(f"  {line}")
    if "error" in (result.stdout + result.stderr).lower():
        print("  СБОР ВСЁ ЕЩЁ ПАДАЕТ")
        return 1
    print("  сбор проходит")
    return 0


if __name__ == "__main__":
    sys.exit(main())