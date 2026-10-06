"""Сквозная проверка нового интерфейса: панели, инструкции, воркспейсы, файлы."""
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8784"


def get(path: str):
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    try:
        return r.status, json.loads(body)
    except json.JSONDecodeError:
        return r.status, body


def post(path: str, payload: dict | None = None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body[:400]}


print("1. GET / — главная страница")
status, html = get("/")
print(f"   status={status} bytes={len(html)}")
markers = {
    "три панели": 'id="left"' in html and 'id="center"' in html and 'id="right"' in html,
    "разделители": html.count("grip") >= 2,
    "перетаскивание": "mousedown" in html and "col-resize" in html,
    "сохранение ширины": "zagent.layout" in html,
    "вложения": "addFiles" in html and "attach" in html,
    "скриншот": "takeShot" in html,
    "дерево файлов": "loadTree" in html,
    "просмотр файла": "openFile" in html,
    "вкладка моделей": 'id="p-models"' in html,
    "вкладка доступа": 'id="p-access"' in html,
    "вкладка очереди": 'id="p-queue"' in html,
    "выбор воркспейса": "wsSel" in html and "switchWs" in html,
    "SSE поток": "EventSource" in html,
}
for name, ok in markers.items():
    print(f"   {'OK  ' if ok else 'MISS'} {name}")

print("\n2. GET /api/state")
status, state = get("/api/state")
print(f"   status={status} шлюзов={len(state.get('gateways', []))} "
      f"моделей={len(state.get('candidates', []))}")
print(f"   воркспейсы: {[w['id'] for w in state.get('workspaces', {}).get('workspaces', [])]}")
print(f"   очередь: {state.get('task_counts')}")
print(f"   хранилище: {state.get('store', {}).get('path', '?').split(chr(92))[-1]}")

print("\n3. POST /api/connect opencode — инструкции")
status, guide = post("/api/connect", {"target": "opencode"})
print(f"   status={status} цель={guide.get('label')}")
usable = [e for e in guide.get("entries", []) if e.get("available")]
blocked = [e for e in guide.get("entries", []) if not e.get("available")]
print(f"   доступных шлюзов: {len(usable)}, заблокировано: {len(blocked)}")
for entry in usable[:3]:
    has_key = bool(entry.get("api_key"))
    print(f"   {entry['label']:<22} provider={entry['provider_id']:<12} "
          f"url={entry['base_url'][:44]:<44} ключ={'да' if has_key else 'не нужен'}")
if blocked:
    print(f"   заблокировано: {[(e['label'], e.get('reason', '')[:40]) for e in blocked]}")

print("\n4. Проверка готовых конфигов")
for entry in usable[:2]:
    block = entry["instruction"]
    has_provider = entry["provider_id"] in block
    has_url = entry["base_url"] in block
    print(f"   {entry['label']:<22} provider_id={'да' if has_provider else 'НЕТ'} "
          f"base_url={'да' if has_url else 'НЕТ'} моделей={len(entry['models'])}")

print("\n5. Инструкции для остальных инструментов")
for target in ("deepseek", "codex", "zed", "cline"):
    status, block = post("/api/connect", {"target": target})
    usable = [e for e in block.get("entries", []) if e.get("available")]
    blocked = [e for e in block.get("entries", []) if not e.get("available")]
    print(f"   {block.get('label', target):<20} доступно={len(usable)} заблокировано={len(blocked)}")

print("\n6. POST /api/files — дерево воркспейса")
status, tree = post("/api/files", {"path": "."})
if tree.get("ok") and tree.get("kind") == "dir":
    names = [e["name"] for e in tree["entries"]]
    print(f"   status={status} папка={tree['path']} файлов={len(names)}")
    print(f"   примеры: {names[:8]}")
else:
    print(f"   status={status} ошибка={tree.get('error')}")

print("\n7. Просмотр файла")
status, content = post("/api/files", {"path": "zagent.bat"})
if content.get("ok"):
    print(f"   status={status} {content['path']} строк={content['lines']} "
          f"символов={len(content['content'])}")
