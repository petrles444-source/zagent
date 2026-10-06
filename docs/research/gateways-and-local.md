# Бесплатные агрегаторы/шлюзы LLM и локальный вариант для вызова из стороннего Python-клиента (httpx, OpenAI-совместимый `/chat/completions`)

**Дата сбора данных: 2026-10-05.** Все данные получены через `web_fetch` с официальных страниц (docs/pricing/GitHub самих проектов), кроме случаев, явно помеченных как сторонний источник.

## 0. Методичка: как читать отчёт и главные предупреждения

**Метки достоверности:**
- **подтверждено официальной страницей** — цитируется официальная docs/pricing страница проекта, приведён URL.
- **подтверждено issue или сторонним источником** — официальную страницу получить не удалось (403/451/timeout) или данные взяты из стороннего репозитория/списка.
- **не подтверждено** — цифру подтвердить не удалось; в отчёте прямо написано «не найдено».

**Технические ограничения этой сессии (важно):**
- `openrouter.ai` полностью отдаёт **HTTP 403 Cloudflare** на любые запросы из этой сети (и HTML, и `/api/v1/models`, и `.md`-версии docs). Данные по OpenRouter — из сторонних источников, проверявшихся 2026-09-23 и 2026-10-04.
- `console.groq.com` (вся документация, включая rate-limits и deprecations) отдаёт **`{"error":{"message":"Forbidden"}}`**. `groq.com/pricing` редиректит на маркетинговую главную без цифр.
- `build.nvidia.com` отдаёт **403 Access Denied**.
- `docs.sambanova.ai` — timeout / 404.
- `docs.llm7.io` — timeout на всех попытках.

**Три самых важных факта на 2026-10-05:**
1. **GitHub Models полностью выведен из эксплуатации 30 июля 2026** — playground, каталог моделей, inference API и BYOK недоступны никому. Это уже не «бесплатный tier».
2. **У Cerebras нет постоянно бесплатного tier.** Официальная страница лимитов прямо: «No. The Free Trial is time- and credit-bounded: $5 in credits that expire 30 days after they're granted» + **требуется привязанная карта**.
3. **OpenCode Zen / keyless-провайдеры проверяют клиента.** Формулировка из официального репозитория: `403 FreeTierError` — *"OpenCode's free tier can only be used from within OpenCode"*. Это ответ на запрос, а не блокировка аккаунта.

---

## 1. OpenRouter (`:free`-модели)

> ⚠️ **Все данные раздела — «подтверждено сторонним источником»**, т.к. Cloudflare блокирует `openrouter.ai` из этой сети (проверено 6 раз, включая API и `.md`-версии).

