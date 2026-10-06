# Отчёт об аудите кода проекта zagent

**Дата:** 2024
**Цель:** Поиск багов и потенциальных проблем в коде

## Критические баги

### 1. ⚠️ Race condition при ленивой инициализации httpx.AsyncClient
**Файл:** `providers/zen.py:46-52`

```python
@property
def client(self) -> httpx.AsyncClient:
    """Лениво создаём общий AsyncClient, чтобы переиспользовать соединения."""
    if self._client is None:
        self._client = httpx.AsyncClient(timeout=self.timeout)
        self._owns_client = True
    return self._client
```

**Проблема:** При параллельных вызовах метода `chat()` возможна ситуация, когда несколько корутин одновременно проверят `self._client is None` и создадут несколько экземпляров клиента. Это приведёт к утечке ресурсов и некорректному закрытию клиентов.

**Решение:** Использовать `asyncio.Lock` для синхронизации создания клиента:
```python
def __init__(...):
    ...
    self._client_lock = asyncio.Lock()

async def _get_client(self) -> httpx.AsyncClient:
    if self._client is None:
        async with self._client_lock:
            if self._client is None:  # double-check
                self._client = httpx.AsyncClient(timeout=self.timeout)
                self._owns_client = True
    return self._client
```

### 2. 🐛 Потенциальная утечка памяти в error handling
**Файл:** `providers/zen.py:103-104`

```python
except Exception as exc:  # защитная сетка: наружу не выпускаем ничего
    return error_result(f"Сеть недоступна: {exc}", duration_ms=_ms(started))
```

**Проблема:** Захват всех исключений и преобразование их в строку может привести к утечке чувствительной информации и затруднить отладку. Кроме того, некоторые исключения (например, `KeyboardInterrupt`, `SystemExit`) не должны перехватываться.

**Решение:** Перехватывать только ожидаемые исключения:
```python
except (httpx.HTTPError, OSError) as exc:
    return error_result(f"Сеть недоступна: {type(exc).__name__}", duration_ms=_ms(started))
```

### 3. 🔥 Отсутствие валидации model_ids в Router
**Файл:** `hub/router.py:70-71`

```python
for index, model_id in enumerate(chain):
    result = await provider.chat(model_id, messages, **kw)
```

**Проблема:** Не проверяется, существуют ли модели из цепочки в списке доступных моделей. Если в `agents.json` указана несуществующая модель, ошибка будет обнаружена только при вызове API.

**Решение:** Добавить валидацию в конструктор:
```python
def __init__(self, agents: dict[str, list[str]], models: Sequence[dict[str, str]] | None = None):
    self.agents = {str(role): list(chain) for role, chain in agents.items()}
    self.models = list(models or [])
    
    # Валидация: все модели в цепочках должны существовать
    known_ids = {m["id"] for m in self.models}
    for role, chain in self.agents.items():
        for model_id in chain:
            if known_ids and model_id not in known_ids:
                raise RouterError(f"Роль '{role}' ссылается на неизвестную модель '{model_id}'")
```

## Средние баги

### 4. ⚠️ Некорректная обработка пустого списка в health.py
**Файл:** `hub/health.py:112`

```python
width = max(len(report.model_id) for report in reports) + 2
```

**Проблема:** Если `reports` пустой, `max()` вызовет `ValueError`. Хотя есть проверка на строке 110, это защитное программирование.

**Решение:** Уже есть проверка на строке 110-111, но можно сделать безопаснее:
```python
width = max((len(report.model_id) for report in reports), default=10) + 2
```

### 5. 🐛 Неконсистентность в обработке ошибок записи в log
**Файл:** `hub/bus.py:76-87`

```python
def log_usage(record: dict[str, Any], root: str | Path | None = None) -> None:
    ...
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"Предупреждение: не удалось записать {path}: {exc}", file=sys.stderr)
```

