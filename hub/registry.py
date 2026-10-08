"""Реестр шлюзов и бесплатных моделей.

Собирает из config/gateways.json единый список бесплатных моделей, объединяя
источники:

    static  — список free_models, заданный вручную в конфиге
    live    — GET /models конкретного шлюза (для OpenRouter берём только :free)

Для OpenRouter дополнительно проверяется цена: у бесплатных моделей в каталоге
prompt/completion равны "0".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from hub.keyring import REGISTRY, gateway_key
from providers.openai_compat import OpenAICompatProvider, extract_model_ids

#: Суффиксы/маркеры, по которым модель считается бесплатной в живом каталоге.
FREE_MARKERS = (":free", "-free")

#: Модели, которые не являются чат-моделями — их не пингуем в health.
#: Проверка по подстроке в lowercase-id, поэтому маркеры короткие и специфичные.
NON_CHAT = (
    "embed",       # text-embedding-*, qwen3-embedding-*
    "bge-",        # bge-m3, bge-reranker
    "moderation",
    "ocr",
    "whisper",
    "-tts",
    "stt",
    "image",
    "guard",
    "safety",
    "rerank",
    "vision-only",
)


@dataclass
class FreeModel:
    """Одна бесплатная модель одного шлюза."""

    gateway_id: str
    model_id: str
    source: str  # static | live | marked
    label: str = ""
    needs_key: bool = True
    context: int | None = None

    @property
    def ref(self) -> str:
        """Ключ для конфигов инструментов: gateway/model."""
        return f"{self.gateway_id}/{self.model_id}"

    @property
    def is_chat(self) -> bool:
        low = self.model_id.lower()
        return not any(marker in low for marker in NON_CHAT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gateway": self.gateway_id,
            "model": self.model_id,
            "ref": self.ref,
            "source": self.source,
            "label": self.label,
            "needs_key": self.needs_key,
            "context": self.context,
            "is_chat": self.is_chat,
        }


@dataclass
class Registry:
    """Собранный реестр: шлюзы + модели + результаты проверки живым запросом."""

    gateways: list[dict[str, Any]] = field(default_factory=list)
    models: list[FreeModel] = field(default_factory=list)
    probed: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def chat_models(self) -> list[FreeModel]:
        return [m for m in self.models if m.is_chat]

    def for_gateway(self, gateway_id: str) -> list[FreeModel]:
        return [m for m in self.models if m.gateway_id == gateway_id]

    def refs(self) -> list[str]:
        return [m.ref for m in self.chat_models]


def looks_free(model_id: str, marker: str | None = None) -> bool:
    """Считается ли модель бесплатной по маркеру в id."""
    if marker and model_id.endswith(marker):
        return True
    return any(model_id.endswith(m) or f"/{m}" in model_id for m in FREE_MARKERS)


async def probe_free_price(provider: OpenAICompatProvider, candidates: list[str]) -> dict[str, str]:
    """Проверить цену у моделей OpenRouter: prompt == "0" и completion == "0"."""
    out: dict[str, str] = {}
    try:
        response = await provider.client.get(
            f"{provider.base_url}/models", headers=provider._headers(), timeout=provider.timeout
        )
        if response.status_code != 200:
            return out
        data = response.json()
    except Exception:
        return out

    payload = data.get("data") if isinstance(data, dict) else data
    if not isinstance(payload, list):
        return out
    wanted = set(candidates)
    for item in payload:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        if model_id not in wanted:
            continue
        pricing = item.get("pricing") or {}
        prompt = str(pricing.get("prompt") or "")
        completion = str(pricing.get("completion") or "")
        out[model_id] = "free" if prompt in ("0", "0.0") and completion in ("0", "0.0") else "paid"
    return out


def models_from_live_catalog(
    gateway: dict[str, Any], model_ids: list[str], contexts: dict[str, int] | None = None
) -> list[FreeModel]:
    """Отобрать бесплатные модели из живого каталога шлюза.

    contexts: необязательная карта model_id -> context_length из того же каталога.
    """
    gateway_id = gateway["id"]
    marker = gateway.get("free_marker")
    routers = {str(r) for r in (gateway.get("routers") or [])}
    needs_key = bool(gateway.get("needs_key"))
    contexts = contexts or {}

    found: list[FreeModel] = []
    for model_id in model_ids:
        is_router = model_id in routers
        if not (is_router or looks_free(model_id, marker)):
            continue
        context = contexts.get(model_id)
        found.append(
            FreeModel(
                gateway_id=gateway_id,
                model_id=model_id,
                source="marked" if is_router else "live",
                label=str(gateway.get("label") or gateway_id),
                needs_key=needs_key,
                context=int(context) if isinstance(context, int) and context > 0 else None,
            )
        )
    return found


def models_from_static(gateway: dict[str, Any]) -> list[FreeModel]:
    """Модели из ручного списка free_models в конфиге.

    Пустые строки и дубли отбрасываются — список в конфиге пишется руками.
    """
    needs_key = bool(gateway.get("needs_key"))
    models: list[FreeModel] = []
    seen: set[str] = set()
    for raw in gateway.get("free_models", []):
        model_id = str(raw).strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append(
            FreeModel(
                gateway_id=gateway["id"],
                model_id=model_id,
                source="static",
                label=str(gateway.get("label") or gateway["id"]),
                needs_key=needs_key,
            )
        )
    return models


def gateway_keys(gateway: dict[str, Any]) -> list[str]:
    """Ключи шлюза из конфигурации, без обращения к кольцу."""
    keys = gateway.get("api_keys") or []
    if keys:
        return [str(k) for k in keys if str(k or "").strip()]
    single = str(gateway.get("api_key") or "").strip()
    return [single] if single else []


def needs_credential(gateway: dict[str, Any]) -> bool:
    """Нужна ли шлюзу учётная запись для разговора с провайдером.

    Ответ берётся не из одного флага `needs_key`: в конфигурации он стоит
    у `zen` как `false`, хотя переменная `ZEN_API_KEY` у него задана и без
    неё шлюз не отвечает. Ориентируемся на оба признака сразу: либо шлюз
    сам просит ключ, либо у него названа переменная, из которой он его
    читает. Шлюз без ключа и без переменной (локальный, без авторизации)
    считаем рабочим — иначе мы бы выкидывали из реестра то, что работает.
    """
    return bool(gateway.get("needs_key") or gateway.get("env"))


def usable_without_keys(gateway: dict[str, Any]) -> bool:
    """Может ли шлюз говорить с провайдером вообще.

    Ключ нужен не всегда, но если он нужен и его нет — шлюз нерабочий, и
    любой его запрос провайдеру закончится отказом.
    """
    if not needs_credential(gateway):
        return True
    return bool(gateway_keys(gateway))


async def collect(
    gateways: list[dict[str, Any]],
    *,
    root: str | Path | None = None,
    include_paid_gateways: bool = True,
    check_price: bool = True,
    timeout: float = 30.0,
) -> Registry:
    """Собрать реестр: статические списки + живые каталоги + проверка цен.

    include_paid_gateways: брать live-каталог даже у шлюзов, которым нужен ключ.
    check_price: у OpenRouter перепроверить, что цена действительно нулевая.
    """
    registry = Registry(gateways=list(gateways))

    live_tasks: list[tuple[dict[str, Any], OpenAICompatProvider]] = []
    clients: list[httpx.AsyncClient] = []

    for gateway in gateways:
        # Шлюз без ключа не добавляет моделей в реестр.
        #
        # Живой прогон 07.10.2026: у `zen` не задана ZEN_API_KEY, но его модель
        # `space-bunny-free` стояла в tiers.json и попадала в выбор. Селектор
        # брал её первой по приоритету, и задача падала за 24 мс с текстом
        # «все ключи провайдера в карантине по лимиту», пока 39 свободных
        # аккаунтов на семи других шлюзах стояли без дела. Проверка `has_key`
        # ниже относилась только к живому каталогу и до статических моделей
        # не доходила.
        if not usable_without_keys(gateway):
            registry.errors[str(gateway.get("id"))] = (
                "нет ключа — модели шлюза не используются"
            )
            continue
        registry.models.extend(models_from_static(gateway))
        catalog = set(gateway.get("catalog") or [])
        if "live" not in catalog:
            continue
        if gateway.get("needs_key") and not gateway.get("has_key"):
            registry.errors[gateway["id"]] = "нет ключа, live-каталог пропущен"
            continue
        if gateway.get("needs_key") and not include_paid_gateways:
            continue
        client = httpx.AsyncClient(follow_redirects=True)
        clients.append(client)
        provider = OpenAICompatProvider(
            gateway["id"],
            gateway["resolved_url"],
            gateway_key(gateway),
            timeout=timeout,
            client=client,
        )
        live_tasks.append((gateway, provider))

    try:
        results = await asyncio.gather(
            *(provider.list_models() for _, provider in live_tasks), return_exceptions=True
        )
        for (gateway, provider), result in zip(live_tasks, results):
            if isinstance(result, BaseException):
                registry.errors[gateway["id"]] = f"{type(result).__name__}: {result}"
                continue
            if not result.get("ok"):
                registry.errors[gateway["id"]] = str(result.get("error") or "каталог недоступен")
                continue
            contexts = await _fetch_contexts(provider)
            registry.models.extend(models_from_live_catalog(gateway, result["ids"], contexts))
    finally:
        for client in clients:
            await client.aclose()

    if check_price:
        await _apply_price_check(registry)

    registry.models = _dedupe(registry.models)
    return registry


async def _fetch_contexts(provider: OpenAICompatProvider) -> dict[str, int]:
    """Достать context_length из каталога шлюза, если провайдер его отдаёт.

    Ошибка здесь не критична: без контекста экспорт подставит разумное значение.
    """
    try:
        response = await provider.client.get(
            f"{provider.base_url}/models", headers=provider._headers(), timeout=provider.timeout
        )
        if response.status_code != 200:
            return {}
        data = response.json()
    except Exception:
        return {}

    payload = data.get("data") if isinstance(data, dict) else data
    if not isinstance(payload, list):
        return {}
    contexts: dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        value = item.get("context_length") or item.get("max_context_length")
        if model_id and isinstance(value, int) and value > 0:
            contexts[model_id] = value
    return contexts


async def _apply_price_check(registry: Registry) -> None:
    """OpenRouter: убрать из реестра :free-модели с ненулевой ценой."""
    openrouter = next((g for g in registry.gateways if g["id"] == "openrouter"), None)
    if openrouter is None or not openrouter.get("has_key"):
        return
    candidates = [m.model_id for m in registry.models if m.gateway_id == "openrouter"]
    if not candidates:
        return
    client = httpx.AsyncClient(follow_redirects=True)
    try:
        provider = OpenAICompatProvider(
            "openrouter", openrouter["resolved_url"], gateway_key(openrouter),
            client=client
        )
        prices = await probe_free_price(provider, candidates)
    finally:
        await client.aclose()

    kept: list[FreeModel] = []
    for model in registry.models:
        if model.gateway_id != "openrouter" or model.source == "static":
            kept.append(model)
            continue
        verdict = prices.get(model.model_id)
        if verdict == "paid":
            registry.errors[f"{model.gateway_id}/{model.model_id}"] = "помечена :free, но цена ≠ 0"
            continue
        kept.append(model)
    registry.models = kept


def _dedupe(models: list[FreeModel]) -> list[FreeModel]:
    """Убрать дубли по (gateway, model), сохранив первый источник."""
    seen: set[tuple[str, str]] = set()
    out: list[FreeModel] = []
    for model in models:
        key = (model.gateway_id, model.model_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(model)
    return sorted(out, key=lambda m: (m.gateway_id, m.model_id))


#: Retry-After, который шлюз просит подставить при лимите, сек.
RETRY_AFTER_S = 12.0

#: Ошибки, при которых повтор бессмысленен: модель закрыта для сторонних клиентов.
PERMANENT_ERRORS = (
    "can only be used from within",
    "only available on agentic harnesses",
    "Unknown Model",
    "not available on the Workers Free plan",
)


async def probe_models(
    gateways: list[dict[str, Any]],
    models: list[FreeModel],
    *,
    prompt: str = "Ответь одним словом: ok",
    max_tokens: int = 256,
    timeout: float = 60.0,
    concurrency: int = 6,
    per_gateway_pause: float = 1.5,
    retry_on_limit: bool = True,
    retry_count: int = 2,
    on_progress: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Живой пинг каждой модели.

    Модели одного шлюза пингуются пачками: у провайдеров лимиты считаются на аккаунт,
    поэтому 6 одновременных запросов к llm7.io (1 RPS анонимно) гарантированно дают 429.
    Между пачками делается пауза per_gateway_pause, а по 429 ставится один повтор
    с ожиданием RETRY_AFTER_S.

    max_tokens по умолчанию 256 — reasoning-модели (gpt-oss, nemotron, glm-flash)
    тратят первые токены на размышление и при меньшем лимите возвращают пустой content.

    Статусы: ok | empty | limited | blocked | down
        limited — 429, модель жива, но исчерпан лимит (повторить позже)
        blocked — доступ закрыт провайдером постоянно (повтор не поможет)
    """
    by_id = {g["id"]: g for g in gateways}
    grouped: dict[str, list[FreeModel]] = {}
    for model in models:
        grouped.setdefault(model.gateway_id, []).append(model)

    results: dict[str, dict[str, Any]] = {}

    notes: dict[str, str] = {}

    # Телеметрия: сколько всего, сколько сделано, что проверяется прямо сейчас.
    # Без неё пинг на 39 моделей выглядит как зависший процесс.
    total = len(models)
    done = 0

    def report(kind: str, model: FreeModel | None = None, **extra: Any) -> None:
        if on_progress is None:
            return
        payload = {
            "kind": kind,
            "done": done,
            "total": total,
            "gateway": gateway_id,
            "model": model.model_id if model else "",
            "ref": model.ref if model else "",
        }
        payload.update(extra)
        try:
            on_progress(payload)
        except Exception:
            # Отчёт о прогрессе не имеет права ронять сам пинг.
            pass

    for gateway_id, group in grouped.items():
        gateway = by_id.get(gateway_id)
        if gateway is None:
            for model in group:
                results[model.ref] = {"status": "down", "error": "нет шлюза в конфиге"}
                done += 1
                report("model", model, status="down")
            continue

        if gateway.get("discover_live"):
            # Локальный рантайм (Ollama/LM Studio): список моделей берём из /models.
            group, note = await _expand_local_group(gateway, group)
            if note:
                notes[gateway_id] = note
            if not group:
                continue

        client = httpx.AsyncClient(follow_redirects=True)
        try:
            provider = OpenAICompatProvider(
                gateway_id,
                gateway["resolved_url"],
                gateway_key(gateway),
                timeout=timeout,
                client=client,
            )
            semaphore = asyncio.Semaphore(max(1, concurrency))
            batch_size = max(1, concurrency)

            for start in range(0, len(group), batch_size):
                batch = group[start : start + batch_size]
                # Сначала сообщаем, что пошли проверять эту пачку: иначе между
                # пачками визуально ничего не происходит по паузе провайдера.
                for model in batch:
                    report("checking", model)
                outcomes = await asyncio.gather(
                    *(one_probe(provider, model, prompt, max_tokens, semaphore) for model in batch)
                )
                for model, outcome in zip(batch, outcomes):
                    results[model.ref] = outcome
                    done += 1
                    report("model", model, status=outcome.get("status"),
                           duration_ms=outcome.get("duration_ms", 0))
                    # Учёт квоты проб. Сканирование каталога — это десятки
                    # запросов по каждому аккаунту, и кольцо обязано о них
                    # знать: иначе агент стартует с остатком «48 осталось»,
                    # полученным до сканирования, и упирается в 429 на середине
                    # задачи, не понимая почему.
                    limits = outcome.get("limits") or {}
                    if limits:
                        REGISTRY.note_quota(gateway, gateway_key(gateway),
                                           limits)
                    REGISTRY.note_spent(gateway, gateway_key(gateway))
                if start + batch_size < len(group) and per_gateway_pause > 0:
                    report("pause", gateway=gateway_id, seconds=per_gateway_pause)
                    await asyncio.sleep(per_gateway_pause)

            if retry_on_limit:
                limited = [m for m in group if results.get(m.ref, {}).get("status") == "limited"]
                if limited:
                    report("retry", gateway=gateway_id, count=len(limited))
                    await asyncio.sleep(RETRY_AFTER_S)
                    retries = await asyncio.gather(
                        *(one_probe(provider, m, prompt, max_tokens, semaphore) for m in limited)
                    )
                    for model, outcome in zip(limited, retries):
                        if outcome["status"] == "ok":
                            outcome["retried"] = True
                        results[model.ref] = outcome
                        report("model", model, status=outcome.get("status"), retried=True)
                        # Повторы тоже тратят квоту — и их учёт обязан быть
                        # таким же, как у основных проб.
                        limits = outcome.get("limits") or {}
                        if limits:
                            REGISTRY.note_quota(gateway, gateway_key(gateway),
                                               limits)
                        REGISTRY.note_spent(gateway, gateway_key(gateway))
        finally:
            await client.aclose()

    # Примечание об успешном сборе не должно попадать в поле `error`:
    # исправная локальная модель выглядела сломанной, потому что её
    # нормальный итог («3 модели в локальном рантайме») записывался
    # туда же, где настоящие отказы шлюзов.
    for gateway_id, note in notes.items():
        results[f"{gateway_id}/*"] = {"status": "note", "message": note}
    return results


