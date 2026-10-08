# Бесплатные модели через API — живой каталог

Обновлено: **2026-10-08T03:14:53Z**. Чат-моделей: **58**, пригодных: **41**.

Статусы: `blocked` — 2, `down` — 1, `empty` — 1, `limited` — 6, `ok` — 27, `skipped` — 14, `slow` — 7.

> opencode: None

## Шлюзы

| Шлюз | Base URL | Ключ | /responses | Моделей | Пригодных |
|---|---|---|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | есть | да | 16 | 14 |
| Groq | `https://api.groq.com/openai/v1` | есть | да | 3 | 3 |
| Z.ai / GLM | `https://api.z.ai/api/paas/v4` | есть | да | 3 | 3 |
| Mistral La Plateforme | `https://api.mistral.ai/v1` | есть | да | 3 | 3 |
| Cloudflare Workers AI | `https://api.cloudflare.com/client/v4/accounts/{cloudflare_account_id}/ai/v1` | есть | нет | 8 | 8 |
| llm7.io (keyless) | `https://api.llm7.io/v1` | не нужен | нет | 4 | 4 |
| OpenCode Zen | `https://opencode.ai/zen/v1` | не нужен | нет | 0 | 0 |
| Ollama (локально) | `http://localhost:11434/v1` | не нужен | да | 0 | 0 |
| OpenCode Zen (донор) | `http://127.0.0.1:8784/v1` | не нужен | нет | 14 | 0 |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | есть | да | 6 | 5 |
| Google AI Studio (Gemini) | `https://generativelanguage.googleapis.com/v1beta/openai` | есть | нет | 1 | 1 |

Ключи берутся из `config/secrets.local.json` или переменных окружения (имя = `ZAGENT_<ID>_API_KEY`). В репозиторий ключи не попадают.

## Модели

| Модель | Шлюз | Статус | Время | Токены | Контекст | Источник |
|---|---|---|---|---|---|---|
| `@cf/google/gemma-4-26b-a4b-it` | Cloudflare Workers AI | ok | 1.3s | 24+137 | — | static |
| `@cf/ibm-granite/granite-4.0-h-micro` | Cloudflare Workers AI | ok | 0.6s | 40+2 | — | static |
| `@cf/meta/llama-3.1-8b-instruct-fp8-fast` | Cloudflare Workers AI | ok | 0.8s | 43+4 | — | static |
| `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Cloudflare Workers AI | ok | 0.8s | 43+4 | — | static |
| `@cf/mistralai/mistral-small-3.1-24b-instruct` | Cloudflare Workers AI | slow | 6.5s | 11+2 | — | static |
| `@cf/openai/gpt-oss-120b` | Cloudflare Workers AI | ok | 1.7s | 74+45 | — | static |
| `@cf/openai/gpt-oss-20b` | Cloudflare Workers AI | ok | 0.6s | 76+40 | — | static |
| `@cf/qwen/qwen3-30b-a3b-fp8` | Cloudflare Workers AI | ok | 2.4s | 16+256 | — | static |
| `gemini-3.8-flash` | Google AI Studio (Gemini) | slow | 5.2s | 9+1 | — | static |
| `openai/gpt-oss-120b` | Groq | ok | 0.7s | 78+40 | — | static |
| `openai/gpt-oss-20b` | Groq | ok | 0.7s | 78+40 | — | static |
| `qwen/qwen3.8-27b` | Groq | ok | 0.2s | 18+2 | — | static |
| `DeepSeek-V4-Flash-0731` | llm7.io (keyless) | slow (повтор) | 5.2s | 90+256 | — | static |
| `GLM-5.3-Flash` | llm7.io (keyless) | limited | 0.2s | 0+0 | — | static |
| `codestral-latest` | llm7.io (keyless) | ok | 0.8s | 11+2 | — | static |
| `minimax-m2.7` | llm7.io (keyless) | limited | 0.2s | 0+0 | — | static |
| `codestral-latest` | Mistral La Plateforme | ok | 0.3s | 11+2 | — | static |
| `ministral-3b-latest` | Mistral La Plateforme | ok | 0.4s | 11+8 | — | static |
| `ministral-8b-latest` | Mistral La Plateforme | ok | 0.4s | 11+6 | — | static |
| `meta/llama-3.2-11b-vision-instruct` | NVIDIA NIM | ok | 0.8s | 43+3 | — | static |
| `meta/llama-3.2-90b-vision-instruct` | NVIDIA NIM | down | 60.2s | 0+0 | — | static |
| `nvidia/nemotron-3-super-120b-a12b` | NVIDIA NIM | ok | 1.0s | 24+39 | — | static |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | NVIDIA NIM | ok | 1.7s | 24+221 | — | static |
| `openai/gpt-oss-20b` | NVIDIA NIM | ok | 3.2s | 72+40 | — | static |
| `poolside/laguna-xs-2.1` | NVIDIA NIM | slow | 8.4s | 22+2 | — | static |
| `deepseek-v4-flash-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `exo-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `fledge-alpha-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `jev-1.13-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `ling-3.0-flash-fin-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `ling-3.1-flash-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `longcat-2.5-preview-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `mimo-v2.5-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `mimo-v2.6-flash-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `muse-spark-1.2-contributor-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `muse-spark-1.3-contributor-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `nemotron-3-ultra-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `nemotron-3.5-lightning-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `space-bunny-free` | OpenCode Zen (донор) | skipped | — | — | — | static |
| `apodex/apodex-1.1-mini:free` | OpenRouter | ok | 2.0s | 16+188 | 262K | live |
| `cohere/north-mini-code:free` | OpenRouter | ok | 1.0s | 8+37 | 256K | live |
| `dots-studio/dots-3-note-preview:free` | OpenRouter | slow | 16.6s | 21+77 | 512K | live |
| `google/gemma-4-26b-a4b-it:free` | OpenRouter | limited | 0.5s | 0+0 | 262K | live |
| `google/gemma-4-31b-it:free` | OpenRouter | limited | 0.5s | 0+0 | 262K | live |
| `inclusionai/ling-3.0-flash-sante:free` | OpenRouter | ok | 1.5s | 30+30 | 262K | live |
| `liquid/lfm-2.5-2.6b:free` | OpenRouter | ok | 3.3s | 18+256 | 65K | live |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | OpenRouter | ok | 1.2s | 24+34 | 256K | live |
| `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter | ok | 0.9s | 24+43 | 262K | live |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter | empty | 0.8s | 0+0 | 1000K | live |
| `nvidia/nemotron-3.5-lightning:free` | OpenRouter | slow | 63.9s | 24+256 | 1000K | live |
| `openrouter/free` | OpenRouter | ok | 3.6s | 16+256 | 200K | marked |
| `poolside/laguna-s-2.1:free` | OpenRouter | ok | 1.0s | 53+2 | 262K | live |
| `poolside/laguna-xs-2.1:free` | OpenRouter | limited | 0.5s | 0+0 | 262K | live |
| `thinkingmachines/inkling-small:free` | OpenRouter | blocked | 0.4s | 0+0 | 1048K | live |
| `thinkingmachines/inkling:free` | OpenRouter | blocked | 0.3s | 0+0 | 1048K | live |
| `glm-4.5-flash` | Z.ai / GLM | slow | 5.2s | 12+153 | — | static |
| `glm-4.6v-flash` | Z.ai / GLM | limited | 0.6s | 0+0 | — | static |
| `glm-4.7-flash` | Z.ai / GLM | ok | 4.1s | 12+209 | — | static |

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

## Ошибки сбора

- `ollama` — ConnectError (localhost:11434)
- `zen` — нет ключа — модели шлюза не используются
