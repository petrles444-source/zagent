"""Проверить, что /api/connect отдаёт connections вместе с блоком цели."""
import json
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

BASE = "http://127.0.0.1:8786"


def post(path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


print("1. /api/connect БЕЗ цели (полный справочник)")
full = post("/api/connect", {})
print(f"   ok={full.get('ok')} connections={len(full.get('connections') or [])}")
for c in (full.get("connections") or [])[:4]:
    print(f"   - {c['gateway']}: base_url={str(c.get('base_url'))[:40]!r} "
          f"key={'есть' if c.get('api_key') else '—'}")

print("\n2. /api/connect С целью (то, что зовёт интерфейс)")
part = post("/api/connect", {"target": "opencode"})
print(f"   ok={part.get('ok')} target={part.get('target')}")
print(f"   connections присутствует: {'connections' in part} "
      f"({len(part.get('connections') or [])})")
print(f"   entries: {len(part.get('entries') or [])}")

if not part.get("connections"):
    raise SystemExit("!! connections отсутствует — блок «provider id / base URL / "
                     "api key» в интерфейсе остался бы пустым")

first = part["connections"][0]
print(f"   пример: gateway={first['gateway']} provider_id={first['provider_id']}")
print(f"   base_url заполнен: {bool(first.get('base_url'))}")

print("\n3. Неизвестная цель по-прежнему отвергается")
bad = post("/api/connect", {"target": "выдумка"})
print(f"   ok={bad.get('ok')} ошибка={bad.get('error')}")

print("\nГотово.")