else:
    print(f"   status={status} ошибка={content.get('error')}")

print("\n8. Выход за пределы воркспейса запрещён")
status, escape = post("/api/files", {"path": "../../../../Windows/System32/drivers/etc/hosts"})
print(f"   status={status} отказ={not escape.get('ok')} сообщение={escape.get('error')}")

print("\n9. POST /api/workspaces list")
status, ws = post("/api/workspaces", {"action": "list"})
print(f"   status={status} активный={ws.get('active')}")
for w in ws.get("workspaces", []):
    print(f"   {w['id']:<14} доступ={w['access']} автономия={w['autonomy']:<7} "
          f"существует={w['exists']} путь={w['path']}")

print("\n10. POST /api/workspaces add — временная папка")
# Папку создаём внутри проекта: системный Temp может быть недоступен для записи.
tmp = "C:/Users/HP/PycharmProjects/WelcomeScreen/zagent/screenshots/ws-test"
import os
os.makedirs(tmp, exist_ok=True)
status, added = post("/api/workspaces", {"action": "add", "path": tmp, "name": "test"})
if added.get("ok"):
    new_id = [w["id"] for w in added["workspaces"] if "test" in w["id"]][0]
    print(f"   status={status} добавлен: {new_id}")
else:
    print(f"   status={status} ошибка={added.get('error')}")
    new_id = None

print("\n11. Переключение на воркспейс")
if new_id:
    status, switched = post("/api/workspaces", {"action": "activate", "id": new_id})
    print(f"   status={status} активный={switched.get('active')}")
    status, cfg_state = get("/api/state")
    print(f"   base_dir агента: {cfg_state['config']['base_dir']}")
    status, back = post("/api/workspaces", {"action": "activate", "id": "default"})
    print(f"   вернулся к: {back.get('active')}")
    status, removed = post("/api/workspaces", {"action": "remove", "id": new_id})
    print(f"   удалён: {status == 200}")

print("\n12. Задача в очередь с воркспейсом")
status, task = post("/api/tasks", {
    "task": "Назови три языка программирования, одним предложением.",
    "workspace_id": "default",
})
print(f"   status={status} task_id={task.get('task_id')}")

print("\n13. Ждём выполнения задачи")
for attempt in range(60):
    time.sleep(5)
    status, st = get("/api/state")
    counts = st.get("task_counts", {})
    if counts.get("queued", 0) == 0 and counts.get("running", 0) == 0:
        break
    print(f"   ... {attempt+1}: {counts}")

status, tasks = get("/api/tasks")
for t in (tasks.get("tasks") or [])[:2]:
    print(f"   задача #{t['id']} {t['status']} шагов={t['steps']} "
          f"модели={t.get('models')}")
    if t.get("status") == "done" and t.get("result"):
        try:
            result = json.loads(t["result"])
            print(f"   итог: {str(result.get('last'))[:150]}")
            print(f"   проверок: {len(result.get('verifications') or [])} "
                  f"токенов: {result.get('tokens')}")
        except json.JSONDecodeError:
            pass

print("\n14. SSE-поток событий")
try:
    req = urllib.request.Request(BASE + "/api/events?since=0")
    with urllib.request.urlopen(req, timeout=20) as r:
        chunk = r.read(400).decode("utf-8", "replace")
    has_data = "data: " in chunk
    print(f"   status={r.status} события идут={has_data}")
    if has_data:
        first = [l for l in chunk.splitlines() if l.startswith("data: ")][0][6:]
        ev = json.loads(first)
        print(f"   первое событие: тип={ev.get('type')} id={ev.get('id')}")
except Exception as exc:
    print(f"   исключение: {type(exc).__name__}: {exc}")

print("\n15. Балансировка панелей в разметке")
status, html = get("/")
print(f"   есть CSS-переменная ширины: {'--lw' in html and '--rw' in html}")
print(f"   панели подписаны: {'#left' in html}, {'#right' in html}")

print("\nГотово.")