async def _expand_local_group(
    gateway: dict[str, Any], group: list[FreeModel]
) -> tuple[list[FreeModel], str]:
    """Узнать модели локального рантайма (Ollama) вместо пустого списка из конфига.

    Возвращает (модели, примечание). Пустой список — пинговать нечего.
    """
    gateway_id = gateway["id"]
    client = httpx.AsyncClient(follow_redirects=True)
    try:
        provider = OpenAICompatProvider(
            gateway_id, gateway["resolved_url"], gateway_key(gateway), client=client
        )
        catalog = await provider.list_models()
    finally:
        await client.aclose()

    if not catalog.get("ok"):
        return [], f"рантайм недоступен: {catalog.get('error')}"
    if not catalog["ids"]:
        return [], "рантайм запущен, но моделей нет — скачайте их (например, `ollama pull gpt-oss:20b`)"

    return (
        [
            FreeModel(
                gateway_id=gateway_id,
                model_id=model_id,
                source="live",
                label=str(gateway.get("label") or gateway_id),
                needs_key=False,
            )
            for model_id in catalog["ids"]
        ],
        f"{len(catalog['ids'])} моделей в локальном рантайме",
    )


async def one_probe(
    provider: OpenAICompatProvider,
    model: FreeModel,
    prompt: str,
    max_tokens: int,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Один пинг с классификацией результата."""
    async with semaphore:
        result = await provider.chat(
            model.model_id,
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=max_tokens,
        )

    error = result.get("error")
    http = result.get("status")
    text = str(result.get("text") or "")
    reasoning = str(result.get("reasoning") or "")

    row: dict[str, Any] = {
        "status": "down",
        "error": error,
        "duration_ms": result.get("duration_ms", 0),
        "tokens_in": result.get("tokens_in", 0),
        "tokens_out": result.get("tokens_out", 0),
        "cost": result.get("cost"),
        "http": http,
        "sample": (text or reasoning)[:60],
        # Остаток квоты из заголовков ответа. Проба идёт напрямую через
        # `provider.chat`, минуя `failover`, где учёт и происходит, — и без
        # этого поля полное сканирование каталога выжигало десятки запросов
        # молча: кольцо считало по старому остатку, агент получал 429 на
        # середине задачи, а причина была в сканировании час назад.
        "limits": result.get("limits") or {},
    }

    if error is None:
        row["status"] = "ok" if (text.strip() or reasoning.strip()) else "empty"
        return row

    message = str(error)
    if http == 429 or "Лимит запросов" in message:
        row["status"] = "limited"
        row["error"] = "Лимит запросов (429) — повторить позже"
    elif http in (401, 403) or any(marker in message for marker in PERMANENT_ERRORS):
        row["status"] = "blocked"
        row["error"] = f"Доступ закрыт провайдером ({http or '—'})"
    return row
