#!/usr/bin/env python
"""Проверить, что в индексе git нет настоящих ключей.

Зачем это отдельным скриптом. `.gitignore` закрывает
`config/secrets.local.json`, но утекает не только этот файл: ключ может
попасть в тест, в пример в README, в отчёт стенда или в сообщение об
ошибке, которое кто-то скопировал в issue. Найти это вручную по `git grep`
надёжно нельзя — глаз пропускает, а регулярка без образцов ключей тем
более.

Скрипт делает две вещи, и обе нужны:

1. **по образцу** — ищет в индексе строки, похожие на ключи известных
   провайдеров. Это находит случайную утечку, о которой никто не знает;
2. **сверкой с секретами** — берёт настоящие ключи из
   `config/secrets.local.json` и ищет их буквально. Это находит ключ,
   спрятанный под непохожим именем.

Проверяется только индекс (`git ls-files`), а не все файлы на диске:
незакоммиченные черновики в публичный репозиторий не попадут.

Запуск:
    .venv\\Scripts\\python.exe tools\\check_secrets.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: Узнаваемая форма ключей по провайдерам. Длина завышена намеренно: под
#: образец попадают и настоящие ключи, и тестовые заглушки, а их придётся
#: разобрать глазами — это безопасно. Обратная ситуация опаснее: короткий
#: образец пропустит ключ с лишним символом.
SHAPES = {
    "openrouter": r"sk-or-v1-[A-Za-z0-9]{40,}",
    "groq": r"gsk_[A-Za-z0-9]{40,}",
    "nvidia": r"nvapi-[A-Za-z0-9_-]{40,}",
    "mistral": r"mstrl_[A-Za-z0-9]{24,}",
    "cloudflare_token": r"cfut_[A-Za-z0-9_-]{24,}",
    "z_ai": r"\b[0-9a-f]{32}\.[A-Za-z0-9]{24,}",
}

#: Файлы, где ключ — часть проверки, а не утечка. Исключение узкое: если
#: в тесте окажется настоящий ключ, исключение его спрячет.
ALLOWED = {
    "config/secrets.local.json.example",
    "tools/check_secrets.py",
}

#: Похожие на ключ строки в тестах — заглушки. Их видно, но перепроверять
#: стоит: в测试 копируется настоящий ключ чаще, чем кажется.
STUB_HINT = re.compile(r"(abc|000|111|222|0123456789|deadbeef|example|test|"
                       r"xxxx|placeholder|dummy|fake)", re.I)


def indexed_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         encoding="utf-8")
    if out.returncode != 0:
        print("Не удалось прочитать индекс git:", out.stderr.strip())
        return []
    return [line for line in out.stdout.splitlines() if line]


def real_secrets() -> list[str]:
    """Настоящие ключи из локального файла секретов."""
    path = Path(__file__).resolve().parent.parent / "config" / "secrets.local.json"
    if not path.is_file():
        return []
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for value in raw.values():
        if isinstance(value, str):
            found.append(value.strip())
        elif isinstance(value, list):
            found.extend(str(v).strip() for v in value)
    return [v for v in found if len(v) >= 20]


def scan_shape(files: list[str]) -> list[tuple[str, str, str]]:
    hits: list[tuple[str, str, str]] = []
    for name in files:
        if name in ALLOWED:
            continue
        try:
            text = Path(name).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for provider, pattern in SHAPES.items():
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append((name, str(line), provider))
    return hits


def scan_exact(files: list[str], secrets: list[str]) -> list[tuple[str, str]]:
    """Найти настоящие ключи буквально. Это главная проверка."""
    hits: list[tuple[str, str]] = []
    for name in files:
        if name in ALLOWED:
            continue
        try:
            text = Path(name).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for secret in secrets:
            if secret in text:
                hits.append((name, secret[:8] + "…"))
    return hits


def main() -> int:
    files = indexed_files()
    print(f"Файлов в индексе: {len(files)}")

    secrets = real_secrets()
    print(f"Настоящих ключей известно: {len(secrets)}")

    exact = scan_exact(files, secrets)
    shaped = scan_shape(files)

    print("\n1. Сверка с настоящими ключами")
    if exact:
        print(f"   НАЙДЕНО: {len(exact)}")
        for name, who in exact[:20]:
            print(f"     {name}  ({who})")
    else:
        print("   чисто — ни одного настоящего ключа в индексе")

    print("\n2. Похожие на ключи по форме")
    real: list[tuple[str, str, str]] = []
    stubs: list[tuple[str, str, str]] = []
    for name, line, provider in shaped:
        try:
            text = Path(name).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            stubs.append((name, line, provider))
            continue
        chunk = text.splitlines()[int(line) - 1] if text.splitlines() else ""
        (stubs if STUB_HINT.search(chunk) else real).append((name, line, provider))
    if real:
        print(f"   БЕЗ ПРИЗНАКА ЗАГЛУШКИ: {len(real)} — проверьте глазами")
        for name, line, provider in real[:20]:
            print(f"     {name}:{line}  ({provider})")
    else:
        print("   все похожие строки помечены как заглушки")
    print(f"   из них заглушек: {len(stubs)}")

    return 1 if exact or real else 0


if __name__ == "__main__":
    sys.exit(main())