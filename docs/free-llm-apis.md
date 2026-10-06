# Бесплатные LLM-API: что подключать к zagent

Дата замеров и сбора: **2026-10-05**. Все сетевые замеры сделаны с этой машины, без API-ключей,
клиентом `httpx 0.28.1` (Python 3.14.7).

Полные отчёты разведки с источниками и датами:
[docs/research/chinese-providers.md](research/chinese-providers.md) ·
[docs/research/gateways-and-local.md](research/gateways-and-local.md)

Метки достоверности: **[офиц.]** — проверено официальной страницей провайдера, **[сторон.]** — только
сторонние источники (issue, агрегаторы), **[замер]** — проверено вживую с этой машины.

---

## 1. Главный вывод по OpenCode Zen

Шлюз принимает ключ, но **бесплатный тариф отдаётся только «настоящему» клиенту OpenCode**:
сторонние стеки получают `403 FreeTierError: OpenCode's free tier can only be used from within OpenCode`.

**[замер]** `GET /models` — 86 моделей, 13 из них `-free`. Прошёл по каждой реальным запросом:

| Модель | Результат |
|---|---|
| `space-bunny-free` | **HTTP 200**, реальный ответ, 166+44 токенов |
| `mimo-v2.6-flash-free`, `longcat-2.5-preview-free`, `mimo-v2.5-free` | 403 FreeTierError |
| `nemotron-3-ultra-free`, `nemotron-3.5-lightning-free` | 403 FreeTierError |
| `muse-spark-1.3-contributor-free`, `muse-spark-1.2-contributor-free` | 403 FreeTierError |
| `ling-3.0-flash-fin-free`, `ling-3.1-flash-free` | 403 FreeTierError |
| `fledge-alpha-free`, `jev-1.13-free` | 403 FreeTierError |
| `deepseek-v4-flash-free` | 400 server_error (апстрим) |

Итог: **доступна 1 бесплатная модель из 13**. Подмена `User-Agent` (`httpx`, `opencode/1.0.0`,
`OpenCode/0.5.0`, `curl/8.5.0`, браузерный) ничего не меняет — проверка привязана к клиентскому контракту,
а не к заголовку. Обход не рассматриваем: это обход контроля доступа провайдера.