**Проблема:** Перехватывается только `OSError`, но `json.dumps()` может вызвать `TypeError` или `ValueError` при невалидных данных. Ошибка будет не поймана и сломает весь поток.

**Решение:**
```python
try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
except (OSError, TypeError, ValueError) as exc:
    print(f"Предупреждение: не удалось записать {path}: {exc}", file=sys.stderr)
```

### 6. 🔍 Отсутствие проверки на отрицательные значения
**Файл:** `providers/zen.py:40`

```python
self.timeout = float(timeout)
```

**Проблема:** Не проверяется, что `timeout` положительный. Отрицательный таймаут может привести к неожиданному поведению.

**Решение:**
```python
if timeout <= 0:
    raise ValueError(f"timeout должен быть положительным, получено: {timeout}")
self.timeout = float(timeout)
```

### 7. ⚠️ Потенциальный ZeroDivisionError
**Файл:** `hub/health.py:45`

```python
@property
def seconds(self) -> float:
    return self.duration_ms / 1000.0
```

**Проблема:** Хотя `duration_ms` обычно положительный, это свойство не защищено от деления на ноль в экстремальных случаях (что маловероятно, но возможно).

**Статус:** Низкий приоритет, но стоит добавить проверку или документацию.

## Логические ошибки

### 8. 🔧 Некорректная логика в _extract_text
**Файл:** `providers/zen.py:154-169`

```python
def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for chunk in content:
            if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                parts.append(chunk["text"])
        return "".join(parts)
    return ""
```

**Проблема:** Если `message` равен `None` (а не пустой словарь), то `message.get("content")` вызовет `AttributeError`.

**Исправление уже присутствует:** Используется `or {}`, что корректно. Однако стоит учесть случай, когда `choices[0]` сам равен `None`:

```python
first_choice = choices[0]
if not isinstance(first_choice, dict):
    return ""
message = first_choice.get("message") or {}
```

### 9. 🐛 Неправильная обработка пустых model_ids в config.py
**Файл:** `hub/config.py:78-84`

```python
model_id = str(item.get("id") or "").strip()
if not model_id:
    raise ConfigError(f"В {path} у models[{index}] не задан id")
if model_id in seen:
    raise ConfigError(f"В {path} модель {model_id} указана дважды")
seen.add(model_id)
```

**Проблема:** Если `item.get("id")` возвращает, например, `0` или `False`, то `or ""` превратит это в пустую строку. Хотя для ID это корректное поведение, стоит быть внимательным.

**Статус:** Не баг, но потенциальный источник путаницы. Лучше явно проверять:
```python
model_id_raw = item.get("id")
if not model_id_raw or not str(model_id_raw).strip():
    raise ConfigError(...)
model_id = str(model_id_raw).strip()
```

## Проблемы безопасности

### 10. 🔐 Логирование потенциально чувствительных данных
**Файл:** `providers/zen.py:129-130`

```python
message = _error_message(data) or _snippet(response.text)
return error_result(f"HTTP {status}: {message}", duration_ms=duration_ms, status=status, raw=data)
```

**Проблема:** Полный ответ API (`raw=data`) записывается в лог. Это может включать чувствительную информацию или внутренние детали API.

**Решение:** Добавить опцию для отключения логирования `raw` в продакшене или фильтровать чувствительные поля.

### 11. 🔒 API ключи в переменных окружения
**Файл:** `hub/config.py:159-161`

```python
from_env = str(environ.get(_env_name(name)) or "").strip()
if from_env:
    return [from_env]
```

**Комментарий:** Код корректен, но стоит документировать, что API ключи не должны попадать в логи или error messages.

## Проблемы производительности

### 12. ⚡ Линейный поиск в Router.label()
**Файл:** `hub/router.py:44-49`

```python
def label(self, model_id: str) -> str:
    for item in self.models:
        if item.get("id") == model_id:
            return item.get("label") or model_id
    return model_id
```

