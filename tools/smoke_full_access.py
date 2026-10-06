"""Полный доступ: агент должен выйти наружу без единого вопроса."""
import json
import os
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

BASE = "http://127.0.0.1:8786"
OUTSIDE = "C:/Users/HP/PycharmProjects/WelcomeScreen/outside-probe"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


os.makedirs(OUTSIDE, exist_ok=True)
target = f"{OUTSIDE}/full.txt"
with open(target, "w", encoding="utf-8") as f:
    f.write("полный")

post("/api/config", {"access": 3})
state = get("/api/state")
ws = state["workspaces"]["workspaces"][0]
print(f"access в интерфейсе: {state['config']['access']}, "
      f"в воркспейсе: {ws['access']}, soft={state['soft_boundary']}")

body = post("/api/tasks", {
    "task": f"Измени файл {target}: замени слово 'полный' на слово 'свободный'. "
            "Используй edit_file.",
    "workspace_id": "default",
})
task_id = body["task_id"]
print("task_id:", task_id)

for _ in range(90):
    time.sleep(2)
    task = next((t for t in get("/api/tasks?limit=40")["tasks"] if t["id"] == task_id), None)
    if task and task["status"] in ("done", "failed", "cancelled"):
        break
    if task and task["status"] == "waiting_permission":
        print("!! агент запросил разрешение при полном доступе")
        break

print("статус:", task["status"] if task else "?")
with open(target, encoding="utf-8") as f:
    content = f.read()
print("файл:", repr(content[:60]))
print("ИЗМЕНЁН БЕЗ ВОПРОСА:", "свободный" in content)
print("незакрытых запросов:", len(get("/api/permissions")["permissions"]))
if task and task.get("result"):
    print("итог:", str(json.loads(task["result"]).get("last"))[:250])
