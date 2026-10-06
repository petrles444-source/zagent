"""Вытащить CSS выбранных эффектов из ref-design в отдельный файл для сверки."""
import re
from pathlib import Path

SRC = Path("ref-design/src/data/effects.ts")
OUT = Path("docs/ref-components.css")

# id в ref-design не совпадают с именами на сайте — сначала ищем по name.
WANT_BY_NAME = {
    "Ring Spinner": None,
    "Progress Bar Loader": None,
    "Icon Swap Button": None,
    "Glow Border Card": None,
    "Shimmer Text": None,
    "Status Badge": None,
    "iOS Switch": None,
    "Search Input": None,
    "Striped Progress": None,
}

text = SRC.read_text(encoding="utf-8")

lines = text.splitlines()
for name in WANT_BY_NAME:
    for index, line in enumerate(lines):
        if f'name: "{name}"' not in line:
            continue
        for back in range(max(0, index - 3), index):
            if "id:" in lines[back]:
                match = re.search(r'id: "([^"]+)"', lines[back])
                if match:
                    WANT_BY_NAME[name] = match.group(1)
        break

blocks = []
for name, slug in WANT_BY_NAME.items():
    if not slug:
        blocks.append(f"/* {name}: НЕ НАЙДЕН */")
        continue
    start = text.find(f'id: "{slug}"')
    if start < 0:
        blocks.append(f"/* {name} ({slug}): НЕ НАЙДЕН */")
        continue
    css_at = text.find("css: `", start)
    css_end = text.find("`", css_at + 6)
    html_at = text.find("html: `", start)
    html_end = text.find("`", html_at + 7)
    bg = re.search(r'bg: "(\w+)"', text[start:css_at])
    blocks.append(
        f"/* ===== {name}  id={slug}  bg={bg.group(1) if bg else '?'} =====\n"
        f"HTML: {text[html_at + 7:html_end].strip()}\n"
        f"{text[css_at + 6:css_end].rstrip()}\n"
    )

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(blocks), encoding="utf-8")
print(f"записано: {OUT} ({len(OUT.read_text(encoding='utf-8').splitlines())} строк)")