| Поле | Значение |
|---|---|
| **1. Название** | OpenRouter |
| **2. Base URL + путь** | `https://openrouter.ai/api/v1` + `POST /chat/completions`. OpenAI-совместимость: **да** (drop-in для `openai` Python SDK, меняется только `base_url` и `api_key`). |
| **3. Доступ** | Регистрация на openrouter.ai → API key. **Карта не нужна** для бесплатных `:free`-моделей. |
| **4. Что бесплатно** | Все модели с суффиксом `:free`. Лимиты: **20 RPM**; **50 RPD** на аккаунт при нулевом балансе; **1000 RPD**, если аккаунт хоть раз купил ≥ $10 кредитов (разовое «разблокирующее» условие, не требование держать баланс). Лимит **глобальный на аккаунт** — дополнительные API-ключи его не расширяют. Счётчик за день виден в `GET /api/v1/key` (`free_model_daily_requests`). Платные модели: динамический лимит $1 баланса = 1 RPS, потолок 500 RPS. |
| **5. Сторонний клиент** | **Работает.** Проверки клиента/сессии нет — обычный Bearer-токен, вызывается из httpx/curl/OpenAI SDK. Но `:free`-модели требуют **включённого разрешения на логирование/тренировку промптов** в privacy-настройках OpenRouter. |
| **6. Доступность из России** | Официально не указана → **не найдено**. Практически: сам сайт из РФ бывает за Cloudflare-защитой, оплата $10 из РФ затруднена (карта), поэтому реально доступен только уровень 50 RPD. |
| **7. Источники** | [OpenRouter free usage limits (doc)](https://openrouter.ai/docs/api-reference/limits) — *прямой фетч 403*; списки моделей — [ClawLabsAI/free-ai-models](https://github.com/ClawLabsAI/free-ai-models) (снимок от **Sun, 04 Oct 2026 10:27:52 UTC**, ссылается на OpenRouter docs, «checked 2026-09-23»); [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) (сноска [^4]); [kestrel openrouter-rate-limits.md](https://raw.githubusercontent.com/pleasedodisturb/kestrel/main/docs/research/openrouter-rate-limits.md) (исследование от 2026-04-21). |
| **8. Достоверность** | **подтверждено сторонним источником** (официальная страница недоступна для фетча). |
| **9. Риски** | Бесплатные модели «обычно не подходят для продакшена» (формулировка самого OpenRouter FAQ). Провайдеры `:free`-маршрутов могут логировать промпты для тренировки. Во время пиков — 429 от upstream. Неудачные запросы всё равно тратят дневную квоту. |

**Актуальные бесплатные model ID (снимок 2026-10-04, 21 чат-модель; лимит у всех одинаковый — 20 RPM / 50 RPD на аккаунт):**

| Model ID | Контекст | Max output | Модальности |
|---|---|---|---|
| `qwen/qwen3.8-27b:free` | 262K | 236K | text, vision, video |
| `google/gemma-4-31b-it:free` | 262K | 33K | vision, text, video |
| `google/gemma-4-26b-a4b-it:free` | 262K | 33K | vision, text, video |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262K | 236K | text |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 1M | 66K | text |
| `nvidia/nemotron-3.5-lightning:free` | 1M | 66K | text |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 256K | 66K | text, audio, vision, video |
| `nvidia/nemotron-3.5-content-safety:free` | 128K | 8K | text, vision |
| `cohere/north-mini-code:free` | 256K | 64K | text (код) |
| `poolside/laguna-s-2.1:free`, `poolside/laguna-xs-2.1:free` | 262K | 32K | text (код) — **retiring 2026-10-31** |
| `thinkingmachines/inkling:free`, `thinkingmachines/inkling-small:free` | 1M | 262K | text, vision, audio |
| `dots-studio/dots-3-note-preview:free` | 512K | 461K | text, vision — retiring 2026-12-31 |
| `inclusionai/ling-3.0-flash-sante:free`, `inclusionai/ling-3.1-flash` | 262K | 33K | text |
| `apodex/apodex-1.1-mini:free` | 262K | 236K | text |
| `liquid/lfm-2.5-2.6b:free` | 66K | 8K | text |
| `openrouter/free` (Free Models Router, авто-роутинг + failover) | 200K | — | text, vision |
| `stealth/space-bunny-alpha` | 1M | 524K | text, vision, video — retiring **2026-10-05** |

Список из [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) (17 моделей, снимок того же периода) частично пересекается и дополнительно содержит `openai/gpt-oss-20b:free`, `nvidia/nemotron-nano-9b-v2:free`, `nvidia/nemotron-nano-12b-v2-vl:free`, `nvidia/nemotron-3-nano-30b-a3b:free`. Полный список вручную из официального каталога **не проверен** — фетч недоступен.

---

## 2. Vercel AI Gateway

| Поле | Значение |
|---|---|
| **1. Название** | Vercel AI Gateway |
| **2. Base URL + путь** | `https://ai-gateway.vercel.sh/v1` + `POST /chat/completions`. Также `GET /v1/models`, `POST /v1/embeddings`, `POST /v1/responses`. OpenAI-совместимость: **да** (официально: «implements the same specification as the OpenAI Chat Completions API», есть примеры на Python/TS/cURL). |
| **3. Доступ** | Аккаунт Vercel (любой team) → AI Gateway API key (`Authorization: Bearer <token>`; альтернативно OIDC-токен). **⚠️ Критично: официальный FAQ перечисляет ошибку `403 customer_verification_required` — «The team must add a valid payment method before using free credits».** То есть бесплатные кредиты могут требовать привязанной карты. |
| **4. Что бесплатно** | **Месячный включённый кредит** (размер в документации **не опубликован** — «месячный free credit», конкретная цифра **не найдено**). Free tier покрывает **только подмножество каталога** (`/ai-gateway/models?freeTier=true`), не все модели. Лимиты — **пониженные на каждую модель**; точные числа Vercel не публикует: «Limits can change, so this page describes behavior rather than fixed numbers». Free tier — не time-limited trial, кредит продлевается ежемесячно. После первой покупки кредитов free-кредит перестаёт начисляться. |
| **5. Сторонний клиент** | **Работает.** Официально: «An AI Gateway API key authenticates requests from any environment, including local development, CI, and other cloud providers… nothing about AI Gateway requires deploying to Vercel». Проверки клиента нет. |
| **6. Доступность из России** | Официально **не найдено**. Практически: Vercel блокирует доступ/регистрацию из РФ (нужен зарубежный платёжный метод для верификации) — *это не подтверждено официальной страницей*. |
| **7. Источники** | [AI Gateway Pricing](https://vercel.com/docs/ai-gateway/pricing) (last_updated **2026-09-08**); [AI Gateway Rate Limits](https://vercel.com/docs/ai-gateway/rate-limits) (2026-09-08); [AI Gateway FAQ](https://vercel.com/docs/ai-gateway/faq) (2026-09-13); [OpenAI Chat Completions API with AI Gateway](https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions) (2026-09-08); [API Keys](https://vercel.com/docs/ai-gateway/authentication-and-byok/api-keys) (2026-09-08). |
| **8. Достоверность** | **подтверждено официальной страницей** (кроме размера месячного кредита — **не найдено**). |
| **9. Риски** | Free tier — подмножество моделей, лимиты не опубликованы и могут меняться. `403 customer_verification_required` может потребовать карту. 429 может приходить от upstream-провайдера, а не от шлюза. |

---

## 3. GitHub Models — **ВЫВЕДЕН ИЗ ЭКСПЛУАТАЦИИ**

| Поле | Значение |
|---|---|
| **1. Название** | GitHub Models |
| **2. Base URL** | **не найдено / не существует.** Официально: inference API больше не доступен. |
| **3. Доступ** | Невозможен. Playground, каталог моделей, inference API и BYOK «are no longer available to any customer». |
| **4. Что бесплатно** | **Ничего.** Сервис полностью выведен из эксплуатации **30 июля 2026**. Copilot-план не даёт доступа к GitHub Models — «GitHub Models was a separate service from GitHub Copilot and is unrelated to GitHub Copilot services». |
| **5. Сторонний клиент** | Неприменимо. |
| **6. Доступность из России** | Неприменимо. |
| **7. Источник** | [docs.github.com/en/github-models](https://docs.github.com/en/github-models) — «As of July 30, 2026, GitHub Models has been fully retired.» Рекомендованные замены от GitHub: Azure AI Foundry, GitHub Copilot. |
| **8. Достоверность** | **подтверждено официальной страницей.** |
| **9. Риски** | Сторонние агрегаторы (например [OmniRoute FREE-TIERS-GUIDE](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/getting-started/FREE-TIERS-GUIDE.md), снимок 2026-09-03) до сих пор указывают «GitHub Models — audited shared pool estimates ~18M tokens/month». Это **устаревшие данные**; не полагайтесь на них. |

---

## 4. Cloudflare Workers AI

| Поле | Значение |
|---|---|
| **1. Название** | Cloudflare Workers AI |
| **2. Base URL + путь** | `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1` + `POST /chat/completions` (есть `/v1/embeddings`; `/v1/responses` — только для `@cf/openai/gpt-oss-120b` и `@cf/openai/gpt-oss-20b`, только `stream: false`). OpenAI-совместимость: **да** (пример с `openai` SDK приведён в офдоках). Есть также нативный `/ai/run/{model}`. |
| **3. Доступ** | Аккаунт Cloudflare (Workers Free) + API token. **Карта не нужна** для Workers Free. |
| **4. Что бесплатно** | **10 000 Neurons в день** бесплатно, суммарно на все модели (не на модель). Сброс в 00:00 UTC. «Going over does not bill you, the request fails.» На Workers Paid — те же 10 000/день бесплатно, далее $0.011 / 1000 Neurons. На free-плане недоступны (требуют Workers Paid или prepaid AI Gateway credits): `@cf/moonshotai/kimi-k2.6`, `@cf/moonshotai/kimi-k2.7-code`, `@cf/zai-org/glm-5.2`, `@cf/zai-org/glm-5.3`, `@cf/zai-org/glm-5.3-flash`, `@cf/deepseek-ai/deepseek-v4-flash-0731`, `@cf/deepseek-ai/deepseek-v4-pro-0813`. Доступные бесплатные ID (примеры): `@cf/meta/llama-3.1-8b-instruct-fp8-fast`, `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, `@cf/openai/gpt-oss-120b`, `@cf/openai/gpt-oss-20b`, `@cf/google/gemma-4-26b-a4b-it`, `@cf/qwen/qwen3-30b-a3b-fp8`, `@cf/mistralai/mistral-small-3.1-24b-instruct`, `@cf/ibm-granite/granite-4.0-h-micro`. Порядок величины: 10 000 neurons ≈ ~10K output-токенов у дешёвых моделей (`granite-4.0-h-micro` — 1542 neurons/M input, 10158 neurons/M output) и заметно меньше у дорогих. |
| **5. Сторонний клиент** | **Работает.** Обычный API-token, примеры cURL и OpenAI SDK без Vercel-подобных ограничений клиента. |
| **6. Доступность из России** | Официально **не найдено**. Практически Cloudflare доступен из РФ (сам CDN работает), регистрация без карты возможна. |
| **7. Источники** | [Workers AI Pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) (Last updated **Oct 1, 2026**); [OpenAI compatible API endpoints](https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/) (Sep 18, 2026); исключения по моделям подтверждены в [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) сноска [^11]. |
| **8. Достоверность** | **подтверждено официальной страницей.** |
| **9. Риски** | ToS Cloudflare Self-Serve §2.2.1(j) запрещает использовать сервисы как «virtual private network or other similar proxy service» — публичный релей на базе Workers AI технически нарушает ToS (флаг `caution` в [OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md)). Для личного однопользовательского оркестратора риск невелик, для публичного прокси — реален. |

---

## 5. Google AI Studio / Gemini API — **отдельная проверка по РФ и карте**

| Поле | Значение |
|---|---|
| **1. Название** | Google AI Studio + Gemini Developer API |
| **2. Base URL + путь** | Нативно: `https://generativelanguage.googleapis.com/v1beta/`. **OpenAI-совместимо:** `https://generativelanguage.googleapis.com/v1beta/openai/` + `POST /chat/completions` (официально: «You can access Gemini models using the OpenAI libraries (Python and TypeScript/Javascript)… update three lines of code»). BASE URL с завершающим слэшем: `https://generativelanguage.googleapis.com/v1beta/openai/`. |
| **3. Доступ** | Google-аккаунт → API key в AI Studio. **Карта НЕ нужна** для Free tier: «Upgrade to Paid» — отдельный шаг с привязкой billing-аккаунта и **предоплатой минимум $5**. Новым пользователям AI Studio автоматически создаёт default GCP-проект и API-ключ после принятия ToS. |
| **4. Что бесплатно** | Free tier: «Limited access to certain models», «Free input & output tokens», **промпты используются для улучшения продуктов Google**. На free-tier **исторически** были Flash-модели (`gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemma`), а `gemini-2.5-pro` ушёл с free-tier в апреле 2026; `2.0 Flash / Flash-Lite` выключены 2026-06-01. **Google перестала публиковать таблицу per-model free-лимитов**: официальная страница rate-limits теперь говорит «Rate limits depend on multiple factors… you can view them in Google AI Studio», то есть конкретные RPM/RPD **не найдено** в публичной документации. Точную цифру нужно смотреть в `aistudio.google.com/rate-limit`. Три-сторонний источник ([awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis), сноска [^1]) приводит: `gemini-3.6-flash` — 15 RPM / 1 500 RPD; `gemini-3.5-flash-lite`/`3.1-flash-lite` — 30 RPM / 1 500 RPD; `gemini-2.5-pro` — 5 RPM / 50 RPD, и отдельно помечает, что **Google больше не публикует per-model free-лимиты**. Free-tier ограничения были урезаны на 50–80 % в декабре 2025 (по [OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md)). |
| **5. Сторонний клиент** | **Работает полностью.** Официальные примеры на Python/cURL с `base_url="https://generativelanguage.googleapis.com/v1beta/openai/"` и Bearer-ключом. Проверки клиента/сессии нет. Единственное ограничение: Google AI Pro/Ultra **подписка** работает только внутри веб-интерфейса AI Studio, но это не влияет на API-ключ. |
| **6. Доступность из России** | **РОССИИ В СПИСКЕ НЕТ.** Официальная страница [Available regions](https://ai.google.dev/gemini-api/docs/available-regions) (Last updated **2026-04-29**) перечисляет доступные страны и территории; **Россия отсутствует** (в списке есть, например, Армения, Азербайджан, Грузия, Казахстан, Кыргызстан, Молдова, Сербия, Турция, Украина, Узбекистан — но не РФ). Страница прямо говорит: при заходе на AI Studio и получении этой страницы возможны три причины — «Regional limitations: Google AI Studio is not available in your region», возраст 18+, либо непройденная верификация возраста в Google-аккаунте. Обходной путь, упомянутый самой Google: **Gemini API на Gemini Enterprise Agent Platform (Google Cloud)**. |
| **7. Источники** | [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing); [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) (Last updated **2026-09-12**); [OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai); [Available regions](https://ai.google.dev/gemini-api/docs/available-regions) (**2026-04-29**); [Google AI plans](https://ai.google.dev/gemini-api/docs/google-ai-plans) (**2026-08-18**); [Billing](https://ai.google.dev/gemini-api/docs/billing); [Using Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key). |
| **8. Достоверность** | Доступность из РФ и отсутствие требования карты для free tier — **подтверждено официальной страницей**. Конкретные RPM/RPD free-tier — **подтверждено сторонним источником** (Google не публикует). |
| **9. Риски** | Free-tier промпты используются для улучшения продуктов Google (в EEA/UK/CH — исключение). С 28 мая 2026 все новые ключи — auth keys; **неограниченные standard keys API отклоняет**. Потолок бесплатного использования может меняться без предупреждения. Для РФ — прямое нарушение региональных ограничений при попытке доступа без VPN; при использовании VPN есть риск блокировки аккаунта. |

---

## 6. Краткий обзор прочих провайдеров

### 6.1 Chutes.ai — **бесплатного tier больше НЕТ**

| Поле | Значение |
|---|---|
| Base URL | `https://llm.chutes.ai/v1` + `POST /chat/completions`, OpenAI-совместимо (да; официальный Python-пример на сайте использует `requests.post("https://llm.chutes.ai/v1/chat/completions")`). |
| Доступ | Аккаунт (`/signup`), Bittensor-кошелёк или платёж. Free trial: **не найдено**. |
| Что бесплатно | **Ничего.** Модель монетизации — только pay-as-you-go per-token + планы Plus $10/мес и Pro $20/мес + private GPU $1.80/час. Официальный FAQ содержит вопрос «Is there a free trial?» — ответ на странице есть, но среди опубликованных тарифов бесплатного нет. Сторонний источник ([OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md)): «`chutes` — free tier ended 2026-03» (прекращён 15 марта 2026). |
| Сторонний клиент | Работает (Bearer `CHUTES_API_KEY`). |
| РФ | **не найдено.** |
| Источник / достоверность | [chutes.ai/pricing](https://chutes.ai/pricing), [docs.chutes.ai](https://docs.chutes.ai/); факт прекращения free tier — сторонний источник. **подтверждено официальной страницей** (отсутствие бесплатного тарифа) + **подтверждено сторонним источником** (дата отмены). |

### 6.2 Novita AI — бесплатного tier не найдено, только signup-credit

| Поле | Значение |
|---|---|
| Base URL | `https://api.novita.ai/v3/openai` + `POST /chat/completions` (OpenAI-совместимо; официальная API-reference: `docs.novita.ai/api-reference/api-reference-overview` — *таймаут при фетче*). |
| Доступ | Регистрация; карта — по сторонним данным требуется/не требуется **не найдено**. |
| Что бесплатно | На официальной [странице цен](https://novita.ai/pricing) **нет ни одного бесплатного тарифа** — только per-token прайс (например `deepseek-v4-flash` $0.14/M input) и 50 % скидка на Batch API. Сторонний источник ([OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md)): `novita` — **signup credit ~500K токенов**, категория `signup credit` (не повторяющийся), ToS-флаг `caution`. |
| Сторонний клиент | Работает. |
| РФ | **не найдено.** |
| Источник / достоверность | [novita.ai/pricing](https://novita.ai/pricing) — **подтверждено официальной страницей** (бесплатного тарифа на pricing нет). Размер signup-кредита — **подтверждено сторонним источником**. |

### 6.3 Nebius AI Studio (сейчас — Token Factory) — только signup-credit

| Поле | Значение |
|---|---|
| Base URL | **не найдено** — `docs.nebius.com/studio/inference/quickstart` редиректит на `docs.tokenfactory.nebius.com`, все попытки фетча завершились timeout/404. |
| Доступ | Регистрация; карта — **не найдено**. |
| Что бесплатно | По сторонним данным ([OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md)): `nebius` — **signup credit ~1M токенов**, категория `signup credit`, ToS `caution`. Повторяющегося free tier нет. |
| Сторонний клиент | По документации vLLM (`docs.vllm.ai` перечисляет «Nebius Serverless AI» как deployment framework) — да, OpenAI-совместимо, но первоисточник не подтверждён. |
| РФ | **не найдено.** NB: Nebius — компания европейского происхождения с российскими корнями (это контекст, а не официальная информация о доступности). |
| Источник / достоверность | Официальные страницы недоступны → **не подтверждено**; цифры — **подтверждено сторонним источником**. |

### 6.4 Hyperbolic — только signup-credit ~$1–5

| Поле | Значение |
|---|---|
| Base URL | **не найдено** (`www.hyperbolic.ai` не открывается из этой сети: cross-origin redirect / «terminated»). |
| Доступ | Регистрация; для GPU-аренды требуется минимальный депозит **$5** (это не бесплатные кредиты). |
| Что бесплатно | По сторонним данным ([OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md) и его `freeNote`-коррекциям): **~$1 trial credit** на signup; **~5M токенов** записано в каталоге как `signup credit`, ToS `ok`. Строка `$1-5 trial credits on signup` в самом OmniRoute признана частично неточной: «$5 — это минимальный депозит для разблокировки GPU-аренды, а не подарочные кредиты». |
| Сторонний клиент | По сторонним данным — да, OpenAI-совместимо. |
| РФ | **не найдено.** |
| Источник / достоверность | **не подтверждено** (официальный сайт недоступен из этой сети). |

### 6.5 SambaNova Cloud — recurring free tier есть, но цифры не подтверждены официально

| Поле | Значение |
|---|---|
| Base URL | `https://api.sambanova.ai/v1` + `POST /chat/completions` (OpenAI-совместимо; официальный домен `cloud.sambanova.ai`, docs — `docs.sambanova.ai`). |
| Доступ | Регистрация; **карта не нужна** для free tier (по сторонним данным). |
| Что бесплатно | Сторонний источник ([OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md)): `sambanova` — recurring ~6M токенов/мес, с опубликованными лимитами **20 RPM / 20 RPD / 200K TPD**, и это **постоянный recurring free tier**, а не только $5 trial. Официальная страница лимитов — **не найдено** (`docs.sambanova.ai/**` timeout/404 на всех попытках). |
| Сторонний клиент | Да, обычный Bearer-ключ. |
| РФ | **не найдено.** |
| Источник / достоверность | **подтверждено сторонним источником** (20 RPM / 20 RPD / 200K TPD, ~6M/мес); официально — **не подтверждено**. ToS-флаг `caution`. |

### 6.6 NVIDIA NIM (build.nvidia.com) — free-доступ без «1000 кредитов»

| Поле | Значение |
|---|---|
| Base URL | `https://integrate.api.nvidia.com/v1` + `POST /chat/completions` (OpenAI-совместимо). |
| Доступ | **NVIDIA Developer Program**: зарегистрировать email → «Get API Key» на странице модели. **Карта не нужна.** Ключ выдаётся сразу, копируется из попапа. |
| Что бесплатно | Официальная страница API-каталога ([docs.api.nvidia.com/nim/docs/api-quickstart](https://docs.api.nvidia.com/nim/docs/api-quickstart)) описывает только получение бесплатного dev-ключа и вызовы; **упоминаний «1000 кредитов» в ней нет**. По [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis): free для Developer Program, **100+ моделей, лимит 40 RPM / 10 000 RPD на модель** (сторонний источник). По [OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md) старый единоразовый пул кредитов убран, доступ теперь «truly rate-limited, no pool». Доступные model ID (из официальной API-reference, среди прочих): `nvidia/nemotron-3-super-120b-a12b`, `nvidia/nemotron-3-ultra-550b-a55b`, `nvidia/nemotron-3-nano-30b-a3b`, `nvidia/nemotron-3.5-lightning-30b-a3b`, `nvidia/llama-3.1-nemotron-ultra-253b-v1`, `meta/llama-3.1-8b-instruct`, `meta/llama-3.3-70b-instruct`, `moonshotai/kimi-k2-instruct`, `moonshotai/kimi-k3`, `minimaxai/minimax-m2.5/m2.7`, `deepseek-ai/deepseek-v4-flash`, `google/gemma-7b`, `mistralai/mixtral-8x7b-instruct`. |
| **Цифра «1000 кредитов»** | **не найдено** — в официальных доках NVIDIA её нет; вероятно, устаревшая/сторонняя формулировка. |
| Сторонний клиент | Да (обычный Bearer `<nvapi-key>`, официальный Python-пример). |
| РФ | **не найдено.** NB: для моделей NVIDIA действует условие «Trial use only — do not submit personal or confidential data. Your use is logged for security purposes and to improve NVIDIA products and services» (цитируется на [kilo.ai/docs/gateway/models-and-providers](https://kilo.ai/docs/gateway/models-and-providers) по [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis)). |
| Источник / достоверность | Официально: получение ключа и OpenAI-совместимость — **подтверждено официальной страницей** ([api-quickstart](https://docs.api.nvidia.com/nim/docs/api-quickstart), [models-1](https://docs.api.nvidia.com/nim/reference/models-1)). Лимиты 40 RPM / 10 000 RPD — **подтверждено сторонним источником**. «1000 кредитов» — **не подтверждено**. |

### 6.7 Groq — free tier есть, но цифры не подтверждаются из этой сети

| Поле | Значение |
|---|---|
| Base URL | `https://api.groq.com/openai/v1` + `POST /chat/completions` (OpenAI-совместимо). |
| Доступ | Бесплатный API-ключ: создать аккаунт на `console.groq.com`. **Карта не нужна** (официальный README Groq API Cookbook: «you'll need a Groq API key that you can get for free by creating an account here»). |
| Что бесплатно | Free plan с **per-model** лимитами. Сторонний источник ([awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis), сноска [^2]): `openai/gpt-oss-120b` и `openai/gpt-oss-20b` — **30 RPM / 1 000 RPD**; `groq/compound` и `groq/compound-mini` — 30 RPM / **250 RPD**; `qwen/qwen3.6-27b` — 30 RPM / 1 000 RPD. `llama-3.3-70b-versatile` и `llama-3.1-8b-instant` **выключены 2026-08-16**. [OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md) (ре-аудит 2026-09-02) добавляет: **5 per-model cap-ов по 200K TPD** (≈6M токенов/мес каждый), «no payment method on file». |
| Сторонний клиент | Да, стандартный OpenAI-совместимый Bearer. Проверки клиента нет. |
| РФ | **не найдено.** |
| Источник / достоверность | Официальные `console.groq.com/docs/rate-limits` и `/docs/deprecations` — **HTTP 403 Forbidden**; `groq.com/pricing` редиректит на маркетинговую главную. Официально подтверждён только факт бесплатного ключа ([groq-api-cookbook README](https://raw.githubusercontent.com/groq/groq-api-cookbook/main/README.md)). Все цифры — **подтверждено сторонним источником**. |
| Риски | Каталог моделей free-tier быстро меняется; за последние месяцы два популярных ID выключены. |

### 6.8 Cerebras — **постоянно бесплатного tier НЕТ**

| Поле | Значение |
|---|---|
| Base URL | `https://api.cerebras.ai/v1` + `POST /chat/completions` (OpenAI-совместимо). |
| Доступ | Регистрация + **верифицированная карта** («New accounts receive $5 in free credits **after adding a verified payment method**»). |
| Что бесплатно | **Только Free Trial:** $5 кредитов, **истекают через 30 дней**, покрывают все модели Shared Inference. Лимиты Free Trial: `gpt-oss-120b` и `qwen-3.8-27b` — **5 RPM, 30K uncached TPM, 90K total TPM, 1M TPH, 1M TPD**. Официальный FAQ: *«Is there a permanently free tier? **No.** … Cerebras doesn't currently offer a no-cost tier that renews automatically or a per-model always-free allowance.»* «If you skip adding a payment method at sign-up, Playground and API access remain inactive until you do.» |
| Сторонний клиент | Да, OpenAI-совместимый Bearer. |
| РФ | **не найдено.** |
| Источник / достоверность | [inference-docs.cerebras.ai/support/rate-limits](https://inference-docs.cerebras.ai/support/rate-limits) — **подтверждено официальной страницей** (и лимиты, и отсутствие постоянного free tier). |
| Риски | Сторонние каталоги ([OmniRoute FREE-TIERS-GUIDE](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/getting-started/FREE-TIERS-GUIDE.md)) до сих пор пишут «Cerebras — audited pool estimates ~30M tokens/month» — **устаревшая информация**. Доверяйте официальному FAQ. |

### 6.9 Дополнительно (не было в задании, но релевантно для «что подключить первым»)

- **Mistral AI** — Free mode по умолчанию, **без карты**, **$10/мес API-кредитов**, base URL `https://api.mistral.ai/v1`, ~1 RPS / 500K TPM. Промпты free-режима используются для тренировки моделей, можно opt-out. [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) сноска [^13]. **подтверждено сторонним источником.**
- **Z AI / Zhipu** — постоянно бесплатные модели `GLM-4.7-Flash`, `GLM-4.5-Flash` (объявлен вывод), `GLM-4.6V-Flash`; base URL `https://open.bigmodel.cn/api/paas/v4`, международный `https://api.z.ai/api/paas/v4`; **без карты**, регистрация принимает зарубежные номера, для chat-API **реальное имя не требуется**. [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) сноска [^12].
- **Ollama Cloud** — бесплатный tier с сессионными (каждые 5 ч) и недельными лимитами; **OpenAI-совместимо** через `https://ollama.com/v1` (`base_url="https://ollama.com/v1"`, `api_key=OLLAMA_API_KEY`). Официально: [docs.ollama.com/api/openai-compatibility](https://docs.ollama.com/api/openai-compatibility). Прямые числа лимитов — **не найдено** (не опубликованы).
- **Kilo Code Gateway** — `https://api.kilo.ai/api/gateway`, бесплатный пул без API-ключа, **200 req/hr на IP**, роутер `kilo-auto/free`. **подтверждено сторонним источником** ([awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) сноска [^5]); официальная страница `kilo.ai/docs/gateway/authentication` не открылась.
- **OVHcloud AI Endpoints** — **анонимный tier без ключа и без регистрации**, `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`, **2 RPM на IP на модель**; на практике 4 из 4 тестовых запросов вернули 429 ([ClawLabsAI](https://github.com/ClawLabsAI/free-ai-models) сноска [^ovh], проверка 2026-09-23). **подтверждено сторонним источником.**
- **Hugging Face Router** — `https://router.huggingface.co/v1`, всего **$0.10/мес** Inference Provider credits для free-аккаунтов. Практически бесполезно, но бесплатно. **подтверждено сторонним источником.**

---

## 7. Шлюзы-агрегаторы, проксирующие бесплатные модели — оценка рисков

### 7.1 llm7.io

| Поле | Значение |
|---|---|
| Base URL | `https://api.llm7.io/v1` + `POST /chat/completions` (OpenAI-совместимо). |
| Доступ | **Анонимно — без ключа** (только `turbo`-модели); бесплатный токен с `token.llm7.io` повышает лимиты, но не открывает новые модели. |
| Что бесплатно | Аноним: **1 RPS, 10 RPM, 60 запросов/час, 500 000 токенов за 24 ч**. С бесплатным токеном: **2 RPS, 40 RPM, 100 запросов/час, 1 000 000 токенов за 24 ч**. Примеры model ID: `gpt-oss:20b`, `mistral-Nemo-Instruct-2407`, `minimax-m2.7`. |
| Сторонний клиент | Да, обычный HTTP. |
| РФ | **не найдено.** |
| Источник / достоверность | Официальный `docs.llm7.io` — **timeout**; данные из [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) сноска [^10] (там же: анонимный доступ подтверждён живым запросом 2026-08-21) и [OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md). **подтверждено сторонним источником.** |
| **Юридические/этические риски** | ToS-флаг `caution`. Провайдер не раскрывает, какие upstream-API он проксирует и на каких аккаунтах. Анонимный доступ без ключа означает, что **ваш трафик идёт через чужую инфраструктуру**, логирование не гарантировано ни в какую сторону. Каталог моделей ротируется — модель может исчезнуть в любой момент. **Не отправляйте чувствительные данные.** Риск блокировки: средний (провайдер может закрыться или ввести платный tier, как уже делали в этой нише). |

### 7.2 pollinations.ai

| Поле | Значение |
|---|---|
| Base URL | `https://text.pollinations.ai/openai` + `POST` (OpenAI-совместимый формат тела). Также `GET https://text.pollinations.ai/{prompt}` и `GET /models`. |
| Доступ | **Ничего не нужно** для анонимного tier; для повышенных лимитов — регистрация на `auth.pollinations.ai` (free tier «Seed»). |
| Что бесплатно | Официальная таблица тарифов ([APIDOCS.md](https://raw.githubusercontent.com/pollinations/pollinations/master/APIDOCS.md), репозиторий самого проекта): **Anonymous — «One request every 15s», только basic models**; **Seed (бесплатная регистрация) — «One request every 5s», standard models**; Flower — 3s (платно); Nectar — без лимитов (enterprise). С марта 2025 бесплатные изображения получают watermark. |
| Сторонний клиент | Да — так и задумано (есть примеры cURL/Python/JS). |
| РФ | **не найдено.** |
| Источник / достоверность | **подтверждено официальной страницей проекта** ([pollinations/pollinations APIDOCS.md](https://github.com/pollinations/pollinations/blob/master/APIDOCS.md) + raw-версия). NB: [OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md) утверждает «interval throttle ~1 req/6-15s для анонимных» — близко к официальному, но сам OmniRoute считает, что каталог недооценивает ограничения. |
| **Юридические/этические риски** | Это **не прокси чужих API** в юридически грязном смысле: Pollinations — самостоятельный сервис со своей инфраструктурой, лицензия кода MIT, есть публичный ToS/privacy. Риск в другом: (1) **анонимный tier — 1 запрос в 15 секунд**, для оркестратора это почти нерабочая скорость; (2) сервис явно дотируется и может в любой момент закрыть/урезать анонимный tier; (3) для free-tier изображений есть watermark; (4) ToS-флаг в OmniRoute — `caution`. Риск блокировки: ниже среднего (легальный сервис), но стабильность — низкая. |

### 7.3 g4f / GPT4Free (`xtekky/gpt4free`) — **высокий риск**

| Поле | Значение |
|---|---|
| Base URL | `http://localhost:1337/v1` или `http://localhost:8080/v1` (локальный FastAPI «Interference API», OpenAI-совместимый) + `POST /chat/completions`. По умолчанию: `python -m g4f --port 8080`; в slim-Docker Interference API мапится на `1337`. Плюс локальный GUI `http://localhost:8080/chat/` и Python-клиент `from g4f.client import Client`. |
| Доступ | **Ничего не нужно в смысле API-ключей** — но требуется Python 3.10+ и/или Docker, а для части провайдеров — **Chrome/Chromium и HAR/cookies** (автоматизация браузера, опциональный вход в аккаунты провайдеров через VNC на порту 7900). |
| Что бесплатно | «model="auto"» — роутинг на любой доступный провайдер. Список провайдеров меняется, включает (по README) OpenAI-совместимые эндпоинты, PerplexityLabs, Gemini, MetaAI, Pollinations. Конкретные модели и лимиты **не найдено** (документация ссылается на `https://g4f.dev/docs/providers-and-models`). |
| Сторонний клиент | Да — сам проект предоставляет OpenAI-совместимый REST. |
| РФ | **не найдено.** |
| Источник / достоверность | [github.com/xtekky/gpt4free](https://github.com/xtekky/gpt4free) + [raw README](https://raw.githubusercontent.com/xtekky/gpt4free/main/README.md). Архитектура и API — **подтверждено официальной страницей (репозиторием проекта)**. |
| **Юридические/этические риски — ЧЕСТНО** | **Высокие, и их несколько слоёв.** (1) Лицензия самого кода — **GPLv3** (свободно, но производные работы обязаны быть GPL). (2) Многие провайдеры внутри g4f — это **обратная разработка (reverse engineering) приватных веб-эндпоинтов** публичных чат-сервисов (PerplexityLabs, Gemini, MetaAI и т. п.) с использованием automation/cookies/HAR. Это типично **нарушает ToS соответствующих сервисов**, которые прямо запрещают автоматизированный доступ, обход технических ограничений и использование сервиса через сторонние обёртки. Раздел README «Security, privacy & takedown policy» сам признаёт: «If your site appears in the project's links and you want it removed, send proof of ownership… it will be removed promptly» — то есть проект работает в режиме «сначала используем, потом убираем по требованию». (3) **Стабильность крайне низкая**: провайдеры отваливаются, эндпоинты ломаются, нужны постоянные обновления g4f и свежие cookies. (4) **Безопасность**: вы запускаете чужой код, который может исполнять браузерную автоматизацию и хранить ваши cookies/HAR на диске. (5) **Риск блокировки**: от умеренного (ваш IP/аккаунт у конкретного провайдера) до высокого (вплоть до юридических претензий от владельцев сервисов, если вы переиспользуете g4f в продукте). (6) Коммерческое использование — отдельный риск, ни один из проксируемых сервисов на это не давал лицензии. **Для оркестратора с реальными данными — не рекомендую.** |

### 7.4 Списки «free-llm-api-resources» на GitHub — оценка

Найдено несколько актуальных списков, все — сторонние:

| Репозиторий | Что даёт | Оценка |
|---|---|---|
| [ClawLabsAI/free-ai-models](https://github.com/ClawLabsAI/free-ai-models) | Ежедневно обновляемая таблица бесплатных моделей (снимок **04 Oct 2026**), поле `rate_limit`, `health` (ok/sick/dead), источник — публичные API OpenRouter и Pollinations. MIT. | **Самый свежий и самый аккуратный из найденных.** Обновляется GitHub Actions ежедневно в 04:00 UTC, без скрейпинга. **Но это промо-проект своего же платного роутера ZeroLimitAI** — читайте данные, а не рекламный текст. |
| [mnfst/awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis) | Большая ручная таблица «permanent free tiers», с подробными сносками-источниками и датами. | **Качественный и честный**: явно отделяет one-time trial credits от recurring, указывает ToS-нюансы (real-name verification, training on prompts). Есть лёгкая реклама manifest.build. |
| [diegosouzapw/OmniRoute](https://github.com/diegosouzapw/OmniRoute) → `docs/reference/FREE_TIERS.md` + `docs/getting-started/FREE-TIERS-GUIDE.md` | Методологически самый строгий: pool-deduped подсчёт (~1.62B токенов/мес recurring), явные `tos`-флаги (`ok`/`caution`/`ambiguous`/`avoid`), `hardStopGuaranteed`, разбор «почему у конкурентов цифры завышены». | **Лучшая методология, но данные отстают.** Документ сам пишет, что последний полный ре-аудит был **2026-06-17**, частичный — 2026-09-02/03, а per-provider таблица — снимок **2026-06-05**. Прямые ошибки: до сих пор перечисляет **GitHub Models** как живой (~18M токенов/мес) и **Cerebras** как recurring ~30M/мес (в GUIDE). Используйте его для методологии и ToS-флагов, но **цифры перепроверяйте** на официальных страницах. |

**Общий вывод по спискам:** это нормальный инструмент *разведки* (какие провайдеры существуют), но **не источник истины по лимитам**. Провайдеры меняют free tier каждые несколько недель (OpenRouter 200→50 RPD, Groq выключил 2 модели, Chutes закрыл free tier 2026-03, GitHub Models закрылся 2026-07-30, Cerebras убрал бесплатный tier). Любая цифра должна перепроверяться на официальной pricing-странице.

### 7.5 Прочие keyless/прокси-варианты, которые всплыли в исследовании (с предупреждениями)

| Провайдер | Доступ | Лимиты | Риск |
|---|---|---|---|
| **OpenCode Zen / OpenCode Free** | keyless, `https://opencode.ai/zen/v1` | без публичного token cap; 6 ротирующихся free coding-моделей | **КРИТИЧНО: 403 `FreeTierError` — «OpenCode's free tier can only be used from within OpenCode».** Отказ привязан к форме запроса (нужны непустой `tools`, `stream: true` и заголовки сессии/UA OpenCode), а не к аккаунту. ToS прямо ограничивает использование «your own internal use, and not on behalf of or for the benefit of any third party» — флаг `avoid`. Для стороннего Python-клиента **не подходит**. |
| **Kiro AI** | OAuth-флоу | audited ~25K токенов/мес (очень мало) | FAQ прямо запрещает использование с «OpenClaw and similar tools that leverage third-party harnesses» — флаг **`avoid`**. |
| **Logfare** | мгновенный бесплатный ключ, без карты | заявлено без rate limits | **Каждый запрос логируется** для исследования (можно opt-out на logfare.ai/consent). Не для чувствительных данных. |
| **AI Horde** | keyless, community capacity | доступность переменная | crowd-sourced, без SLA и предсказуемости. |
| **DuckDuckGo AI / Meta AI web / iFlytek Spark / Coze / Blackbox / T3 Web / FriendliAI / NLP Cloud / Modal / Fireworks / AI21** | keyless-веб или OAuth | разные | ToS в [OmniRoute FREE_TIERS](https://raw.githubusercontent.com/diegosouzapw/OmniRoute/release/v3.8.52/docs/reference/FREE_TIERS.md) явно запрещают автоматизированный доступ, проксирование, сублицензирование или использование через третьи стороны — большинство помечены `avoid`. Перечислены здесь, чтобы вы их **не** подключали. |

---

## 8. Локальный вариант (fallback без интернета)

### 8.1 Сравнение рантаймов

| Поле | **Ollama** | **llama.cpp (`llama-server`)** | **LM Studio** | **vLLM** |
|---|---|---|---|---|
| **Base URL + chat completions** | `http://localhost:11434/v1` + `POST /chat/completions` | `http://localhost:8080/v1` + `POST /chat/completions` (порт задаётся `--port`, дефолт **8080**) | `http://localhost:1234/v1` + `POST /chat/completions` | `http://localhost:8000/v1` + `POST /chat/completions` (порт задаётся `--port`, дефолт **8000**) |
| **OpenAI-совместимость** | **Частично** — официально «Ollama supports a subset of the OpenAI API»: `/v1/chat/completions`, `/v1/models`, `/v1/embeddings`, `/v1/responses`; api_key **игнорируется** (`api_key='ollama'` обязателен синтаксически) | **Частично/да** — официально «no strong claims of compatibility with OpenAI API spec», но работает с `openai` Python SDK; есть `/v1/models`, `/v1/completions`, `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`, плюс Anthropic-совместимый `/v1/messages` | **Да, шире всех по эндпоинтам**: `/v1/models`, `/v1/responses`, `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings` | **Да** — `/v1/completions`, `/v1/chat/completions`, `/v1/responses`, плюс доп. параметры |
| **Установка/доступ** | `curl -fsSL https://ollama.com/install.sh \| sh` + `ollama pull <model>` | Сборка из исходников или готовые бинарники; `llama-server -m model.gguf` | GUI-приложение (Windows x64/ARM, macOS Apple Silicon, Linux AppImage); модель качается в UI | `pip install vllm` + `vllm serve <hf-model>` |
| **Требования** | 8 GB RAM — только маленькие модели; 16 GB+ комфортно | CPU-only работает; GPU по `-ngl` | **Официально: Windows/Linux — 16 GB RAM рекомендовано, ≥ 4 GB VRAM; macOS — Apple Silicon M1/M2/M3/M4, macOS 14+, 16 GB+ RAM, Intel-маки не поддерживаются** | **Только NVIDIA/AMD GPU (или CPU-сборка)**; на одного пользователя оверкилл |
| **Сторонний клиент** | Да, любой HTTP-клиент | Да | Да | Да |
| **РФ** | Работает офлайн после скачивания модели | Работает офлайн | Работает офлайн; но установщик/LM Studio требуют первичного скачивания | Работает офлайн |
| **Источники** | [docs.ollama.com/api/openai-compatibility](https://docs.ollama.com/api/openai-compatibility), [ollama.com/library/deepseek-r1](https://ollama.com/library/deepseek-r1) | [tools/server/README.md](https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md) | [lmstudio.ai/docs/developer/openai-compat](https://lmstudio.ai/docs/developer/openai-compat), [system-requirements](https://lmstudio.ai/docs/app/system-requirements), [parallel-requests](https://lmstudio.ai/docs/app/advanced/parallel-requests) | [docs.vllm.ai OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/), [Quickstart](https://docs.vllm.ai/en/latest/getting_started/quickstart/) |
| **Достоверность** | **подтверждено официальной страницей** | **подтверждено официальной страницей (репозиторием)** | **подтверждено официальной страницей** | **подтверждено официальной страницей** |

**Замечания по портам (эмпирические, официальными страницами не подтверждены — «не подтверждено»):**
- Ollama 11434, LM Studio 1234, llama.cpp 8080, vLLM 8000 — это дефолты; llama.cpp `-h` показывает `--port PORT port to listen (default: 8080)`, Ollama и LM Studio фигурируют в официальных примерах как `localhost:11434` и `localhost:1234`. Дефолт vLLM 8000 в профетченных фрагментах не отобразился — проверьте `vllm serve --help`.
- LM Studio официально предупреждает: «make sure your GGUF runtime is upgraded to llama.cpp v2.0.0» для parallel requests; Max Concurrent Predictions по умолчанию **4**.

### 8.2 Сколько VRAM/RAM нужно для моделей уровня 7B–14B

**Ориентир, подтверждённый официальным каталогом Ollama** ([ollama.com/library/deepseek-r1](https://ollama.com/library/deepseek-r1), размеры файлов квантованных GGUF, 128K контекст):

| Модель | Размер файла (≈ VRAM при полном оффлоаде) | Комментарий |
|---|---|---|
| `deepseek-r1:1.5b` | **1.1 GB** | влезет на любую встройку |
| `deepseek-r1:7b` | **4.7 GB** | комфортно на 8 GB VRAM |
| `deepseek-r1:8b` (latest) | **5.2 GB** | 8 GB VRAM, дефолтный контекст |
| `deepseek-r1:14b` | **9.0 GB** | нужно **≥ 10–12 GB VRAM** (или частичный оффлоад на 8 GB с просадкой) |
| `deepseek-r1:32b` | 20 GB | 16 GB VRAM не хватит без оффлоада |
| `deepseek-r1:70b` | 43 GB | нужен 48 GB VRAM или multi-GPU |
| `deepseek-r1:671b` | 404 GB | серверный класс |

Эти размеры — размеры **файлов моделей**, то есть это нижняя граница потребления. Реальный расход = размер весов + KV-cache (растёт линейно с контекстом, `-ctk`/`-ctv` в llama.cpp позволяют сжать KV до `q8_0`/`q4_0`, экономя 2–4×) + оверхед рантайма (~0.5–1.5 GB).

**Практические ориентиры для 7B–14B:**
- **7B–8B в Q4_K_M**: 4.5–5.5 GB VRAM → хватает **8 GB VRAM** (RTX 3060 Ti/4060) или **16 GB system RAM** для CPU-инференса.
- **14B в Q4_K_M**: 8.5–9.5 GB VRAM → нужно **12 GB VRAM** (RTX 3060 12GB / 4070) или **24–32 GB RAM** для CPU.
- **14B в Q8_0 или FP16**: 15–28 GB → **16–24 GB VRAM** или частичный оффлоад.
- Минимальные официальные требования LM Studio: **Windows/Linux — 16 GB RAM recommended, ≥ 4 GB dedicated VRAM**; **macOS — Apple Silicon, 16 GB+ RAM** (на 8 GB «still be able to use… but stick to smaller models and modest context sizes»).

*Что «не найдено»:* официальной таблицы «VRAM для 7B/14B» ни Ollama, ни llama.cpp, ни LM Studio, ни vLLM не публикуют — цифры выше выведены из официально опубликованных размеров квантованных моделей Ollama и официальных системных требований LM Studio.

### 8.3 Рекомендуемая конфигурация локального fallback

- **Минимальный (CPU-only, 16 GB RAM):** Ollama + `gpt-oss:20b` или `deepseek-r1:7b` на `http://localhost:11434/v1`. `api_key="ollama"` (игнорируется).
- **Оптимальный (8 GB VRAM):** LM Studio или Ollama + модель 7B–8B в Q4_K_M, `http://localhost:1234/v1` или `:11434/v1`.
- **Продвинутый (12–24 GB VRAM, multi-user):** llama.cpp `llama-server --port 8080 --host 0.0.0.0 -np <slots> -cb -fa auto -ctk q8_0 -ctv q8_0` + модель 14B, или vLLM для батчинга.

---

## 9. Итог: ранжированный ТОП-5 «что подключить первым» к оркестратору

Оркестратор — сторонний Python-клиент (httpx / OpenAI SDK), поэтому **главный фильтр — п.5 «работает ли из стороннего клиента»**. Все пять вариантов ниже проходят этот фильтр.

### 🥇 1. Google AI Studio / Gemini API (free tier)
**Почему первым:** чистый OpenAI-совместимый `/chat/completions`, карта не нужна, проверки клиента нет, качество моделей на free tier (Flash-семейство) выше всего остального в списке, лимиты порядка 1 500 RPD на Flash-модели — на порядок больше, чем у OpenRouter free (50 RPD). Нативно поддерживается в любом OpenAI SDK.
**Оговорки:** **официально недоступен из России** (РФ отсутствует в [available-regions](https://ai.google.dev/gemini-api/docs/available-regions)). Free-промпты используются для улучшения продуктов Google. Точные RPM/RPD надо смотреть в личном кабинете AI Studio, публичной таблицы Google больше не публикует. **Если оркестратор работает из РФ напрямую — этот вариант нерабочий; тогда он опускается ниже или заменяется на #2.**

### 🥈 2. OpenRouter `:free` (с `openrouter/free` как авто-роутером)
**Почему:** самый широкий бесплатный каталог (21+ chat-модель на снимке 2026-10-04), включая крупные MoE (Nemotron 3 Super 120B/Ultra 550B) и vision/audio, полностью OpenAI-совместимо, карта не нужна, проверки клиента нет, есть готовый авто-роутер с failover (`openrouter/free`). Идеален как «мультимодельный» резерв для оркестратора.
**Оговорки:** **50 RPD на аккаунт** — это очень мало; выгодный режим 1 000 RPD требует разовой покупки $10, что из РФ проблематично. 20 RPM. `:free`-модели требуют включённого разрешения на логирование промптов. Не проверено официально из-за Cloudflare (403), но проверено двумя независимыми сторонними источниками.

### 🥉 3. Cloudflare Workers AI (Workers Free)
**Почему:** 10 000 Neurons/день бесплатно, карта не нужна, полноценный OpenAI-совместимый `/v1/chat/completions`, работает из любого HTTP-клиента, аккаунт Cloudflare не требует зарубежной карты. Есть адекватные модели (`@cf/openai/gpt-oss-120b`, `@cf/meta/llama-3.3-70b-instruct-fp8-fast`, `@cf/google/gemma-4-26b-a4b-it`).
**Оговорки:** 10 000 Neurons/день — это порядка **10K output-токенов у дешёвой модели** и заметно меньше у дорогих, то есть ~несколько десятков запросов в день. Несколько сильных моделей (Kimi K2.6, GLM 5.2/5.3, DeepSeek V4) требуют платного плана. ToS запрещает использование как публичного прокси.

### 4. Vercel AI Gateway (free tier)
**Почему:** чистый OpenAI-совместимый `/v1`, официально аутентифицируется из «any environment, including local development, CI, and other cloud providers», месячный бесплатный кредит не истекает как trial, zero-markup.
**Оговорки — главные:** свободных кредитов **может потребоваться привязка карты** (`403 customer_verification_required` прямо описан в официальном FAQ), лимиты и размер кредита **не опубликованы**, free tier покрывает только подмножество каталога. Из РФ почти наверняка требует зарубежный платёжный метод. Стоит №4, а не выше, именно из-за неопределённости и карты.

### 5. Локальный fallback: **Ollama** (+ при желании LM Studio / llama.cpp)
**Почему в топ-5 обязательно:** это **единственный вариант, который не зависит ни от интернета, ни от чужого ToS, ни от лимитов, ни от доступности из РФ**. `http://localhost:11434/v1/chat/completions`, `api_key="ollama"` (игнорируется), любой OpenAI SDK. 7B–8B в Q4 (4.7–5.2 GB по официальному каталогу Ollama) работают на 8 GB VRAM / 16 GB RAM; 14B (9.0 GB) — на 12 GB VRAM.
**Оговорки:** официально «supports a subset of the OpenAI API» — не все параметры и не все эндпоинты доступны. Качество 7B–14B заметно ниже облачных Flash/Nemotron. Первичное скачивание модели требует интернета.
**Немедленный резерв на случай отказа облака:** `llama-server` (`:8080/v1`) или LM Studio (`:1234/v1`) — оба тоже проходят фильтр стороннего клиента.

---

## 10. Что НЕ подключать (или подключать с осторожностью)

| Провайдер | Причина |
|---|---|
| **GitHub Models** | **Сервис полностью выведен из эксплуатации 30 июля 2026.** Официально. Никакого бесплатного tier больше не существует. |
| **Cerebras** | Постоянно бесплатного tier **нет** (официальный FAQ). Только $5 на 30 дней и **с обязательной картой**. |
| **Chutes.ai** | Бесплатный tier закрыт в марте 2026; сейчас только PAYG и подписки $10–20/мес. |
| **OpenCode Zen / OpenCode Free** | `403 FreeTierError` — «free tier can only be used from within OpenCode». Для стороннего клиента непригодно, ToS-флаг `avoid`. |
| **Kiro AI** | ToS прямо запрещает third-party harnesses; free-пул ~25K токенов/мес. Флаг `avoid`. |
| **g4f / GPT4Free** | Reverse-engineered веб-эндпоинты, нарушение ToS множества сервисов, GPLv3, нестабильность, риск юридических претензий. **Не для оркестратора с реальными данными.** |
| **Nebius / Hyperbolic / Novita** | Бесплатно только одноразовые signup-кредиты (~0.5–5M токенов), не recurring. Официальные страницы недоступны для верификации. |
| **llm7.io, Pollinations, OVHcloud anonymous, Kilo free pool, HuggingFace** | Легально, но либо микроскопические лимиты (Pollinations 1 req/15s anonymous; HF $0.10/мес; OVH 2 RPM и 429 на практике), либо непрозрачная инфраструктура (llm7.io). Как «проба пера» — да, как основа оркестратора — нет. |

---

## 11. Сводная таблица-шпаргалка (то, что реально можно вставить в конфиг)

| Провайдер | base_url | api_key | Бесплатно | Сторонний клиент | Официально подтверждено |
|---|---|---|---|---|---|
| Gemini API | `https://generativelanguage.googleapis.com/v1beta/openai/` | Gemini key | Flash-модели, ~1.5K RPD (сторонний) | ✅ | ✅ (кроме цифр) |
| OpenRouter | `https://openrouter.ai/api/v1` | OpenRouter key | `:free` модели, 20 RPM / 50 RPD | ✅ | ❌ (403) |
| Cloudflare Workers AI | `https://api.cloudflare.com/client/v4/accounts/{id}/ai/v1` | CF token | 10K Neurons/день | ✅ | ✅ |
| Vercel AI Gateway | `https://ai-gateway.vercel.sh/v1` | AI Gateway key | месячный кредит + подмножество моделей | ✅ | ✅ (кроме цифр) |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `nvapi-...` | 100+ моделей, 40 RPM / 10K RPD (сторонний) | ✅ | ✅ (кроме цифр) |
| Groq | `https://api.groq.com/openai/v1` | `gsk_...` | per-model, ~30 RPM / 250–1000 RPD | ✅ | ❌ (403) |
| SambaNova | `https://api.sambanova.ai/v1` | SN key | recurring, 20 RPM / 20 RPD / 200K TPD (сторонний) | ✅ | ❌ |
| Mistral | `https://api.mistral.ai/v1` | Mistral key | $10/мес кредитов, ~1 RPS | ✅ | ❌ |
| Z AI (GLM Flash) | `https://api.z.ai/api/paas/v4` | Z key | GLM-4.7-Flash и др., бесплатно | ✅ | ❌ |
| Ollama Cloud | `https://ollama.com/v1` | `OLLAMA_API_KEY` | сессионные/недельные лимиты | ✅ | ✅ |
| **Ollama (локально)** | `http://localhost:11434/v1` | `ollama` (игнор) | всё, без лимитов | ✅ | ✅ |
| **llama.cpp (локально)** | `http://localhost:8080/v1` | `sk-no-key-required` | всё | ✅ | ✅ |
| **LM Studio (локально)** | `http://localhost:1234/v1` | любой | всё | ✅ | ✅ |
| **vLLM (локально)** | `http://localhost:8000/v1` | `EMPTY`/`--api-key` | всё | ✅ | ✅ (порт — не подтверждено) |

---

*Отчёт собран 2026-10-05. Ни одна цифра не выдумана: где официальный источник был недоступен (403/451/timeout), это явно указано, и приведена метка «подтверждено сторонним источником» или «не найдено».*
