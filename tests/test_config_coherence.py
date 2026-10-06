"""Мёртвый конфиг — не документация, а обман.

Аудит 07.10.2026: в репозитории лежали `config/routing.json`,
`config/routing.json.example` и `config/keys.json.example`, но ни один `.py`
их не открывал. README при этом предлагал скопировать `keys.json.example` в
`keys.json` и «настроить маршрутизацию» — то есть человек заполнял файлы,
которые программа не читает, и ничего не менялось.

Проверяется три независимые вещи:

* файл в `config/` читается программой — или явно помечен в `.gitignore`
  как личный (ключи кладутся вручную и кодом не открываются);
* у каждого `*.example` есть читаемый оригинал;
* README не отправляет к несуществующим файлам.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

#: Откуда читается конфигурация. Тесты не считаем: в них упоминания
#: `/config/gateways.json` — это песочница, а не чтение программы.
SOURCE_DIRS = ("hub", "providers", "tools")


def _sources() -> str:
    chunks: list[str] = []
    for name in SOURCE_DIRS:
        for path in (ROOT / name).rglob("*.py"):
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    for path in ROOT.glob("*.py"):
        chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _personal_configs() -> set[str]:
    """Файлы, которые кладут вручную и код не читает — `.gitignore` говорит сам."""
    patterns = [
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return {
        path.name
        for path in CONFIG.glob("*.json")
        if any(fnmatch.fnmatch(f"config/{path.name}", pat) for pat in patterns)
    }


def test_конфиг_в_config_читается_программой() -> None:
    """Любой json в config/ либо читается, либо это личный файл из .gitignore."""
    sources = _sources()
    personal = _personal_configs()
    ghosts = [
        path.name
        for path in sorted(CONFIG.glob("*.json"))
        if path.name not in personal and path.name not in sources
    ]
    assert not ghosts, (
        "файлы никто не читает — они вводят в заблуждение так же, как "
        f"вводил routing.json: {ghosts}"
    )


def test_у_примера_есть_читаемый_оригинал() -> None:
    """*.example описывает файл, который программа действительно открывает."""
    sources = _sources()
    ghosts = [
        path.name
        for path in sorted(CONFIG.glob("*.example"))
        if path.name[: -len(".example")] not in sources
    ]
    assert not ghosts, (
        "пример ведёт на файл, которого программа не знает: "
        f"{ghosts} — копировать его некуда"
    )


def test_readme_ведёт_на_существующие_файлы() -> None:
    """Инструкция из README обязана работать на чистом клоне."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"`config/([\w.\-]+)`", readme))
    missing = sorted(ref for ref in refs if not (CONFIG / ref).exists())
    assert not missing, f"README указывает на несуществующее: {missing}"
