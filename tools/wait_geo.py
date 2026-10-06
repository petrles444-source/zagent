"""Дождаться конца замера и показать итог."""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8786"


def post(path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


budget = int(sys.argv[1]) if len(sys.argv) > 1 else 900
deadline = time.time() + budget
last = ""
while time.time() < deadline:
    s = post("/api/region", {"action": "status"})
    p = s.get("progress") or {}
    line = f"{p.get('done',0)}/{p.get('total',0)} {p.get('phase','')} {(p.get('current') or '')[:36]}"
    if line != last:
        print(line, flush=True)
        last = line
    if not s.get("running"):
        break
    time.sleep(4)
else:
    print("!! не дождался")

s = post("/api/region", {"action": "status"})
c = s["summary"]["counts"]
print(f"\nитог: без VPN {c['ok']} · нужен VPN {c['vpn']} · "
      f"недоступно {c['blocked']} · неизвестно {c['unknown']}")
print(f"измерено: {s['direct_measured']}")
print("пояснения (последние):")
for line in (s.get("log") or [])[-8:]:
    print("  ", line)

state = json.loads(urllib.request.urlopen(BASE + "/api/state", timeout=30).read().decode())
marked = {}
for row in state.get("candidates") or []:
    reg = (row.get("region") or {}).get("status", "unknown")
    marked[reg] = marked.get(reg, 0) + 1
print("метки в интерфейсе:", marked)
