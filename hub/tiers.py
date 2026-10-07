"""Приоритеты моделей: ранжирование по качеству, скорости и специализации.

Идея: в режиме `auto` агент берёт лучшую доступную модель и переключается на
следующую по убыванию приоритета, когда текущая упала (лимит, сеть, блокировка).

Приоритет задаётся в config/tiers.json вручкой и дополняется замерами:

    tier          1 — лучшие (большие MoE, сильные флагманы)
                  5 — запасные (мелкие модели, keyless-шлюзы)
    vision        умеет принимать изображения — фильтр, а не достоинство
    tools         поддерживает вызов инструментов
    notes         человекочитаемая причина ранга

**Скорость входит в ранг наравне с его номером.** Не выдумывается, а
измеряется: модель, которая отвечает полминуты, не «немного медленнее»,
она делает задачу невозможной, и её место вверху списка — ошибка конфига,
а не предпочтение.

Модели, которых нет в tiers.json, ранжируются эвристикой по имени и шлюзу.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Писатели лежат в config.py: он владеет форматом файлов, а tiers.json —
# лишь один из них. Цикла нет: config ни откуда не импортируется.
from hub.config import (
    ConfigWriteError,
    atomic_write,
    clean_model_id,
    clean_secret_name,
    detect_indent,
)

TIERS_FILE = "tiers.json"

#: Сколько секунд задержки «стоят» одного шага ранга. Число выбрано по
#: замеру: `meta/llama-3.2-90b-vision-instruct` отвечает за 32.7 секунды,
#: и при 2.0 она уходит ниже всех рангом 3 — то есть туда, где место
#: модели, которая сработает, если ничего лучше не осталось.
TIER_COST_S = 2.0

#: Задержка, которую получает модель, которую ещё ни разу не звали.
#: Не «лучшая из всех», а средняя: иначе непроверенная модель обгоняет
#: заведомо быстрые и оборачивается минутой ожидания на первом шаге.
UNKNOWN_LATENCY_S = 2.0

#: Сколько «штрафных рангов» стоит полный провал модели (доля отказов = 1).
#:
#: Ненадёжность сопоставима по весу с провайдерским рангом, а не с
#: задержкой: модель, не ответившая ни разу, уходит ниже двух соседних
#: рангов, но остаётся в списке — выкидывать её целиком дело карантина,
#: а выбор ранга — сообщать, что брать в первую очередь.
UNRELIABLE_COST = 2.0


@dataclass
class ModelSpec:
    """Паспорт модели: ранг и capabilities."""

    gateway: str
    model: str
    tier: int = 5
    vision: bool = False
    tools: bool = True
    notes: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.gateway}/{self.model}"

    @property
    def rank(self) -> tuple[int, str]:
        """Ключ сортировки: меньше — лучше."""
        return (self.tier, self.model)


#: Признаки vision-моделей в имени.
_VISION_HINTS = ("vl", "vision", "omni", "-vl", "multimodal", "pixtral", "llava", "ocr")

#: Признаки сильных моделей: чем крупнее число параметров, тем выше ранг.
_STRONG_HINTS = (
    (r"ultra.*(\d{3})b", 1),
    (r"(\d{3})b", 1),
    (r"120b|550b|397b|235b|70b|32b", 2),
    (r"\b(27|30)b", 3),
    (r"\b(8|9|20|22)b", 4),
    (r"\b(3|4|7)b", 5),
)


def _has_vision_hint(model: str) -> bool:
    low = model.lower()
    return any(h in low for h in _VISION_HINTS)


def guess_tier(model: str, gateway: str) -> int:
    """Эвристический ранг для модели, которой нет в tiers.json."""
    low = model.lower()

    # Локальный рантайм и keyless-шлюзы — по умолчанию внизу: там либо мелкие
    # модели, либо жёсткие анонимные лимиты.
    if gateway == "ollama":
        return 4
    if gateway in ("llm7", "zen"):
        return 4

    for pattern, tier in _STRONG_HINTS:
        if re.search(pattern, low):
            return tier

    # Флагманы без числа в имени.
    if any(h in low for h in ("ultra", "max", "opus", "pro")):
        return 2
    if any(h in low for h in ("flash", "lite", "nano", "mini", "instant")):
        return 4
    return 3


class TierBook:
    """Загруженный и нормализованный config/tiers.json."""

    def __init__(self, specs: dict[tuple[str, str], ModelSpec]) -> None:
        self._specs = specs

    def __len__(self) -> int:
        return len(self._specs)

    @classmethod
    def empty(cls) -> "TierBook":
        """Книга без единого паспорта — ранги выводятся по названию модели.

        Нужна там, где перебор паспортов неуместен: в проверках и при работе
        без файла конфигурации.
        """
        return cls({})

    @classmethod
    def load(cls, root: str | Path | None = None) -> "TierBook":
        base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
        path = base / "config" / TIERS_FILE
        specs: dict[tuple[str, str], ModelSpec] = {}
        if not path.is_file():
            return cls(specs)

        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("models") or data.get("tiers") or []
        for item in entries:
            if not isinstance(item, dict):
                continue
            gateway = str(item.get("gateway") or "").strip()
            model = str(item.get("model") or "").strip()
            if not gateway or not model:
                continue
            specs[(gateway, model)] = ModelSpec(
                gateway=gateway,
                model=model,
                tier=int(item.get("tier") or 5),
                vision=bool(item.get("vision", _has_vision_hint(model))),
                tools=bool(item.get("tools", True)),
                notes=str(item.get("notes") or ""),
                tags=[str(t) for t in (item.get("tags") or [])],
            )
        return cls(specs)

    def get(self, gateway: str, model: str) -> ModelSpec:
        """Паспорт модели: из конфига, иначе по эвристике."""
        spec = self._specs.get((gateway, model))
        if spec is not None:
            return spec
        return ModelSpec(
            gateway=gateway,
            model=model,
            tier=guess_tier(model, gateway),
            vision=_has_vision_hint(model),
        )

    def specs(self) -> list[ModelSpec]:
        """Все явные паспорта, отсортированные по рангу."""
        return sorted(self._specs.values(), key=lambda s: s.rank)

    def tier_of(self, gateway: str, model: str) -> int:
        return self.get(gateway, model).tier


def rank_models(
    models: list[Any],
    tierbook: TierBook,
    *,
    require_vision: bool = False,
    require_tools: bool = False,
    prefer_speed: bool = False,
    latencies: dict[str, float] | None = None,
    unreliable: dict[str, float] | None = None,
    speed_weight: float = TIER_COST_S,
) -> list[Any]:
    """Отсортировать модели по приоритету для режима auto.

    models: список FreeModel из hub.registry.
    require_vision: оставить только модели, умеющие изображения.
    require_tools: оставить только модели с вызовом инструментов.
    prefer_speed: скорость учитывается вдвое строже.
    latencies: ref -> задержка последнего ответа, в секундах.
    unreliable: ref -> доля отказов по истории (0..1).
    speed_weight: сколько секунд задержки «стоят» одного шага ранга.

    **Скорость входит в ранг, а не только разбирает ничьи.**

    Раньше порядок задавался почти исключительно номером ранга, и модель с
    задержкой 32 секунды стояла выше всех, если её кто-то назвал рангом 1.
    Для агента это худший выбор: она не «медленная», она делает задачу
    невозможной — человек успевает уйти и вернуться, а лимит уже выбит.

    Теперь ранг складывается из качества и задержки: задержка делится на
    speed_weight и прибавляется к номеру ранга. Модель на 2 секунды быстрее
    другой поднимается примерно на ранг, а модель на 30 секунд уходит под
    все ранги второго и третьего. Ранг и задержка сопоставимы по весу, а не
    «ранг главное, остальное вторично».

    Умение видеть — фильтр, а не достоинство. Если задача с картинкой,
    vision-модели остаются, но не лезут в начало списка, где им не место.

    Надёжность входит в ранг тем же слагаемым, что и ранг провайдера.
    Раньше история отказов на выбор не влияла вовсе: `ok_count` писался в
    базу, а читал никто, и модель, отдающая лимит через раз, стояла наравне
    со стабильной — каждый хоп начинался с её пробного запроса.
    """
    latencies = latencies or {}
    unreliable = unreliable or {}
    kept: list[Any] = []

    for model in models:
        spec = tierbook.get(model.gateway_id, model.model_id)
        if require_vision and not spec.vision:
            continue
        if require_tools and not spec.tools:
            continue
        kept.append(model)

    def latency_of(model: Any) -> float:
        """Задержка в секундах; неизвестная — средняя, а не лучшая.

        Иначе модель, которую ни разу не позвали, выглядит быстрее всех
        проверенных, и первое же её использование оборачивается минутой
        ожидания уже на первом шаге задачи.
        """
        seconds = latencies.get(model.ref)
        return float(seconds) if seconds else UNKNOWN_LATENCY_S

    def score(model: Any) -> tuple[float, str]:
        tier = tierbook.tier_of(model.gateway_id, model.model_id)
        weight = speed_weight / (2.0 if prefer_speed else 1.0)
        penalty = unreliable.get(model.ref, 0.0) * UNRELIABLE_COST
        return (tier + latency_of(model) / weight + penalty, model.model_id)

    return sorted(kept, key=score)


# ================================================================ запись
#
# Правка config/tiers.json из интерфейса (вкладка «Настройки»). Значений
# ключей здесь нет по построению — только ссылки на шлюз и модель.


def edit_model(
    gateway: Any,
    model: Any,
    *,
    action: str = "add",
    tier: Any = None,
    notes: Any = "",
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Добавить паспорт модели в tiers.json или убрать его.

    Без явного tier ранг достаётся из guess_tier() по имени — тот же
    приём, которым TierBook() оценивает модели, не занесённые в файл.
    """
    if action not in ("add", "remove"):
        raise ConfigWriteError(f"Неизвестное действие «{action}»")

    gid = clean_secret_name(gateway)
    m = clean_model_id(model)
    if action == "add":
        if tier is None:
            rank = guess_tier(m, gid)
        else:
            try:
                rank = int(tier)
            except (TypeError, ValueError) as exc:
                raise ConfigWriteError(
                    f"Приоритет должен быть числом 1–5, а не «{tier}»"
                ) from exc
            if not 1 <= rank <= 5:
                raise ConfigWriteError(f"Приоритет {rank} вне шкалы 1–5")
        note = str(notes or "").strip()
        if len(note) > 400:
            raise ConfigWriteError("Заметка длиннее 400 знаков")

    path = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    path = path / "config" / TIERS_FILE
    text = path.read_text(encoding="utf-8") if path.is_file() else "{}\n"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigWriteError(f"Некорректный JSON в {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigWriteError(f"В {path} ожидался объект")
    entries = data.get("models")
    if not isinstance(entries, list):
        entries = []
        data["models"] = entries

    index = next(
        (
            i for i, item in enumerate(entries)
            if isinstance(item, dict)
            and str(item.get("gateway")) == gid
            and str(item.get("model")) == m
        ),
        None,
    )

    if action == "add":
        entry = {
            "gateway": gid,
            "model": m,
            "tier": rank,
            "vision": _has_vision_hint(m),
            "tools": True,
            "notes": note,
        }
        if index is None:
            entries.append(entry)
            change = "added"
        else:
            entries[index] = {**entries[index], **entry}
            change = "updated"
        result: dict[str, Any] = {
            "ok": True, "action": action, "gateway": gid, "model": m,
            "tier": rank, "changed": change, "total": len(entries),
        }
    else:
        if index is None:
            return {
                "ok": False, "action": action, "gateway": gid, "model": m,
                "error": "Такой модели нет в tiers.json", "total": len(entries),
            }
        entries.pop(index)
        result = {
            "ok": True, "action": action, "gateway": gid, "model": m,
            "removed": 1, "total": len(entries),
        }

    indent: int | str = detect_indent(text) if path.is_file() else 2
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n")
    return result
