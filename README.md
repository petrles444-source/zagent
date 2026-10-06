# WelcomeScreen Agent Config

## Файлы конфигурации

- `config/gateways.json` — шлюзы: адреса, переменные с ключами, лимиты, RPM
- `config/secrets.local.json` — **секретные ключи** (не коммитить!)
- `config/secrets.local.json.example` — пример структуры ключей
- `config/models.json` — список моделей для статического режима
- `config/models.json.example` — пример списка моделей
- `config/tiers.json` — приоритеты и возможности моделей
- `config/regions.json` — доступность шлюзов по регионам
- `config/workspaces.json` — папки агента и их настройки

Удалены 07.10.2026, потому что их не читал никто:

- `keys.json` и `routing.json` — ключи читаются из `secrets.local.json`,
  порядок моделей задаёт `tiers.json`
- `agents.json` и роутер по ролям — выбор моделей идёт через `hub/select.py`
  и `hub/failover.py`

## Провайдеры

### OpenRouter
Бесплатные модели:
- `nvidia/nemotron-3-ultra-550b-a55b:free` — 550B MoE, контекст 1M
- `nvidia/nemotron-3-super-120b-a12b:free` — 120B MoE, быстрая
- `nvidia/nemotron-3.5-lightning:free` — 1M контекста
- `qwen/qwen3.8-27b:free` — 27B
- `cohere/north-mini-code:free` — кодовая
- `poolside/laguna-s-2.1:free` — кодовая
- `dots-studio/dots-3-note-preview:free` — vision, 512K контекста
- `google/gemma-4-31b-it:free` — vision
- `google/gemma-4-26b-a4b-it:free` — MoE 26B/4B, vision
- `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` — omni, reasoning
- `inclusionai/ling-3.0-flash-sante:free` — flash
- `liquid/lfm-2.5-2.6b:free` — 2.6B
- `apodex/apodex-1.1-mini:free` — mini

### Z.ai
Бессрочно бесплатные:
- `glm-4.7-flash` — лучшее качество среди GLM Flash
- `glm-4.5-flash`
- `glm-4.6v-flash` — vision

### Cloudflare Workers AI
Бесплатный tier: 10 000 нейронов/день на все модели.
- `@cf/openai/gpt-oss-120b`
- `@cf/meta/llama-3.3-70b-instruct-fp8-fast`
- `@cf/qwen/qwen3-30b-a3b-fp8`
- `@cf/google/gemma-4-26b-a4b-it` — vision

## Использование

1. Скопируйте `config/secrets.local.json.example` → `config/secrets.local.json`
   и вставьте реальные ключи.
2. Приоритет и возможности моделей настройте в `config/tiers.json`.
3. Агент будет выбирать модели по tiers и доступности.

## Безопасность

- `config/secrets.local.json` добавлен в `.gitignore`
- Никогда не коммитьте реальные ключи
- Перед коммитом и пушем прогоняйте `tools/check_secrets.py`
- Используйте переменные окружения или секретные хранилища в продакшене
