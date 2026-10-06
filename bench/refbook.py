"""Библиотека эталонов: индекс, подсказки и оценка её использования.

Индекс лежит в ``ref/INDEX.yaml``. Агент читает его **первым** — это дешевле,
чем перебор файлов, и не даёт ему изобретать то, что уже собрано.

Отдельная функция здесь — ``similarity``. Без неё «использовал ли эталон» это
гадание: агент может переписать образец наполовину, и простой grep по названию
покажет «не использовал», хотя использовал.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Файлы, по которым сравниваем эталон с результатом. Остальное (картинки,
#: манифесты) в сходстве ничего не значит.
COMPARE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".html", ".css", ".json", ".md", ".txt", ".yml", ".yaml"}

#: Подборка дизайн-систем (design-md). Это не код, а описания: цвета,
#: шрифты, сетки, компоненты. Сравнивать их с результатом бессмысленно,
#: поэтому такая папка идёт по отдельному пути и в сходство не попадает.
DESIGN_BOOK_DIR = "awesome-design-md-main/design-md"

#: Порог, выше которого считаем, что эталон использован по-настоящему.
#: Число взято с замеров живых прогонов, а не выбрано на глаз: копирование с
#: правкой текстов даёт около 0.99, переписывание под свою задачу — 0.48–0.70,
#: а «прочитал и написал своё» — 0.30–0.33. 0.35 разделяет эти группы и не
#: помечает как «не использовал» нормальную адаптацию.
USED_THRESHOLD = 0.35


#: Тон бренда выводим из его же описания. Совпадения по названию темы
#: подобраны вручную по смыслу, а не по вхождению слова: «минимализм» и
#: «minimal» встречаются в разных папках, а объединение даёт мусор.
DESIGN_TONES: dict[str, str] = {
    "linear.app": "интерфейсы, тёмная база, чёткость, плотная сетка",
    "vercel": "тёмный минимализм, моношрифт, строгая сетка",
    "stripe": "светлый минимализм, градиенты, типографика как главный акцент",
    "apple": "светлый минимализм, воздух, крупная типографика, без рамок",
    "claude": "тёплый минимализм, приглушённые тона, спокойный тон",
    "cursor": "тёмный минимализм, графитовые тона, акцент на коде",
    "notion": "нейтральный минимализм, ч/б, плоские блоки, много воздуха",
    "figma": "светлый минимализм, цветные акценты, радиусы и сетка",
    "framer": "тёмный минимализм, крупные заголовки, градиентные пятна",
    "raycast": "тёмный минимализм, градиенты, компактность",
    "opencode.ai": "тёмный минимализм, терминальный тон, моношрифт",
    "airtable": "светлый интерфейсный, плотная сетка, цветные метки",
    "asana": "светлый интерфейсный, яркие акценты, скругления",
    "slack": "яркий, много цвета, плотный интерфейс",
    "discord": "тёмный, насыщенные акценты, плотная сетка",
    "shopify": "светлый, зелёный акцент, крупные кнопки",
    "uber": "светлый, чёрный и белый, крупная типографика",
    "airbnb": "светлый, тёплые акценты, крупные фото, скругления",
    "nike": "минимализм, крупная типографика, один акцент, много воздуха",
    "spotify": "тёмный, насыщенный зелёный, крупные обложки",
    "netflix": "тёмный, красный акцент, контраст, минимализм",
    "tesla": "минимализм, ч/б, красный акцент, инженерный тон",
    "ferrari": "тёмный, красный, премиальный минимализм",
    "bmw": "светлый, синий акцент, инженерная строгость",
    "porsche": "тёмный, жёлтый акцент, техническая точность",
    "sentry": "тёмный, фиолетовый акцент, плотность, логи",
    "supabase": "тёмный, зелёный акцент, техническая строгость",
    "hashicorp": "тёмный, фиолетовый, строгая сетка",
    "nvidia": "тёмный, зелёный акцент, мощная типографика",
    "basecamp": "светлый, тёплый, человечный тон, базовые формы",
    "dropbox": "светлый, синий акцент, простой и ясный",
    "mailchimp": "светлый, тёплый, дружелюбный",
    "hubspot": "светлый, оранжевый, плотный интерфейс",
    "mintlify": "тёмный, бирюзовый акцент, документация",
    "posthog": "тёмный, многослойный, технический тон",
    "revolut": "тёмный, минимализм, синий акцент",
    "mastercard": "светлый, красный и жёлтый, простой",
    "coinbase": "светлый, синий, крупная типографика",
    "binance": "тёмный, жёлтый акцент, плотная сетка",
    "kraken": "тёмный, фиолетовый, строгость",
    "expo": "тёмный, минимализм, моношрифт",
    "warp": "тёмный, градиенты, терминальный тон",
    "zed": "тёмный, минимализм, плотность",
    "miro": "светлый, яркий, доска и кавычки",
    "sentry-alt": "тёмный, фиолетовый",
    "spacex": "тёмный, ч/б, инженерный минимализм",
    "theverge": "светлый, журнальная вёрстка, крупная типографика",
    "wired": "журнальная вёрстка, крупная типографика",
    "starbucks": "тёмный, зелёный, человечный тон",
    "nintendo-2001": "яркий, игровой, крупные формы",
    "playstation": "тёмный, синий, игровой минимализм",
    "bmw-m": "тёмный, синий, технологичность",
    "lamborghini": "тёмный, жёлтый, премиальный минимализм",
    "bugatti": "тёмный, синий, премиальный",
    "vodafone": "красный, простой, мобильный",
    "wise": "светлый, бирюзовый, дружелюбный",
    "renault": "светлый, синий, инженерный",
    "replicate": "тёмный, нейтральный, минимализм",
    "mistral.ai": "тёмный, оранжевый акцент",
    "meta": "светлый, синий, нейтральный",
    "together.ai": "тёмный, градиенты",
    "minimax": "тёмный, градиенты",
    "resend": "тёмный, минимализм, моношрифт",
    "intercom": "светлый, жёлтый, дружелюбный",
    "zapier": "оранжевый, яркий, иллюстративный",
    "monday": "цветной, весёлый, табличный",
    "dell-1996": "классический, строгий",
    "cal": "тёмный, календарь, плотность",
    "cohere": "нейтральный, AI, строгость",
    "x.ai": "тёмный, минимализм",
    "composio": "тёмный, технический",
    "elevenlabs": "тёмный, кремовый, премиальный",
    "runwayml": "тёмный, кинематографичный",
    "superhuman": "тёмный, премиальный, плотность",
    "sanity": "светлый, красный акцент, контент",
    "clickhouse": "жёлтый акцент, технический",
    "coindesk": "жёлтый, новостной",
}


@dataclass
class DesignBrand:
    """Описание дизайн-системы одного бренда.

    Это не код, а документ: цвета, шрифты, сетка, компоненты, правила и
    запреты. Из него полезны три вещи — характер (для выбора), палитра
    (чтобы не гадать с цветом) и правила «не делай так» (чтобы агент не
    натянул чужой стиль).
    """

    id: str
    title: str
    path: str
    character: str
    palette: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    dos: list[str] = field(default_factory=list)
    donts: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, folder: Path, spec: Path) -> "DesignBrand":
        text = spec.read_text(encoding="utf-8", errors="replace")
        brand_id = folder.name

        title = brand_id
        match = re.search(r"^# (.+)$", text, re.M)
        if match:
            title = match.group(1).strip()

        palette = sorted(set(re.findall(r"#[0-9a-fA-F]{6}\b", text)))[:12]

        # Шрифты берутся из раздела про семейство шрифтов. Регулярка нужна
        # широкая: у Linear имена в **жирном** («Linear Display»), у Apple в
        # обычном («SF Pro Display»), у Stripe просто прописью («Sohne»).
        # Раньше читался только жирный, и у половины брендов шрифтов не было
        # вовсе — а без них палитра сама по себе маловразумична.
        fonts: list[str] = []
        font_section = _section(text, "font family")
        if font_section:
            bold = re.findall(
                r"\*\*([A-Z][\w.+-]*(?:\s+[A-Z][\w.+-]*){0,3})"
                r"(?:\s+(?:Sans|Grotesk|Mono|Serif|Display|Text|UI))?\*\*",
                font_section,
            )
            plain = re.findall(
                r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\s+"
                r"(?:Sans|Grotesk|Mono|Serif|Display|Text|UI|Sans-Serif))\b",
                font_section,
            )
            for name in bold + plain:
                name = " ".join(name.split())
                if 3 < len(name) < 34 and name not in fonts:
                    fonts.append(name)
            fonts = fonts[:5]

        dos, donts = _rules(text)

        sections = [
            h.strip()
            for h in re.findall(r"^## (.+)$", text, re.M)
            if h.strip()
        ]

        return cls(
            id=brand_id,
            title=title,
            path=f"{DESIGN_BOOK_DIR}/{brand_id}/DESIGN.md",
            character=DESIGN_TONES.get(brand_id, "тон описан в файле"),
            palette=palette,
            fonts=fonts,
            dos=dos[:4],
            donts=donts[:4],
            sections=sections,
        )

    def short_brief(self, max_chars: int = 1200) -> str:
        """Краткая выжимка для промпта агента.

        Полный файл — 20–40 КБ, и два таких в промпте съедают весь контекст
        задачи. Поэтому сюда идёт характер, палитра и самые важные запреты.
        """
        parts = [f"ДИЗАЙН-СИСТЕМА: {self.title} ({self.path})",
                 f"Характер: {self.character}"]
        if self.palette:
            parts.append("Палитра: " + ", ".join(self.palette[:8]))
        if self.fonts:
            parts.append("Шрифты: " + ", ".join(self.fonts))
        if self.donts:
            parts.append("НЕ делай так:\n" + "\n".join(f"- {d}" for d in self.donts))
        text = "\n".join(parts)
        if len(text) > max_chars:
            text = text[: max_chars - 30].rstrip() + "\n…(остальное в файле)"
        return text


def _section(text: str, name: str) -> str:
    """Тело раздела по имени (регистр и пробелы не важны)."""
    pattern = re.compile(
        r"^#{2,3} " + re.escape(name) + r"\s*$", re.IGNORECASE | re.M
    )
    found = pattern.search(text)
    if not found:
        return ""
    body = text[found.end():]
    nxt = re.search(r"^#{2,3} ", body, re.M)
    return body[: nxt.start()] if nxt else body


def _rules(text: str) -> tuple[list[str], list[str]]:
    """Правила «делай» и «не делай» из разделов Do / Don't."""
    dos: list[str] = []
    donts: list[str] = []
    for line in text.splitlines():
        item = line.strip()
        if not item.startswith("- "):
            continue
        body = item[2:].strip()
        # Плейсхолдеры вида {colors.canvas} агента ничего не говорят,
        # а в описании они встречаются в каждом правиле.
        low = body.lower()
        if low.startswith("don") and len(body) < 40:
            continue
        if low.startswith("do") and len(body) < 40:
            continue
        (donts if low.startswith("don't") or low.startswith("do not")
         else dos).append(body)
    return dos, donts