**Проблема:** O(n) поиск при каждом вызове. Для большого количества моделей это может быть узким местом.

**Решение:** Создать словарь в конструкторе:
```python
def __init__(self, agents, models):
    ...
    self._model_labels = {m["id"]: m.get("label") or m["id"] for m in self.models}

def label(self, model_id: str) -> str:
    return self._model_labels.get(model_id, model_id)
```

### 13. ⚡ Неэффективная работа с _keys_from_value
**Файл:** `hub/config.py:165-191`

```python
keys: list[str] = []
seen: set[str] = set()
for item in raw:
    text = str(item or "").strip()
    if not text or text in seen:
        continue
    seen.add(text)
    keys.append(text)
return keys
```

**Комментарий:** Код оптимален, но можно упростить:
```python
return list(dict.fromkeys(text for item in raw if (text := str(item or "").strip())))
```

## Потенциальные проблемы

### 14. 📝 Неконсистентная обработка None в базовых функциях
**Файлы:** `providers/base.py:29-59` и `providers/base.py:62-87`

```python
def ok_result(...):
    return {
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        ...
    }
```

**Проблема:** `int(None or 0)` работает корректно, но `int("abc" or 0)` вызовет `ValueError`. Стоит добавить явную валидацию или обработку исключений.

### 15. 🔍 Отсутствие проверки типов в gather_chats
**Файл:** `hub/bus.py:38-46`

```python
raw = await asyncio.gather(*tasks, return_exceptions=True)

results: list[dict[str, Any]] = []
for model_id, item in zip(model_ids, raw):
    if isinstance(item, BaseException):
        results.append(error_result(f"Внутренняя ошибка: {item}"))
    else:
        results.append(item)
return results
```

**Проблема:** Предполагается, что `item` это словарь, но не проверяется. Если `provider.chat()` возвращает что-то другое (из-за бага), это сломает последующий код.

**Решение:**
```python
for model_id, item in zip(model_ids, raw):
    if isinstance(item, BaseException):
        results.append(error_result(f"Внутренняя ошибка: {item}"))
    elif not isinstance(item, dict):
        results.append(error_result(f"Некорректный результат от провайдера: {type(item)}"))
    else:
        results.append(item)
```

## Проблемы с тестами

### 16. 🧪 Недостаточное покрытие edge cases
**Файл:** `tests/test_router.py`

**Отсутствующие тесты:**
- Пустая цепочка моделей
- Все модели в цепочке вернули одновременно пустые ответы
- Таймаут при всех моделях
- Некорректный формат ответа от провайдера
- Concurrent вызовы Router.ask() с одним провайдером

## Рекомендации

### Общие улучшения:

1. **Добавить type hints везде:** Некоторые функции имеют неполные аннотации типов
2. **Использовать mypy/pyright:** Для статической проверки типов
3. **Добавить pydantic:** Для валидации конфигурационных файлов
4. **Логирование:** Использовать proper logging вместо print() для ошибок
5. **Метрики:** Добавить мониторинг для отслеживания ошибок в продакшене

### Приоритеты исправления:

**Высокий приоритет:**
- Баг #1 (race condition)
- Баг #3 (валидация model_ids)
- Баг #5 (обработка ошибок в логировании)

**Средний приоритет:**
- Баг #2 (слишком широкий except)
- Баг #10 (логирование чувствительных данных)
- Баг #12 (оптимизация производительности)

**Низкий приоритет:**
- Баги #6, #7, #14 (дополнительные валидации)
- Баг #13 (code style)

## Итоги

**Всего найдено:** 16 проблем
- Критические: 3
- Средние: 5
- Логические: 2
- Безопасность: 2
- Производительность: 2
- Потенциальные: 2

**Общая оценка кода:** Код написан качественно, с хорошей структурой и документацией. Большинство найденных проблем относятся к edge cases и не критичны для базовой функциональности. Основное внимание следует уделить race condition в провайдере и валидации данных.