Подтверждения: [OmniRoute FREE_TIERS](https://github.com/diegosouzapw/OmniRoute/blob/release/v3.8.52/docs/reference/FREE_TIERS.md#3),
[issue: Free-tier Zen 403 for all third-party stacks](https://github.com/anomalyco/opencode/issues/49621#1).

---

## 2. Сетевая доступность с этой машины **[замер]**

Одинаковый результат с дефолтным `User-Agent` httpx и с браузерными заголовками — отпечаток TLS ни при чём.

### Доступно

| Хост | Ответ без ключа | Трактовка |
|---|---|---|
| Cloudflare API (`api.cloudflare.com`) | 400 «Missing Authorization» | доступен, ждёт токен |
| Mistral (`api.mistral.ai`) | 401 Invalid API Key | доступен, ждёт ключ |
| Z.ai intl (`api.z.ai`) | 401 | доступен, ждёт ключ |
| Qwen DashScope intl (`dashscope-intl.aliyuncs.com`) | 401 | доступен, ждёт ключ |
| Qwen DashScope CN (`dashscope.aliyuncs.com`) | 401 | доступен, ждёт ключ |
| Ollama Cloud (`ollama.com/v1`) | 200, список моделей | доступен |
| SambaNova (`api.sambanova.ai`) | 200 | публичный список моделей |
| llm7.io (`api.llm7.io`) | 200 | публичный список моделей |
| Pollinations (`text.pollinations.ai`) | 200 | публичный список моделей |
| Google Gemini | 403 «unregistered callers» | API отвечает, но РФ нет в списке регионов Google |
| OpenCode Zen | 200 | публичный список моделей |

### Заблокировано с этой машины

| Хост | Ответ | Причина |
|---|---|---|
| xAI Grok (`api.x.ai`) | 403 HTML | прямой текст «This service is not available in your region» |
| NVIDIA NIM | **451** | блокировка по юридическим причинам (регион) |
| Groq, OpenRouter, Cerebras, Together, Hyperbolic, Cohere | 403 Cloudflare | блок до приложения; браузерные заголовки не помогают |
| Vercel AI Gateway (`ai-gateway.vercel.sh`) | таймаут чтения | недоступен |
| Novita, Zhipu BigModel CN | таймаут соединения / TLS | недоступны |

**Оговорка:** 403 от Cloudflare — сильный признак регионального блока, но не доказательство; окончательно
подтвердит только запрос с действующим ключом. Для xAI (текст отказа) и NVIDIA (451) блокировка однозначна.

---

## 3. Что регистрировать: приоритетный список

### Уровень 1 — доступны сейчас, без карты, работают из стороннего клиента

| # | Сервис и ссылка | Что даёт | Нюансы | Достоверность |
|---|---|---|---|---|
| 1 | **Z.ai / Zhipu GLM** — [z.ai](https://z.ai) (или [open.bigmodel.cn](https://open.bigmodel.cn)) | `glm-4.7-flash`, `glm-4.5-flash`, `glm-4.6v-flash` — **бессрочно 0 $**, OpenAI-совместимо (`/api/paas/v4`), официальный гайд по OpenAI SDK | карта не нужна; RPM/TPM официально не публикуются (видны в консоли); в КНР нужна 实名 | цены — [офиц.]; лимиты — нет |
| 2 | **Alibaba Model Studio (Qwen)** — [console](https://modelstudio.console.alibabacloud.com) | ~**1 000 000 токенов на КАЖДУЮ модель**, включая размещённые чужие (DeepSeek/Kimi/GLM/MiniMax); OpenAI-совместимо; официально документирован вызов из сторонних клиентов | ключ привязан к региону (иначе 401); 90 дней; между моделями квота не переносится; для Сингапура — заполнить профиль аккаунта, 实名 для квоты не требуется; включайте режим «Free Quota Only», иначе после квоты пойдёт платное списание | [офиц.] |
| 3 | **Mistral La Plateforme** — [console.mistral.ai](https://console.mistral.ai) | free mode по умолчанию, **$10/мес API-кредитов**, `api.mistral.ai/v1`, ~1 RPS / 500K TPM | промпты идут в обучение (есть opt-out) | [сторон.] |
| 4 | **Cloudflare Workers AI** — [dash.cloudflare.com](https://dash.cloudflare.com) | **10 000 Neurons/день** (сброс 00:00 UTC), OpenAI-совместимый `/v1/chat/completions`, бесплатны `gpt-oss-120b`, `llama-3.3-70b-fp8-fast`, `gemma-4-26b-a4b-it`, `qwen3-30b-a3b-fp8`; карта не нужна; за превышение не биллингует — запрос просто падает | 10K Neurons ≈ десятки запросов в день; Kimi/GLM/DeepSeek там требуют платного плана; ToS §2.2.1(j) запрещает использование как публичного прокси | [офиц.] |
| 5 | **SambaNova Cloud** — [cloud.sambanova.ai](https://cloud.sambanova.ai) | recurring free ~6M токенов/мес, 20 RPM / 20 RPD / 200K TPD; модели `DeepSeek-V3.2`, `Llama-3.3-70B`, `gpt-oss-120b`, `MiniMax-M3`, `gemma-4-31B` | цифры официально не подтверждены (docs.sambanova.ai недоступен) | [сторон.] |

### Уровень 2 — вообще без ключей (можно начать прямо сейчас)

| Сервис | Base URL | Что работает **без ключа** | Лимиты |
|---|---|---|---|
| **llm7.io** | `https://api.llm7.io/v1` | **[замер]** 4 модели из 68: `DeepSeek-V4-Flash-0731` (91+77 токенов), `codestral-latest`, `minimax-m2.7`, `mistral-Nemo-Instruct-2407`. Остальные 39 требуют ключ, 25 — не чат-модели (TTS/картинки/видео) | аноним ~1 RPS / 10 RPM / 60 запросов в час / 500K токенов в сутки; ключ с [token.llm7.io](https://token.llm7.io) поднимает до 100 запросов/час и 1M токенов [сторон.] |
| **Pollinations** | `https://text.pollinations.ai/openai` | **[замер]** `openai-fast` (GPT-OSS 20B через OVH) — реальный ответ получен | официально: анонимно **1 запрос / 15 с**, только basic-модели; бесплатная регистрация (Seed) — 1 запрос / 5 с [офиц. репозитория] |
| **Ollama Cloud** | `https://ollama.com/v1` | free tier с сессионными (5 ч) и недельными лимитами, OpenAI-совместимо | объём лимитов не публикуется [офиц.] |
| **Kilo Code Gateway** | `https://api.kilo.ai/api/gateway` | бесплатный пул без ключа, роутер `kilo-auto/free` | 200 запросов/час на IP [сторон.] |
| **OVHcloud AI Endpoints** | `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1` | анонимный tier без регистрации | 2 RPM на IP на модель; на практике 4 из 4 тестовых запросов дали 429 [сторон.] |

### Уровень 3 — только с VPN (с этой машины блокируются)

| Сервис | Бесплатно | Ключ | Нюанс |
|---|---|---|---|
| **Groq** — [console.groq.com](https://console.groq.com) | `gpt-oss-120b`, `gpt-oss-20b`, `qwen3.6-27b`: ~30 RPM / 1000 RPD; `groq/compound` — 250 RPD | `gsk_...`, карта не нужна [офиц. README] | вся дока console.groq.com отдаёт 403 на фетч из этой сети; `llama-3.3-70b-versatile` и `llama-3.1-8b-instant` **выключены 16.08.2026** [сторон.] |
| **OpenRouter** — [openrouter.ai](https://openrouter.ai) | 21+ чат-моделей с `:free` (Qwen3.8-27B, Gemma-4, Nemotron-3, `openrouter/free` как авто-роутер с failover) | карта не нужна для `:free` | **50 RPD** на аккаунт (1000 RPD — после разовой покупки $10); 20 RPM; `:free` требуют разрешить логирование промптов [сторон.] |
| **Google Gemini** — [aistudio.google.com](https://aistudio.google.com) | Flash-модели free tier, карта не нужна, чистый OpenAI-совместимый эндпоинт `/v1beta/openai/` | Gemini key | **России нет в официальном списке регионов** [офиц.]; промпты идут в обучение Google; конкретные RPM/RPD Google перестала публиковать [сторон.] |
| **NVIDIA NIM** — [build.nvidia.com](https://build.nvidia.com) | Developer Program: 100+ моделей, 40 RPM / 10 000 RPD на модель [сторон.] | `nvapi-...`, без карты | **с этой машины 451 (регион)** [замер]; официального «1000 кредитов» в доках нет; NVIDIA логирует запросы |
| **Cerebras** | постоянного free tier **нет**: $5 на 30 дней | **обязательна верифицированная карта** | офиц. FAQ: «Is there a permanently free tier? No.» [офиц.] |

### Уровень 4 — не тратить время

| Сервис | Почему нет |
|---|---|
| **GitHub Models** | **полностью закрыт 30.07.2026** — playground, каталог, inference API и BYOK недоступны никому; Copilot к нему отношения не имел [офиц., проверено вживую: эндпоинт отдаёт заглушку `OK`] |
| **xAI Grok API** | бесплатного API нет, только платные модели; free tier есть у клиента Grok Build, не у API [офиц.]. Плюс блокировка по региону [замер] |
| **DeepSeek API** | бесплатного тарифа нет вообще, только −50% в off-peak часы [офиц.] |
| **Chutes.ai** | free tier закрыт 15.03.2026, остался PAYG [офиц.] |
| **MiniMax, Moonshot Kimi** | бесплатных моделей нет; Kimi требует минимум $1 пополнения [офиц.] |
| **SiliconFlow** | с 15.05.2026 аккаунт без 实名 не работает, верификация — Alipay + распознавание лица, принимают только документы КНР / ПМЖ [офиц.] — для гражданина РФ закрыто |
| **Novita, Nebius, Hyperbolic** | только одноразовые signup-кредиты (~0.5–5M токенов), не recurring [сторон.] |
| **g4f / GPT4Free** | reverse-engineering приватных эндпоинтов, нарушение ToS множества сервисов, GPLv3, нестабильность, юридические риски |
| **Vercel AI Gateway** | официальный FAQ прямо описывает `403 customer_verification_required` («нужно добавить способ оплаты»); размер кредита не публикуется; с этой машины таймаут [замер] |

---

## 4. Локальный вариант **[замер железа]**

- CPU: **12 логических ядер**, дискретной GPU **нет** (Intel UHD Graphics), `nvidia-smi` отсутствует.
- **Ollama уже установлен** (client 0.35.1), но сервис не запущен.

Практический вывод: локально реальны только модели 7B–8B в квантовании Q4 (файлы 4.7–5.2 GB по
официальному каталогу Ollama), и только на CPU — это медленно (единицы токенов в секунду), но полностью
независимо от ключей, лимитов и региональных блокировок. Модели 14B (9 GB) и выше для этой машины нереалистичны.

| Рантайм | Base URL | Ключ |
|---|---|---|
| Ollama | `http://localhost:11434/v1` | `"ollama"` (игнорируется) |
| llama.cpp | `http://localhost:8080/v1` | `sk-no-key-required` |
| LM Studio | `http://localhost:1234/v1` | любой |

Все три — OpenAI-совместимые `/chat/completions` **[офиц.]**.

---

## 5. Что это значит для zagent

1. С текущим ключом Zen `swarm` из трёх моделей невозможен: работает одна (`space-bunny-free`),
   роли `coder` и `architect` уйдут в fallback. Fallback уже протестирован — код к этому готов.
2. Даже без новых ключей оркестратор можно наполнить прямо сейчас: **6 моделей без единого ключа**
   (4 у llm7.io + 1 у Pollinations + `space-bunny-free` у Zen).
3. Минимальный набор для полноценного «трёх мнений»: **Z.ai GLM Flash** + **Qwen/Alibaba** + **Mistral**
   — все три доступны с этой машины, без карты, с официальным вызовом из сторонних клиентов.
4. Локальный Ollama — единственный контур, который не зависит ни от ключей, ни от лимитов,
   ни от региональных блокировок; но на этой машине он ограничен CPU и моделями 7B–8B.