@dataclass
class RefEntry:
    """Одна запись индекса."""

    id: str
    path: str
    tags: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    complexity: int = 1
    use_when: str = ""
    avoid_when: str = ""
    license: str = ""
    source: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.path)

    def summary_line(self) -> str:
        """Одна строка для подсказки агенту."""
        bits = [f"- {self.id}  ({self.path})"]
        if self.use_when:
            bits.append(f"когда: {self.use_when}")
        if self.avoid_when:
            bits.append(f"НЕ когда: {self.avoid_when}")
        if self.stack:
            bits.append(f"стек: {', '.join(self.stack)}")
        return " | ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "path": self.path, "tags": self.tags,
            "stack": self.stack, "complexity": self.complexity,
            "use_when": self.use_when, "avoid_when": self.avoid_when,
            "license": self.license, "source": self.source,
        }


class RefBook:
    """Каталог эталонов."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.entries: list[RefEntry] = []
        self.load_errors: list[str] = []
        self._load()

    def _load(self) -> None:
        index = self.root / "INDEX.yaml"
        if not index.is_file():
            self.load_errors.append(f"нет индекса {index}")
            return
        try:
            raw = yaml.safe_load(index.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            self.load_errors.append(f"{index.name}: не разбирается — {exc}")
            return
        if not isinstance(raw, dict):
            self.load_errors.append(f"{index.name}: ожидался словарь")
            return

        seen: set[str] = set()
        for number, item in enumerate(raw.get("entries") or [], start=1):
            if not isinstance(item, dict) or "id" not in item or "path" not in item:
                self.load_errors.append(f"{index.name}: запись {number} без id или path")
                continue
            rid = str(item["id"])
            if rid in seen:
                self.load_errors.append(f"{index.name}: два эталона с id {rid!r}")
                continue
            seen.add(rid)
            self.entries.append(
                RefEntry(
                    id=rid,
                    path=str(item["path"]),
                    tags=[str(t) for t in item.get("tags") or []],
                    stack=[str(s) for s in item.get("stack") or []],
                    complexity=int(item.get("complexity", 1)),
                    use_when=str(item.get("use_when", "")),
                    avoid_when=str(item.get("avoid_when", "")),
                    license=str(item.get("license", "")),
                    source=str(item.get("source", "")),
                )
            )
        if not self.entries and not self.load_errors:
            self.load_errors.append(f"{index.name}: ни одной записи")

    # ------------------------------------------------------------------ выборка

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def get(self, ref_id: str) -> RefEntry | None:
        for entry in self.entries:
            if entry.id == ref_id:
                return entry
        return None

    def resolve(self, hint: str) -> RefEntry | None:
        """Найти эталон по id, по имени папки или по пути из задания."""
        hint = hint.strip().strip("/")
        if not hint:
            return None
        direct = self.get(hint)
        if direct:
            return direct
        tail = hint.rstrip("/").split("/")[-1]
        for entry in self.entries:
            if entry.path.rstrip("/").split("/")[-1] == tail or entry.id == tail:
                return entry
        return None

    def dir_of(self, entry: RefEntry) -> Path | None:
        path = self.root / entry.path
        return path if path.is_dir() else None

    def broken(self) -> list[RefEntry]:
        """Записи, чьей папки нет: индекс разошёлся с библиотекой."""
        return [e for e in self.entries if self.dir_of(e) is None]

    # ---------------------------------------------------------------- подсказка

    def summary(self, *, only: list[str] | None = None, max_chars: int = 1800) -> str:
        """Компактный список для промпта агента.

        Подсказки из задания идут первыми и подробно, остальное — одной строкой
        на эталон. Если текст не влезает в лимит, обрезаем хвост, а не
        середину, чтобы не потерять конец списка.
        """
        chosen = self.entries
        if only:
            picked: list[RefEntry] = []
            for hint in only:
                found = self.resolve(hint)
                if found and found not in picked:
                    picked.append(found)
            others = [e for e in self.entries if e not in picked]
            chosen = picked + others

        if not chosen:
            return ""

        head: list[str] = []
        for hint in only or []:
            found = self.resolve(hint)
            if found:
                head.append(
                    f"БЛИЖАЙШИЙ ЭТАЛОН: {found.id} — папка {found.path}\n"
                    f"  когда применять: {found.use_when or '—'}\n"
                    f"  когда НЕ применять: {found.avoid_when or '—'}\n"
                    f"  прочитай его перед началом работы."
                )

        tail = [entry.summary_line() for entry in chosen]
        text = "\n".join(head + tail)
        if len(text) > max_chars:
            text = text[: max_chars - 20].rstrip() + "\n…(остальное в ref/INDEX.yaml)"
        return text

    # ------------------------------------------------------------ использование

    def similarity(self, ref_dir: Path, artifacts: dict[str, Path]) -> float:
        """Насколько результат похож на эталон, 0..1.

        Сравниваются пары «файл эталона — файл результата», берётся лучшая для
        каждого файла эталона, и **взвешенное среднее по объёму**: короткий
        README не должен уравновешивать сходство большого исходника.

        Замер на живой модели: переписывание эталона под задачу даёт 0.48–0.70,
        копирование с правкой текстов — около 0.99, «прочитал и написал своё» —
        0.30–0.33. Порог 0.35 стоит между ними.
        """
        ref_dir = Path(ref_dir)
        if not ref_dir.is_dir() or not artifacts:
            return 0.0

        ref_files = {
            p.relative_to(ref_dir).as_posix(): p
            for p in ref_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in COMPARE_SUFFIXES
        }
        if not ref_files:
            return 0.0

        out_files = {
            rel: p for rel, p in artifacts.items()
            if Path(rel).suffix.lower() in COMPARE_SUFFIXES
        }
        if not out_files:
            return 0.0

        out_text: dict[str, str] = {}
        for rel, path in out_files.items():
            try:
                out_text[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        if not out_text:
            return 0.0

        scores: list[float] = []
        for rel, path in ref_files.items():
            try:
                ref_text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not ref_text.strip():
                continue
            best = 0.0
            for body in out_text.values():
                # autojunk выключен обязательно. Он считает «частыми» строки,
                # встречающиеся больше 1% текста, и выбрасывает их из
                # сравнения — а в коде это `}`, `    return` и пробелы. На
                # повторяющемся файле он даёт 0.002 вместо 0.874: сходство
                # падает не из-за различий, а из-за самого алгоритма.
                # Платим скоростью, но вердикт о попадании в эталон должен
                # зависеть от кода, а не от частотности строк в нём.
                matcher = difflib.SequenceMatcher(
                    None, ref_text, body, autojunk=False
                )
                if matcher.quick_ratio() <= best:
                    continue
                best = max(best, matcher.ratio())
                if best > 0.99:
                    break
            scores.append(best)

        if not scores:
            return 0.0
        # Взвешенное среднее по длине: короткий README не должен уравновешивать
        # сходство по большому исходнику. Файл весит пропорционально объёму,
        # поэтому результат отражает, сколько кода на самом деле взято.
        weights: list[float] = []
        for score, path in zip(scores, ref_files.values()):
            try:
                weights.append(max(1, path.stat().st_size))
            except OSError:
                weights.append(1)
        total = sum(weights)
        if not total:
            return 0.0
        return round(sum(s * w for s, w in zip(scores, weights)) / total, 3)

    # -------------------------------------------------- дизайн-системы

    def design_dir(self) -> Path | None:
        """Папка с описаниями дизайн-систем, если её положили в библиотеку."""
        candidate = self.root / DESIGN_BOOK_DIR
        if candidate.is_dir():
            return candidate
        return None

    def designs(self) -> list[DesignBrand]:
        """Доступные дизайн-системы, отсортированные по имени."""
        folder = self.design_dir()
        if folder is None:
            return []
        found: list[DesignBrand] = []
        for child in sorted(folder.iterdir()):
            if not child.is_dir():
                continue
            spec = child / "DESIGN.md"
            if not spec.is_file():
                continue
            try:
                found.append(DesignBrand.from_file(child, spec))
            except (OSError, ValueError):
                # Битый файл не должен ронять весь индекс: остальные пригодны.
                continue
        return found

    def design_by_id(self, brand_id: str) -> DesignBrand | None:
        for design in self.designs():
            if design.id == brand_id:
                return design
        return None

    def summary_designs(self, *, max_chars: int = 1400) -> str:
        """Короткий список брендов для подсказки агенту.

        Только имена и характер: полное описание в 30 КБ агента утопит, а
        нужно лишь знать, что выбор есть.
        """
        found = self.designs()
        if not found:
            return ""
        text = "\n".join(f"- {d.id:14} {d.character}" for d in found)
        if len(text) > max_chars:
            text = text[: max_chars - 20].rstrip() + "\n…(полный список в ref/)"
        return text

    def usage_report(self, ref_dir: Path, artifacts: dict[str, Path]) -> dict[str, Any]:
        """Вердикт по использованию эталона: сходство + прямая ссылка."""
        similarity = self.similarity(ref_dir, artifacts)
        name = Path(ref_dir).name
        mentioned = False
        for path in artifacts.values():
            if path.suffix.lower() not in COMPARE_SUFFIXES:
                continue
            try:
                if name in path.read_text(encoding="utf-8", errors="replace"):
                    mentioned = True
                    break
            except OSError:
                continue
        used = similarity >= USED_THRESHOLD
        return {
            "similarity": similarity,
            "mentioned": mentioned,
            "used": used,
            "reinvented_wheel": not used,
            "threshold": USED_THRESHOLD,
        }