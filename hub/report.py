"""Формирование отчётов по реестру и статусам моделей.

Выводит таблицы в консоль и сохраняет их в docs/:
    docs/free-models.json   — машинный реестр (для других инструментов)
    docs/free-models.md     — человекочитаемая сводка
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hub.registry import Registry

CATALOG_JSON = Path("docs") / "free-models.json"
CATALOG_MD = Path("docs") / "free-models.md"

STATUS_OK = "ok"
STATUS_SLOW = "slow"
STATUS_EMPTY = "empty"
STATUS_LIMITED = "limited"
STATUS_BLOCKED = "blocked"
STATUS_DOWN = "down"
STATUS_SKIPPED = "skipped"
STATUS_NOTE = "note"

#: Статусы, при которых модель считается пригодной к использованию.
ALIVE_STATUSES = (STATUS_OK, STATUS_SLOW, STATUS_LIMITED, STATUS_EMPTY)

#: Статусы, из-за которых модель не стоит использовать вообще.
DEAD_STATUSES = (STATUS_BLOCKED, STATUS_DOWN)

SLOW_AFTER_MS = 5000


def classify(result: dict[str, Any] | None, *, slow_after_ms: int = SLOW_AFTER_MS) -> str:
    """Итоговый статус модели из результата живого пинга."""
    if result is None:
        return STATUS_SKIPPED
    status = str(result.get("status") or "")
    if status == STATUS_OK and int(result.get("duration_ms") or 0) >= slow_after_ms:
        return STATUS_SLOW
    return status or STATUS_SKIPPED


def build_snapshot(
    registry: Registry,
    probes: dict[str, dict[str, Any]] | None = None,
    *,
    slow_after_ms: int = SLOW_AFTER_MS,
) -> dict[str, Any]:
    """Собрать машинный снимок реестра для docs/free-models.json."""
    probes = probes or {}
    entries: list[dict[str, Any]] = []
    notes: list[str] = []
    for ref, probe in (probes or {}).items():
        if ref.endswith("/*") and probe.get("status") == STATUS_NOTE:
            notes.append(f"{ref[:-2]}: {probe.get('error')}")

    for model in registry.chat_models:
        gateway = next((g for g in registry.gateways if g["id"] == model.gateway_id), {})
        probe = probes.get(model.ref)
        entry = model.to_dict()
        status = classify(probe, slow_after_ms=slow_after_ms)
        entry.update(
            gateway_label=gateway.get("label", model.gateway_id),
            base_url=gateway.get("base_url"),
            status=status,
            usable=status in ALIVE_STATUSES,
        )
        if probe:
            entry.update(
                duration_ms=probe.get("duration_ms"),
                tokens_in=probe.get("tokens_in"),
                tokens_out=probe.get("tokens_out"),
                cost=probe.get("cost"),
                sample=probe.get("sample"),
                error=probe.get("error"),
                retried=probe.get("retried"),
            )
        entries.append(entry)

    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_chat_models": len(entries),
        "status_counts": counts,
        "notes": notes,
        "gateways": [
            {
                "id": g["id"],
                "label": g.get("label"),
                "base_url": g.get("base_url"),
                "needs_key": g.get("needs_key"),
                "has_key": g.get("has_key"),
                "supports_responses": g.get("supports_responses"),
                "verified": g.get("verified"),
                "notes": g.get("notes"),
                "error": registry.errors.get(g["id"]),
            }
            for g in registry.gateways
        ],
        "models": entries,
        "errors": registry.errors,
    }


def write_json(snapshot: dict[str, Any], root: str | Path | None = None) -> Path:
    """Записать docs/free-models.json."""
    base = Path(root) if root is not None else _project_root()
    path = base / CATALOG_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_markdown(snapshot: dict[str, Any], root: str | Path | None = None) -> Path:
    """Записать docs/free-models.md."""
    base = Path(root) if root is not None else _project_root()
    path = base / CATALOG_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(snapshot), encoding="utf-8")
    return path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def render_markdown(snapshot: dict[str, Any]) -> str:
    """Человекочитаемая сводка по шлюзам и моделям."""
    lines: list[str] = []
    counts = snapshot.get("status_counts") or {}
    total = snapshot.get("total_chat_models", 0)
    alive = sum(counts.get(status, 0) for status in ALIVE_STATUSES)

    lines.append("# Бесплатные модели через API — живой каталог")
    lines.append("")
    lines.append(
        f"Обновлено: **{snapshot.get('generated_at')}**. "
        f"Чат-моделей: **{total}**, пригодных: **{alive}**."
    )
    lines.append("")
    if counts:
        parts = [f"`{k}` — {v}" for k, v in sorted(counts.items())]
        lines.append("Статусы: " + ", ".join(parts) + ".")
        lines.append("")

    for note in snapshot.get("notes") or []:
        lines.append(f"> {note}")
    if snapshot.get("notes"):
        lines.append("")

    lines.append("## Шлюзы")
    lines.append("")
    lines.append("| Шлюз | Base URL | Ключ | /responses | Моделей | Пригодных |")
    lines.append("|---|---|---|---|---|---|")
    for gateway in snapshot.get("gateways", []):
        models = [m for m in snapshot.get("models", []) if m.get("gateway") == gateway["id"]]
        good = sum(1 for m in models if m.get("usable"))
        key_state = (
            "не нужен" if not gateway.get("needs_key") else ("есть" if gateway.get("has_key") else "нет")
        )
        responses = "да" if gateway.get("supports_responses") else "нет"
        lines.append(
            f"| {gateway.get('label')} | `{gateway.get('base_url')}` | {key_state} | "
            f"{responses} | {len(models)} | {good} |"
        )
    lines.append("")
    lines.append(
        "Ключи берутся из `config/secrets.local.json` или переменных окружения "
        "(имя = `ZAGENT_<ID>_API_KEY`). В репозиторий ключи не попадают."
    )
    lines.append("")

    lines.append("## Модели")
    lines.append("")
    lines.append("| Модель | Шлюз | Статус | Время | Токены | Контекст | Источник |")
    lines.append("|---|---|---|---|---|---|---|")
    for model in snapshot.get("models", []):
        duration = model.get("duration_ms")
        duration_text = f"{duration / 1000:.1f}s" if isinstance(duration, int) else "—"
        tokens = (
            f"{model.get('tokens_in', 0)}+{model.get('tokens_out', 0)}"
            if isinstance(duration, int)
            else "—"
        )
        context = model.get("context")
        context_text = f"{context // 1000}K" if isinstance(context, int) and context else "—"
        retried = " (повтор)" if model.get("retried") else ""
        lines.append(
            f"| `{model.get('model')}` | {model.get('gateway_label')} | {model.get('status')}{retried} | "
            f"{duration_text} | {tokens} | {context_text} | {model.get('source')} |"
        )
    lines.append("")

    lines.append("## Как использовать")
    lines.append("")
    lines.append("```bash")
    lines.append("# обновить каталог и статусы")
    lines.append("python tools/cli.py ping --write")
    lines.append("")
    lines.append("# конфиги для других инструментов")
    lines.append("python tools/cli.py export opencode --verified-only > opencode.jsonc")
    lines.append("python tools/cli.py export codex --verified-only")
    lines.append("python tools/cli.py export zed --verified-only")
    lines.append("python tools/cli.py export cline --verified-only")
    lines.append("")
    lines.append("# спросить модель")
    lines.append('python tools/cli.py ask "напиши тест на pytest" --gateway groq')
    lines.append('python tools/cli.py swarm "сравни подходы" --gateway openrouter --limit 5')
    lines.append("```")
    lines.append("")
    lines.append(
        "Ключи в экспортируемые конфиги не попадают — вместо них имена переменных окружения."
    )
    lines.append("")

    lines.append("## Что означают статусы")
    lines.append("")
    lines.append("| Статус | Значение |")
    lines.append("|---|---|")
    for status, meaning in LEGEND.items():
        lines.append(f"| `{status}` | {meaning} |")
    lines.append("")

    errors = snapshot.get("errors") or {}
    if errors:
        lines.append("## Ошибки сбора")
        lines.append("")
        for key, message in sorted(errors.items()):
            lines.append(f"- `{key}` — {message}")
        lines.append("")

    return "\n".join(lines)


def render_table(snapshot: dict[str, Any], *, only_statuses: tuple[str, ...] | None = None) -> str:
    """Компактная таблица для консоли."""
    models = snapshot.get("models", [])
    if only_statuses:
        models = [m for m in models if m.get("status") in only_statuses]
    if not models:
        return "Нет моделей для отображения."

    width = max(len(str(m.get("model"))) for m in models) + 2
    lines = []
    for model in models:
        duration = model.get("duration_ms")
        duration_text = f"{duration / 1000:.1f}s" if isinstance(duration, int) else "  —  "
        detail = _detail(model)
        lines.append(
            f"{str(model.get('model')):<{width}}{str(model.get('status')):<8}"
            f"{model.get('gateway'):<12}{duration_text:>7}  {detail}"
        )
    return "\n".join(lines)


def _detail(model: dict[str, Any]) -> str:
    status = model.get("status")
    if status in (STATUS_OK, STATUS_SLOW):
        suffix = " (повтор)" if model.get("retried") else ""
        return f"tokens: {model.get('tokens_in', 0)}+{model.get('tokens_out', 0)}{suffix}"
    if status == STATUS_EMPTY:
        return "пустой ответ (reasoning съел max_tokens)"
    if status == STATUS_LIMITED:
        return "лимит 429 — повторить позже"
    if status == STATUS_BLOCKED:
        return "доступ закрыт провайдером — не использовать"
    error = model.get("error") or "нет данных"
    http = model.get("http")
    return f"HTTP {http} · {error}" if http else str(error)


LEGEND = {
    STATUS_OK: "отвечает",
    STATUS_SLOW: "отвечает медленно",
    STATUS_EMPTY: "пустой ответ (reasoning съел max_tokens)",
    STATUS_LIMITED: "лимит запросов исчерпан, повторить позже",
    STATUS_BLOCKED: "доступ закрыт провайдером, не использовать",
    STATUS_DOWN: "недоступна",
    STATUS_SKIPPED: "не проверялась",
}


def render_legend() -> str:
    """Пояснение статусов — печатается под таблицей."""
    lines = ["Статусы:"]
    for status, meaning in LEGEND.items():
        lines.append(f"  {status:<8} {meaning}")
    return "\n".join(lines)


def render_summary(snapshot: dict[str, Any]) -> str:
    """Итоговая строка: сколько моделей пригодно к использованию."""
    counts = snapshot.get("status_counts") or {}
    total = snapshot.get("total_chat_models", 0)
    alive = sum(counts.get(status, 0) for status in ALIVE_STATUSES)
    parts = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    head = f"Пригодных моделей: {alive} из {total}"
    return f"{head} ({parts})" if parts else head
