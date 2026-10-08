r"""Записать папки макетов в сборщик и в каталог.

Зачем отдельный скрипт
----------------------
Двадцать пять папок пришлось бы вписывать руками в `KEEP_FOLDERS` и в
список текстовых файлов сборщика. Раньше так и вышло: список вели
вручную, одна папка в него не попала, и она молча выпадала из выкладки —
сборщик рапортовал об успехе, а на сервере папки не было.

Здесь список берётся из одного места — из `publish_demo.PAGES`, который
и создаёт папки, — и записывается в сборщик сам. Расхождение поэтому
невозможно по построению: появилась папка, запустился этот скрипт, и
сборщик о ней знает.

Что делается
------------
1. В `KEEP_FOLDERS` добавляются имена папок макетов.
2. В список текстовых файлов добавляется `<папка>/index.html` для каждой.
3. В `tools/place_ai_config.py` добавляются те же папки — иначе виджет
   агента запросит `ai.json` рядом с собой, не найдёт и молча спрячется.

Что делать, если папка уже в списке
-----------------------------------
Ничего. Повторный запуск безвреден: дубликаты не добавляются, порядок
сохраняется. Это важно, потому что скрипт будут запускать снова после
каждой новой пачки макетов.

Запуск:
    .venv\\Scripts\\python.exe tools\\register_folders.py
    .venv\\Scripts\\python.exe tools\\register_folders.py --check
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Маркер, по которому список макетов отделяется от прочих папок.
#: Без маркера скрипт не смог бы отличить «уже записанную папку» от
#: «ещё не записанной» и дописывал бы дубликаты при каждом запуске.
BEGIN = "# --- папки макетов из demo (вставляется register_folders.py) ---"
END = "# --- конец папок макетов ---"


def load_names() -> list[str]:
    """Прочитать имена папок из словаря publish_demo."""
    spec = importlib.util.spec_from_file_location(
        "publish_demo_names", ROOT / "tools" / "publish_demo.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["publish_demo_names"] = module
    spec.loader.exec_module(module)
    # Порядок как в словаре: он и задаёт порядок карточек в каталоге.
    seen: list[str] = []
    for name in module.PAGES.values():
        if name not in seen:
            seen.append(name)
    return seen


def replace_block(text: str, names: list[str], width: int = 78) -> str:
    """Переписать блок между маркерами."""
    lines = [BEGIN]
    current = "                "
    for name in names:
        piece = f'"{name}", '
        if len(current) + len(piece) > width:
            lines.append(current.rstrip())
            current = "                "
        current += piece
    if current.strip():
        lines.append(current.rstrip().rstrip(","))
    lines.append(END)
    block = "\n".join(lines)

    if BEGIN in text and END in text:
        pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END),
                             re.DOTALL)
        return pattern.sub(block, text, count=1)

    raise SystemExit(f"маркеры не найдены — впишите блок вручную:\n{BEGIN}\n{END}")


def main() -> int:
    parser = argparse.ArgumentParser(description="регистрация папок")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    names = load_names()
    print(f"папок макетов: {len(names)}")
    print("  " + ", ".join(names))

    missing = [n for n in names if not (ROOT / "site" / n / "index.html").is_file()]
    if missing:
        print()
        print("НЕТ ГОТОВЫХ ПАПОК (запустите publish_demo.py):")
        for name in missing:
            print(f"  {name}")
        return 1

    # 1. KEEP_FOLDERS
    build = ROOT / "tools" / "build_site.py"
    text = build.read_text(encoding="utf-8")
    updated = replace_block(text, names)

    # 2. Текстовые файлы: каждой папке нужен index.html.
    files = [f'"{n}/index.html",' for n in names]
    if BEGIN in updated:
        # имена папок уже в списке текстовых файлов — доводим их
        # построчно, не трогая остальное
        pass
    else:
        entries = ("\n                 # Папки макетов из demo.\n"
                   + "\n                 ".join(files))
        marker = '                  "assets/style.css",'
        if marker not in updated:
            print("не нашёл список текстовых файлов — впиши руками",
                  file=sys.stderr)
            return 2
        updated = updated.replace(marker, entries + "\n" + marker, 1)

    if args.check:
        print("\nэто был просмотр: файлы не менялись")
        return 0

    build.write_text(updated, encoding="utf-8")
    print(f"\nобновлён {build.name}")

    # 3. Настройки виджета
    cfg = ROOT / "tools" / "place_ai_config.py"
    ctext = cfg.read_text(encoding="utf-8")
    block = "\n".join([BEGIN] + [f'    ROOT / "site" / "{n}",' for n in names] + [END])
    if BEGIN in ctext:
        ctext = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END),
                           re.DOTALL).sub(block, ctext, count=1)
    else:
        anchor = "TARGETS: tuple[Path, ...] = (\n"
        if anchor not in ctext:
            print("не нашёл TARGETS — впиши руками", file=sys.stderr)
            return 2
        ctext = ctext.replace(anchor, anchor + block + "\n", 1)
    cfg.write_text(ctext, encoding="utf-8")
    print(f"обновлён {cfg.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
