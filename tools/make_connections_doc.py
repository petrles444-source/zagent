r"""Сделать справку по подключениям ко всем моделям — отдельным файлом.

Зачем
----
Человек просил: «ботам нужна информация по подключению ко всем
моделям из агента. И так далее. Дублируй всю информацию по
подключениям».

Причина в том, как устроен репозиторий. Подключения живут в
`config/gateways.json`, а боты на сервере этот файл не видят: там
другой набор файлов, и добраться до папки агента бот не может.
Значит справка должна лежать рядом с каждым, кому она нужна.

Секреты сюда не попадают и не попадут. Пишутся адреса, имена
переменных окружения и то, где лежит ключ, — но не сам ключ.
Иначе файл, повторённый в пяти местах, стал бы утечкой в пяти
местах сразу.

Запуск:
    .venv\\Scripts\\python.exe tools\\make_connections_doc.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAYS = ROOT / "config" / "gateways.json"
MODELS = ROOT / "config" / "models.json"

#: Куда копируется. Не одна папка, а четыре: боты, сайты, утилиты и
#: сам агент. Файл маленький, а пользуются им все.
COPIES = (
    ROOT / "ПОДКЛЮЧЕНИЯ.md",
    ROOT / "bots" / "ПОДКЛЮЧЕНИЯ.md",
    ROOT / "sites" / "ПОДКЛЮЧЕНИЯ.md",
    ROOT / "utils" / "ПОДКЛЮЧЕНИЯ.md",
    ROOT / "hosting" / "pythonanywhere" / "ПОДКЛЮЧЕНИЯ.md",
)

HEADER = """# Подключения к моделям

Справка о том, к каким сервисам можно ходить и где лежат ключи.

**Секретов здесь нет.** Написаны адреса, имена переменных окружения
и то, где искать ключ. Сами ключи лежат в двух местах, и оба в
`.gitignore`:

* `config/secrets.local.json` — ключи агента;
* `hosting/pythonanywhere/credentials.json` — доступ к хостингу.

Файл намеренно продублирован в несколько папок. Боты на сервере
папку агента не видят, поэтому справка должна лежать рядом с тем,
кто её читает. Копия ничего не добавляет и не утекает: секретов
в ней нет по определению.

"""


def build() -> str:
    lines = [HEADER]

    # Шлюзы.
    if GATEWAYS.is_file():
        data = json.loads(GATEWAYS.read_text(encoding="utf-8"))
        gateways = data.get("gateways") or []
        lines.append("## Сервисы\n")
        lines.append("| Ключ | Название | Адрес | Переменная | Нужен ключ |")
        lines.append("|---|---|---|---|---|")
        for item in gateways:
            if not isinstance(item, dict):
                continue
            env = item.get("env") or "—"
            needs = "да" if item.get("needs_key") else "нет"
            secret = item.get("secret_key")
            where = (f" (`{secret}`)" if secret else "")
            lines.append(
                f"| `{item.get('id')}` | {item.get('label')} | "
                f"`{item.get('base_url')}` | `{env}`{where} | {needs} |")
        lines.append("")

    # Модели по умолчанию.
    if MODELS.is_file():
        data = json.loads(MODELS.read_text(encoding="utf-8"))
        base = data.get("base_url")
        models = data.get("models") or []
        lines.append("## Модели по умолчанию\n")
        if base:
            lines.append(f"Адрес по умолчанию: `{base}`\n")
        if models:
            lines.append("| Идентификатор | Название |")
            lines.append("|---|---|")
            for item in models:
                if not isinstance(item, dict):
                    continue
                lines.append(f"| `{item.get('id')}` | {item.get('label')} |")
            lines.append("")

    lines.append("""## Как бот ходит в модель

Боты на хостинге работают через OpenRouter:

* адрес: `https://openrouter.ai/api/v1`
* модель подбирается проверкой, а не зашивается в код — каталог
  меняется быстрее кода;
* ключ лежит в `config/secrets.local.json` агента, копия попадает в
  `config.json` на сервере при настройке.

Почему модель не зашита. Раньше в коде стояла
`anthropic/claude-3.5-haiku`. Её убрали из каталога, проверка ключей
стала получать 404, и все девять ключей объявлялись мёртвыми — хотя
были живы: отказ приходил на модель, а виноваты оказывались ключи.
Теперь кандидатов четыре, и берётся первый отвечающий.

## Как проверить, что ключ живой

```bash
python tools/check_env.py
```

Скрипт печатает «есть» или «нет» и никогда не показывает ключ
целиком.

## Что делать, если модель перестала отвечать

1. Проверить ключ через `/key` — это не зависит от каталога моделей;
2. Если ключ жив, взять другую модель из списка кандидатов;
3. Если не жив — выпустить новый и положить в `secrets.local.json`.
""")
    return "\n".join(lines)


def main() -> int:
    text = build()
    for target in COPIES:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"  записан {target.relative_to(ROOT)}")
    print(f"\nразмер: {len(text)} символов, копий: {len(COPIES)}")

    # Проверка, что секрет случайно не попал в текст.
    import re
    leaks = re.findall(r"\b(?:sk-or-|sk-|ghp_|cfut_)[A-Za-z0-9_\-]{10,}", text)
    if leaks:
        print(f"  ВНИМАНИЕ: в справке видно {len(leaks)} ключей!", file=sys.stderr)
        return 1
    print("  ключей в тексте нет — проверено")
    return 0


if __name__ == "__main__":
    sys.exit(main())