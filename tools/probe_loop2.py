"""Проверить, отвечает ли loop воркера на живом сервере."""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8786"


def post(path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


print("1. Синхронный вызов в loop: /api/pause (resume=true)")
print("  ", post("/api/pause", {"resume": True}))

print("\n2. Синхронный вызов в loop: /api/scan")
try:
    r = post("/api/scan", {})
    print("  ", {k: v for k, v in r.items() if k != 'results'})
except Exception as exc:
    print("   ОШИБКА:", type(exc).__name__, exc)

print("\n3. Состояние замера")
s = post("/api/region", {"action": "status"})
print("   running:", s["running"], "progress:", s["progress"])

print("\n4. Если замер висит — отменяем повторным стартом")
r = post("/api/region", {"action": "measure", "mode": "direct"})
print("  ", r)
