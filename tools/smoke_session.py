"""Сквозная проверка сессий: новая сессия в том же воркспейсе и переключение."""
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


def wait_server(budget=60):
    deadline = time.time() + budget
    while time.time() < deadline:
        try:
            return get("/api/state")
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise SystemExit("сервер не поднялся")


state = wait_server()
print("1. Стартовое состояние")
print(f"   воркспейс: {state['workspaces']['active']}")
print(f"   сессия: {state.get('session')}")
print(f"   сессий: {len(state.get('sessions') or [])}")

print("\n2. Новая сессия в том же воркспейсе")
before = state["workspaces"]["active"]
first = state.get("session")
new = post("/api/sessions", {"action": "new", "name": "Проверка"})
print(f"   http-ok={new.get('ok')} id={new.get('session_id')}")
state = get("/api/state")
same_folder = state["workspaces"]["active"] == before
print(f"   воркспейс не сменился: {same_folder} ({state['workspaces']['active']})")
print(f"   активная сессия: {state['session']} (была {first})")
print(f"   сессий теперь: {len(state['sessions'])}")
names = [s["name"] for s in state["sessions"]]
print(f"   названия: {names}")
assert new["ok"] and same_folder and state["session"] == new["session_id"]

print("\n3. История новой сессии пуста")
history = post("/api/sessions", {"action": "history"})
print(f"   задач: {len(history['tasks'])}, событий: {len(history['events'])}")

print("\n4. Сессия без имени получает имя по времени")
auto = post("/api/sessions", {"action": "new", "name": ""})
state = get("/api/state")
current = [s for s in state["sessions"] if s["id"] == state["session"]][0]
print(f"   имя: {current['name']!r} (id={current['id']!r})")
print(f"   без пробелов в id: {' ' not in current['id']}")
assert current["name"], "сессия обязана иметь название"

print("\n5. Удаление сессии возвращает предыдущую")
target = auto["session_id"]
dropped = post("/api/sessions", {"action": "remove", "session_id": target})
print(f"   ok={dropped.get('ok')} активная={dropped.get('active')}")
state = get("/api/state")
print(f"   активная теперь: {state['session']}")
assert dropped["ok"] and state["session"] != target

print("\n6. Последнюю сессию воркспейса удалить нельзя")
# Сводим воркспейс к одной сессии, иначе проверка зависит от leftovers.
while len(get("/api/state")["sessions"]) > 1:
    spare = get("/api/state")["sessions"][-1]["id"]
    if get("/api/state")["session"] == spare:
        post("/api/sessions", {"action": "switch", "session_id":
                               get("/api/state")["sessions"][0]["id"]})
    gone = post("/api/sessions", {"action": "remove", "session_id": spare})
    if not gone.get("ok"):
        break
only_left = post("/api/sessions", {"action": "remove",
                                   "session_id": get("/api/state")["session"]})
print(f"   сессий осталось: {len(get('/api/state')['sessions'])}")
print(f"   ok={only_left.get('ok')} ({only_left.get('error')})")
assert not only_left.get("ok"), "последнюю сессию удалять нельзя"

print("\n7. Переключение на другую сессию")
state = get("/api/state")
keep = state["session"]
second = post("/api/sessions", {"action": "new", "name": "Вторая"})
back = post("/api/sessions", {"action": "switch", "session_id": keep})
print(f"   переключились на {back.get('session_id')}: ok={back.get('ok')}")
state = get("/api/state")
print(f"   активная: {state['session']}")
assert back.get("ok") and state["session"] == keep

print("\n8. Переключение на несуществующую сессию")
bad = post("/api/sessions", {"action": "switch", "session_id": "нет-такой"})
print(f"   ok={bad.get('ok')} ошибка={bad.get('error')}")
assert not bad.get("ok")

print("\n9. Переименование")
renamed = post("/api/sessions", {
    "action": "rename", "session_id": state["session"], "name": "Переименованная"})
print(f"   ok={renamed.get('ok')} имя={renamed.get('session', {}).get('name')}")

print("\n10. Сессия в состоянии сервера")
state = get("/api/state")
print(f"   session={state['session']}")
for s in state["sessions"]:
    print(f"   - {s['id']}: {s['name']!r} задач={s['task_count']}")

print("\nГотово.")
