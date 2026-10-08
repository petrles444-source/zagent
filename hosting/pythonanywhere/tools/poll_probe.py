"""Подбор длительности длинного опроса Telegram на этом хостинге.

`getUpdates?timeout=N` держит соединение открытым N секунд. Прокси
PythonAnywhere длинные соединения рвёт (503), поэтому берём тот N,
который проходит, и ставим его в бота. Подбираем на месте: на другой
машине и на другом тарифе предел другой.

Запуск на сервере:  python3 poll_probe.py
"""

import json
import time
import urllib.request

TOKEN = json.load(open("config.json", encoding="utf-8"))["telegram_token"]

for wait in (0, 3, 5, 10, 15, 25):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?timeout={wait}"
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=wait + 15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        spent = time.time() - started
        print(f"timeout={wait:2}  ok, ждали {spent:4.1f} с, "
              f"обновлений {len(payload.get('result') or [])}")
    except Exception as exc:
        spent = time.time() - started
        print(f"timeout={wait:2}  СБОЙ через {spent:4.1f} с: "
              f"{type(exc).__name__}: {exc}")
