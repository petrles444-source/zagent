# Бесплатные модели через API — живой каталог

Обновлено: **2026-10-05T03:34:42Z**. Чат-моделей: **39**, пригодных: **37**.

Статусы: `blocked` — 2, `limited` — 7, `ok` — 27, `slow` — 3.

## Шлюзы

| Шлюз | Base URL | Ключ | /responses | Моделей | Пригодных |
|---|---|---|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | есть | да | 17 | 15 |
| Groq | `https://api.groq.com/openai/v1` | есть | да | 3 | 3 |
| Z.ai / GLM | `https://api.z.ai/api/paas/v4` | есть | да | 3 | 3 |
| Mistral La Plateforme | `https://api.mistral.ai/v1` | есть | да | 3 | 3 |
| Cloudflare Workers AI | `https://api.cloudflare.com/client/v4/accounts/{cloudflare_account_id}/ai/v1` | есть | нет | 8 | 8 |
| llm7.io (keyless) | `https://api.llm7.io/v1` | не нужен | нет | 4 | 4 |
| OpenCode Zen | `https://opencode.ai/zen/v1` | не нужен | нет | 1 | 1 |
| Ollama (локально) | `http://localhost:11434/v1` | не нужен | да | 0 | 0 |

Ключи берутся из `config/secrets.local.json` или переменных окружения (имя = `ZAGENT_<ID>_API_KEY`). В репозиторий ключи не попадают.

## Модели

| Модель | Шлюз | Статус | Время | Токены | Контекст | Источник |
|---|---|---|---|---|---|---|
| `@cf/google/gemma-4-26b-a4b-it` | Cloudflare Workers AI | ok | 0.9s | 24+137 | — | static |
| `@cf/ibm-granite/granite-4.0-h-micro` | Cloudflare Workers AI | ok | 0.4s | 40+2 | — | static |
| `@cf/meta/llama-3.1-8b-instruct-fp8-fast` | Cloudflare Workers AI | ok | 0.3s | 43+3 | — | static |
| `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Cloudflare Workers AI | ok | 0.4s | 43+4 | — | static |
| `@cf/mistralai/mistral-small-3.1-24b-instruct` | Cloudflare Workers AI | ok | 0.6s | 11+2 | — | static |
| `@cf/openai/gpt-oss-120b` | Cloudflare Workers AI | ok | 0.8s | 74+45 | — | static |
| `@cf/openai/gpt-oss-20b` | Cloudflare Workers AI | ok | 0.5s | 76+40 | — | static |
| `@cf/qwen/qwen3-30b-a3b-fp8` | Cloudflare Workers AI | ok | 2.0s | 16+256 | — | static |
| `openai/gpt-oss-120b` | Groq | ok | 1.0s | 78+40 | — | static |
| `openai/gpt-oss-20b` | Groq | ok | 0.2s | 78+40 | — | static |
| `qwen/qwen3.8-27b` | Groq | ok | 0.1s | 18+2 | — | static |
| `DeepSeek-V4-Flash-0731` | llm7.io (keyless) | limited | 0.2s | 0+0 | — | static |
| `GLM-5.3-Flash` | llm7.io (keyless) | limited | 0.2s | 0+0 | — | static |
| `codestral-latest` | llm7.io (keyless) | limited | 0.2s | 0+0 | — | static |
| `minimax-m2.7` | llm7.io (keyless) | limited | 0.1s | 0+0 | — | static |
| `codestral-latest` | Mistral La Plateforme | ok | 0.3s | 11+2 | — | static |
| `ministral-3b-latest` | Mistral La Plateforme | ok | 0.4s | 11+8 | — | static |
| `ministral-8b-latest` | Mistral La Plateforme | ok | 0.3s | 11+6 | — | static |
| `apodex/apodex-1.1-mini:free` | OpenRouter | ok | 1.5s | 16+165 | 262K | live |
| `cohere/north-mini-code:free` | OpenRouter | slow | 6.2s | 8+35 | 256K | live |
| `dots-studio/dots-3-note-preview:free` | OpenRouter | ok | 2.3s | 21+67 | 512K | live |
| `google/gemma-4-26b-a4b-it:free` | OpenRouter | limited | 0.4s | 0+0 | 262K | live |
| `google/gemma-4-31b-it:free` | OpenRouter | limited | 0.4s | 0+0 | 262K | live |
| `inclusionai/ling-3.0-flash-sante:free` | OpenRouter | ok | 1.3s | 30+47 | 262K | live |
| `liquid/lfm-2.5-2.6b:free` | OpenRouter | ok | 1.0s | 18+256 | 65K | live |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | OpenRouter | ok | 1.1s | 24+34 | 256K | live |
| `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter | ok | 0.8s | 24+39 | 262K | live |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter | ok | 0.8s | 24+17 | 1000K | live |
| `nvidia/nemotron-3.5-lightning:free` | OpenRouter | ok | 1.3s | 24+256 | 1000K | live |
| `openrouter/free` | OpenRouter | ok | 0.9s | 24+43 | 200K | marked |
| `poolside/laguna-s-2.1:free` | OpenRouter | ok | 2.6s | 53+2 | 262K | live |
| `poolside/laguna-xs-2.1:free` | OpenRouter | slow | 6.1s | 53+215 | 262K | live |
| `qwen/qwen3.8-27b:free` | OpenRouter | ok | 0.5s | 58+30 | 262K | live |
| `thinkingmachines/inkling-small:free` | OpenRouter | blocked | 0.2s | 0+0 | 1048K | live |
| `thinkingmachines/inkling:free` | OpenRouter | blocked | 0.1s | 0+0 | 1048K | live |
| `glm-4.5-flash` | Z.ai / GLM | slow | 5.8s | 12+156 | — | static |
| `glm-4.6v-flash` | Z.ai / GLM | limited | 0.5s | 0+0 | — | static |
| `glm-4.7-flash` | Z.ai / GLM | ok | 3.3s | 12+163 | — | static |
| `space-bunny-free` | OpenCode Zen | ok | 1.2s | 164+17 | — | static |

## Как использовать

```bash
# обновить каталог и статусы
python tools/cli.py ping --write

# конфиги для других инструментов
python tools/cli.py export opencode --verified-only > opencode.jsonc
python tools/cli.py export codex --verified-only
python tools/cli.py export zed --verified-only
python tools/cli.py export cline --verified-only

# спросить модель
python tools/cli.py ask "напиши тест на pytest" --gateway groq
python tools/cli.py swarm "сравни подходы" --gateway openrouter --limit 5
```

Ключи в экспортируемые конфиги не попадают — вместо них имена переменных окружения.

## Что означают статусы

| Статус | Значение |
|---|---|
| `ok` | отвечает |
| `slow` | отвечает медленно |
| `empty` | пустой ответ (reasoning съел max_tokens) |
| `limited` | лимит запросов исчерпан, повторить позже |
| `blocked` | доступ закрыт провайдером, не использовать |
| `down` | недоступна |
| `skipped` | не проверялась |
