"""Проверка, какие адреса достижимы с PythonAnywhere.

Бесплатный тариф ходит в интернет не через интернет, а через прокси с
белым списком. Из-за этого часть привычных адресов просто не отвечает,
и это выглядит как «бот молчит», хотя с ним всё в порядке.

Запуск на сервере:  python3 reach.py
"""

import json
import ssl
import urllib.error
import urllib.request

HOSTS = [
    "https://api.telegram.org/",
    "https://api.groq.com/openai/v1/models",
    "https://integrate.api.nvidia.com/v1/models",
    "https://openrouter.ai/api/v1/models",
    "https://api.mistral.ai/v1/models",
    "https://api.z.ai/api/paas/v4/models",
    "https://example.com/",
]

ctx = ssl.create_default_context()
rows = []
for url in HOSTS:
    host = url.split("/")[2]
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ada/1.0"})
        with urllib.request.urlopen(request, timeout=20, context=ctx) as resp:
            rows.append((host, str(resp.status)))
    except urllib.error.HTTPError as exc:
        # Ответ сервера — значит адрес доступен: 401 без ключа это норм.
        rows.append((host, f"доступен (HTTP {exc.code})"))
    except Exception as exc:
        rows.append((host, f"НЕДОСТУПЕН ({type(exc).__name__})"))

for host, verdict in rows:
    print(f"{host:32} {verdict}")

ok = [h for h, v in rows if not v.startswith("НЕДОСТУПЕН")]
print()
print(f"доступно {len(ok)} из {len(rows)}")
print(json.dumps({"ok": ok}, ensure_ascii=False))
