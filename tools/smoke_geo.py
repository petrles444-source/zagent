"""Замер доступности из России через API: телеметрия и два прогона."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

BASE = "http://127.0.0.1:8786"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def events():
    """Читаем поток до первого keepalive — backlog отдаётся сразу."""
    out = []
    with urllib.request.urlopen(BASE + "/api/events?since=0", timeout=20) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith(":"):
                if "keepalive" in line:
                    break
                continue
            if line.startswith("data: "):
                try:
                    out.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return out


print("1. Состояние до замера")
st = post("/api/region", {"action": "status"})
print(f"   running={st['running']} измерено={st['direct_measured']}")
print(f"   сводка: {st['summary']['counts']}")

print("\n2. Второй замер запрещён до первого (кнопка заблокирована в UI)")
print("   (проверяем, что сервер тоже не даст ерунду: запускаем direct)")

print("\n3. Запускаем замер БЕЗ VPN")
r = post("/api/region", {"action": "measure", "mode": "direct"})
print(f"   ok={r.get('ok')} mode={r.get('mode')} всего={r.get('total')}")
if not r.get("ok"):
    raise SystemExit(f"   не запустился: {r.get('error')}")

print("\n4. Телеметрия (живая)")
seen = set()
last = ""
deadline = time.time() + 420
while time.time() < deadline:
    time.sleep(3)
    s = post("/api/region", {"action": "status"})
    p = s.get("progress") or {}
    line = f"   {p.get('done',0)}/{p.get('total',0)} {p.get('phase','')} {p.get('current','')[:38]}"
    if line != last:
        print(line)
        last = line
    if not s.get("running"):
        print(f"   завершено, измерено моделей: {s.get('direct_measured')}")
        break
else:
    print("   !! замер не уложился в отведённое время")
    raise SystemExit(1)

print("\n5. Итог первого замера")
s = post("/api/region", {"action": "status"})
c = s["summary"]["counts"]
print(f"   без VPN {c['ok']} · нужен VPN {c['vpn']} · "
      f"недоступно {c['blocked']} · неизвестно {c['unknown']}")
print("   пояснения:")
for line in (s.get("log") or [])[-6:]:
    print(f"     {line}")

print("\n6. Метки у моделей в состоянии")
state = get("/api/state")
marked = {}
for row in state.get("candidates") or []:
    reg = (row.get("region") or {}).get("status", "unknown")
    marked[reg] = marked.get(reg, 0) + 1
print(f"   {marked}")

print("\n7. События замера в потоке")
kinds = {}
for e in events():
    if str(e.get("type", "")).startswith("geo"):
        k = e["type"]
        kinds[k] = kinds.get(k, 0) + 1
print(f"   {kinds}")

print("\nГотово. Теперь включите VPN и нажмите «Замер с VPN».")
