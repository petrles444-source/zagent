"""Найти жёстко заданные цвета в CSS компонентов (вне блока тем)."""
import re
from pathlib import Path

src = Path("hub/ui.py").read_text(encoding="utf-8")
css = src.partition("</style>")[0]
lines = css.splitlines()

# Граница: блок тем заканчивается на строке с --sans (после последней темы).
# Всё, что ниже — компоненты и каркас, где цвет должен идти из токена.
start = next(i for i, line in enumerate(lines) if "--sans:" in line)

found = []
for number, line in enumerate(lines[start:], start=start + 1):
    for match in re.finditer(r"#[0-9a-fA-F]{3,8}\b", line):
        found.append((number, match.group(0), line.strip()[:80]))

print(f"строк компонентов: {len(lines) - start}")
print(f"жёстких цветов: {len(found)}")
for number, color, text in found:
    print(f"{number:5} {color:9} {text}")
