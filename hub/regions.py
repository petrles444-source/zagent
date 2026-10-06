"""Доступность моделей из конкретной страны.

Зачем это отдельным файлом, а не строчкой в tiers.json: доступность зависит не
от модели, а от того, откуда её зовут. Модель может работать из Москвы и не
работать из Берлина, причём для разных шлюзов по-разному.

Честное измерение, а не догадка. Статус выводится из двух замеров:

    с VPN выключенным модель ответила  ->  RU_OK      работает из России
    без VPN не ответила, с VPN ответила ->  RU_VPN     нужен VPN
    не ответила ни так, ни так          ->  RU_BLOCKED не работает вовсе
    замеров не было                     ->  RU_UNKNOWN не проверяли

Один замер ничего не доказывает: с включённым VPN все шлюзы выглядят
рабочими, поэтому режим замера записывается вместе с результатом и вердикт
собирается только из пары замеров. Файл config/regions.json обновляется
командой `zagent geo`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REGIONS_FILE = "regions.json"

#: Известные режимы замера. VPN включён — проверить «без VPN» не выйдет.
MODE_DIRECT = "direct"   # VPN выключен
MODE_VPN = "vpn"         # VPN включён
MODE_ANY = MODE_DIRECT, MODE_VPN

#: Вердикты.
RU_OK = "ok"              # доступна без VPN
RU_VPN = "vpn"            # нужен VPN
RU_BLOCKED = "blocked"    # не работает даже с VPN
RU_UNKNOWN = "unknown"    # не проверяли

#: Подписи для интерфейса.
RU_LABELS = {
    RU_OK: "РФ без VPN",
    RU_VPN: "нужен VPN",
    RU_BLOCKED: "недоступна",
    RU_UNKNOWN: "не проверено",
}

#: Что показывать рядом с моделью.
RU_MARKS = {
    RU_OK: ("✔", "доступна из России без VPN"),
    RU_VPN: ("🔒", "из России нужен VPN"),
    RU_BLOCKED: ("✘", "недоступна даже с VPN"),
    RU_UNKNOWN: ("?", "не проверено из России"),
}


@dataclass
class RegionNote:
    """Что известно о модели про доступ из конкретной страны."""

    region: str = "ru"
    status: str = RU_UNKNOWN
    #: Чем обосновано: {"direct": "ok", "vpn": "down"} — сырые замеры.
    samples: dict[str, str] = field(default_factory=dict)
    note: str = ""
    checked_at: float = 0.0

    @property
    def usable_direct(self) -> bool:
        """Можно звать из России без VPN."""
        return self.status == RU_OK

    @property
    def needs_vpn(self) -> bool:
        return self.status == RU_VPN

    @property
    def dead(self) -> bool:
        return self.status == RU_BLOCKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "status": self.status,
            "samples": dict(self.samples),
            "note": self.note,
            "checked_at": self.checked_at,
            "label": RU_LABELS.get(self.status, self.status),
        }


def verdict(samples: dict[str, str]) -> str:
    """Вердикт из сырых замеров.

    Правило простое и намеренно консервативное: без замера без VPN нельзя
    сказать, что модель доступна из России, даже если с VPN она отвечает.
    """
    direct = samples.get(MODE_DIRECT)
    vpn = samples.get(MODE_VPN)

    # Модель ответила, если пинг не вернул отказ. «empty» — тоже ответ:
    # reasoning-модель съела max_tokens на размышление, но дошла до сервера.
    if direct and direct != "down":
        return RU_OK
    if direct == "down":
        # Без VPN не отвечает. Отвечает ли с VPN — тогда это VPN, иначе нет.
        return RU_VPN if vpn and vpn != "down" else RU_BLOCKED
    # Прямого замера не было: с VPN отвечает — но доступность из России
    # неизвестна, и утверждать обратное нельзя.
    if vpn and vpn != "down" and MODE_DIRECT not in samples:
        return RU_VPN
    return RU_UNKNOWN


class RegionBook:
    """Загруженный config/regions.json."""

    def __init__(self, notes: dict[str, RegionNote] | None = None,
                 root: str | Path | None = None) -> None:
        self.notes = notes or {}
        self.root = Path(root) if root is not None else Path(__file__).resolve().parent.parent

    @classmethod
    def load(cls, root: str | Path | None = None) -> "RegionBook":
        base = Path(root) if root is not None else Path(__file__).resolve().parent.parent
        path = base / "config" / REGIONS_FILE
        if not path.is_file():
            return cls({}, root=base)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Не заданный файл регионов не должен ломать запуск программы.
            return cls({}, root=base)

        notes: dict[str, RegionNote] = {}
        entries = data.get("models") if isinstance(data, dict) else None
        for ref, entry in (entries or {}).items():
            if not isinstance(entry, dict):
                continue
            samples = entry.get("samples")
            notes[str(ref)] = RegionNote(
                region=str(entry.get("region") or "ru"),
                status=str(entry.get("status") or RU_UNKNOWN),
                samples={str(k): str(v) for k, v in (samples or {}).items()},
                note=str(entry.get("note") or ""),
                checked_at=float(entry.get("checked_at") or 0.0),
            )
        return cls(notes, root=base)

    def get(self, ref: str) -> RegionNote:
        note = self.notes.get(ref)
        if note is None:
            return RegionNote()
        return note

    def status_of(self, ref: str) -> str:
        return self.get(ref).status

    def describe(self, ref: str) -> dict[str, Any]:
        return self.get(ref).to_dict()

    def record(self, ref: str, mode: str, probe_status: str,
               *, note: str = "", region: str = "ru") -> RegionNote:
        """Записать один замер и пересобрать вердикт.

        Старые замеры сохраняются: замер с VPN не должен затирать уже
        известное «работает без VPN», и наоборот.
        """
        if mode not in MODE_ANY:
            raise ValueError(f"неизвестный режим замера: {mode}")
        entry = self.notes.get(ref) or RegionNote(region=region)
        entry.region = region
        entry.samples[mode] = probe_status
        entry.status = verdict(entry.samples)
        entry.checked_at = time.time()
        if note:
            entry.note = note
        self.notes[ref] = entry
        return entry

    def direct_ok(self) -> set[str]:
        """Модели, доступные из России без VPN."""
        return {ref for ref, note in self.notes.items() if note.usable_direct}

    def needs_vpn(self) -> set[str]:
        return {ref for ref, note in self.notes.items() if note.needs_vpn}

    def measured(self) -> set[str]:
        return {ref for ref, note in self.notes.items() if note.samples}

    def to_payload(self) -> dict[str, Any]:
        return {
            "_comment": (
                "Заполняется командой `zagent geo --vpn|--direct`. "
                "Не затирайте руками: вердикт собирается из сырых замеров."
            ),
            "models": {
                ref: {
                    "region": note.region,
                    "status": note.status,
                    "samples": note.samples,
                    "note": note.note,
                    "checked_at": note.checked_at,
                }
                for ref, note in sorted(self.notes.items())
                if note.samples
            },
        }

    def save(self) -> Path:
        path = self.root / "config" / REGIONS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


def summarize(book: RegionBook) -> dict[str, Any]:
    """Сводка по вердиктам — для строки в интерфейсе и для отчёта."""
    counts = {RU_OK: 0, RU_VPN: 0, RU_BLOCKED: 0, RU_UNKNOWN: 0}
    for note in book.notes.values():
        counts[note.status] = counts.get(note.status, 0) + 1
    return {
        "counts": counts,
        "measured": len(book.measured()),
        "total": len(book.notes),
    }
