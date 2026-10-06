"""Проверить, что интерфейс отдаётся и ключевые куски на месте."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.ui import UI_HTML  # noqa: E402

THEMES = ["dark", "black", "light", "blue", "gray"]
COMPONENTS = {
    "кольцевой спиннер": "ring-rot",
    "полоса прогресса": "bar-sweep",
    "полоса в полоска": "@keyframes stripes",
    "мерцающий текст": "@keyframes shimmer",
    "бейдж статуса": "badge-pulse",
    "переключатель iOS": ".isw",
    "кнопка со сдвигом иконки": ".swapBtn",
    "поле поиска": ".searchWrap",
    "карточка со свечением": ".glowCard",
}

print(f"размер HTML: {len(UI_HTML)} символов")

print("\nТемы:")
for theme in THEMES:
    found = f'[data-theme="{theme}"]' in UI_HTML
    dot = f'data-t="{theme}"' in UI_HTML
    print(f"  {theme:6} определение={'да' if found else 'НЕТ':4} кнопка={'да' if dot else 'НЕТ'}")

print("\nКомпоненты (названия взяты из ref-design):")
for name, marker in COMPONENTS.items():
    print(f"  {name:26} {'найден' if marker in UI_HTML else 'НЕ НАЙДЕН'}")

print("\nШрифты:")
print(f"  Geist подключён:  {'fonts.googleapis.com/css2?family=Geist' in UI_HTML}")
print(f"  запасной системный: {'-apple-system' in UI_HTML}")
print(f"  Geist Mono:        {'Geist+Mono' in UI_HTML}")

print("\nПереключение темы:")
print(f"  setTheme():   {'function setTheme' in UI_HTML}")
print(f"  initTheme():  {'function initTheme' in UI_HTML}")
print(f"  до отрисовки: {UI_HTML.index('zagent.theme') < UI_HTML.index('<body>')}")
print(f"  localStorage: {'localStorage.getItem' in UI_HTML}")

print("\nЖёсткие цвета вне блока тем:")
head, _, css = UI_HTML.partition("</style>")
lines = css.splitlines()
start = next((i for i, l in enumerate(lines) if "--sans:" in l), 0)
hits = []
for number, line in enumerate(lines[start:], start=start + 1):
    for match in re.finditer(r"#[0-9a-fA-F]{3,8}\b", line):
        hits.append((number, match.group(0)))
print(f"  всего: {len(hits)}")
for number, color in hits:
    print(f"    строка {number}: {color}")
