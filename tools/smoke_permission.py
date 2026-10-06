"""Сквозная проверка мягкой границы: агент просит разрешения, пользователь решает.

Запуск: сервер на 8786 уже поднят, затем `python tools\\smoke_permission.py`.
"""
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

# Ответы моделей содержат символы вроде узкого неразрывного пробела (U+202F),
# которых нет в cp1251 консоли Windows. Печатаем в UTF-8 с заменой, иначе
# проверка падает на выводе, а не на том, что проверяет.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

BASE = "http://127.0.0.1:8786"
OUTSIDE = "C:/Users/HP/PycharmProjects/WelcomeScreen/outside-probe"
WS = "default"


def say(text=""):
    print(text, flush=True)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_permission(task_id, *, budget=90):
    """Ждать запрос разрешения именно по нашей задаче.

    Чужие незакрытые запросы (от прошлых прогонов) игнорируем: иначе ответ
    уйдёт не туда и проверка будет висеть вечно.
    """
    deadline = time.time() + budget
    while time.time() < deadline:
        for item in get("/api/permissions").get("permissions", []):
            if item.get("task_id") == task_id:
                return item
        time.sleep(2)
    return None


def wait_status(task_id, statuses, *, budget=180):
    """Ждать, пока задача придёт в один из терминальных статусов."""
    deadline = time.time() + budget
    last = None
    while time.time() < deadline:
        tasks = get("/api/tasks?limit=40").get("tasks", [])
        task = next((t for t in tasks if t["id"] == task_id), None)
        if task:
            last = task["status"]
            if last in statuses:
                return task
        time.sleep(2)
    return {"id": task_id, "status": last or "?"}


def start(task_text):
    status, body = post("/api/tasks", {"task": task_text, "workspace_id": WS})
    say(f"   task_id={body.get('task_id')} (http {status})")
    return body["task_id"]


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        return f"<не читается: {exc}>"


def outcome(task_id):
    tasks = get("/api/tasks?limit=40").get("tasks", [])
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task or not task.get("result"):
        return "", None
    try:
        result = json.loads(task["result"])
    except json.JSONDecodeError:
        return "", None
    return str(result.get("last") or ""), result.get("models_used")


shutil.rmtree(OUTSIDE, ignore_errors=True)
os.makedirs(OUTSIDE, exist_ok=True)

def wait_server(*, budget=60):
    """Дождаться, пока сервер поднимется.

    Без этого гонка: скрипт стартует раньше, чем порт занят, и падает
    с ConnectionRefused вместо внятного сообщения.
    """
    deadline = time.time() + budget
    while time.time() < deadline:
        try:
            return get("/api/state")
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise SystemExit(f"Сервер {BASE} не отвечает за {budget} с — он запущен?")


say("1. Состояние")
state = wait_server()
# Обычный режим явно: иначе проверка зависит от того, что осталось от
# прошлого прогона, и при полном доступе агент выйдет наружу без вопроса.
post("/api/config", {"access": 2})
state = get("/api/state")
say(f"   soft_boundary={state.get('soft_boundary')}")
say(f"   доступ: {state['config']['access']} (2 = обычный, 3 = полный)")
say(f"   воркспейс: {state['workspaces']['active']} -> "
    f"{state['workspaces']['workspaces'][0]['path']}")
say(f"   незакрытых запросов на старте: {len(get('/api/permissions')['permissions'])}")

# ---------------------------------------------------------------- разрешить
say("\n2. Задача: изменить файл ВНЕ воркспейса (ответ «только сейчас»)")
target = f"{OUTSIDE}/probe.txt"
with open(target, "w", encoding="utf-8") as f:
    f.write("старое содержимое")
say(f"   файл: {target}")

task_id = start(
    f"Измени файл {target}: замени слово 'старое' на слово 'новое'. "
    "Используй edit_file.")

permission = wait_permission(task_id)
if not permission:
    say("   ЗАПРОС НЕ ПОЯВИЛСЯ")
    last, models = outcome(task_id)
    say(f"   статус задачи: {wait_status(task_id, {'done', 'failed'})['status']}")
    say(f"   модели: {models}")
    say(f"   итог: {last[:400]}")
    raise SystemExit(1)

say(f"   запрос #{permission['id']}: {permission['operation']} -> {permission['path']}")
tasks = get("/api/tasks?limit=40").get("tasks", [])
mine = next(t for t in tasks if t["id"] == task_id)
say(f"   задача в статусе: {mine['status']}")
say(f"   файл ещё не тронут: {read(target)[:40]!r}")

say("\n3. Отвечаем: ТОЛЬКО СЕЙЧАС")
status, answered = post("/api/permissions", {
    "action": "answer", "permission_id": permission["id"],
    "allow": True, "scope": "once"})
say(f"   http={status} решение={answered.get('permission', {}).get('status')} "
    f"scope={answered.get('permission', {}).get('scope')}")

final = wait_status(task_id, {"done", "failed", "cancelled"})
say(f"   итоговый статус: {final['status']} шагов={final.get('steps')}")
content = read(target)
say(f"   файл теперь: {content[:60]!r}")
say(f"   ИЗМЕНЁН: {'новое' in content and 'старое' not in content}")
last, models = outcome(task_id)
say(f"   модели: {models}")
say(f"   итог агента: {last[:250]}")

say("\n4. «Только сейчас» не действует на другие задачи")
tasks = get("/api/tasks?limit=40").get("tasks", [])
mine = next(t for t in tasks if t["id"] == task_id)
say(f"   payload без grant_path: {'grant_path' not in (mine.get('payload') or {})}")

# ------------------------------------------------------------------ отклонить
say("\n5. Задача с отказом: агент должен получить «нет» и не тронуть файл")
target2 = f"{OUTSIDE}/denied.txt"
with open(target2, "w", encoding="utf-8") as f:
    f.write("оставь как есть")

task2 = start(
    f"Измени файл {target2}: замени 'оставь' на 'убрал'. Используй edit_file.")

permission2 = wait_permission(task2)
if not permission2:
    say("   ЗАПРОС НЕ ПОЯВИЛСЯ")
    last, models = outcome(task2)
    say(f"   итог: {last[:300]}")
    raise SystemExit(1)

say(f"   запрос #{permission2['id']} -> {permission2['path']}")
post("/api/permissions", {
    "action": "answer", "permission_id": permission2["id"], "allow": False})
say("   отклонено")

denied = wait_status(task2, {"done", "failed", "cancelled"})
say(f"   статус: {denied['status']} шагов={denied.get('steps')}")
say(f"   файл не тронут: {read(target2)[:60]!r}")
last, models = outcome(task2)
say(f"   модели: {models}")
say(f"   итог агента: {last[:300]}")

# -------------------------------------------------------------------- журнал
say("\n6. События журнала")
# /api/events — вечный SSE-поток: keepalive-комментарий приходит каждые 15 с,
# то есть чаще таймаута сокета, и обычный read() не вернётся никогда.
# Поэтому читаем построчно и обрываем на первом же комментарии: накопленный
# журнал сервер отдаёт сразу, до keepalive.
events = []
with urllib.request.urlopen(BASE + "/api/events?since=0", timeout=20) as r:
    for raw in r:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            continue
        if line.startswith(":"):
            # Сервер сначала шлёт ": stream open", потом backlog, и только
            # потом keepalive. Обрываем на keepalive — он идёт после данных.
            if "keepalive" in line:
                break
            continue
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
        if len(events) >= 500:
            break
perm_events = [e for e in events if "permission" in str(e.get("type"))]
say(f"   событий: {len(events)}, о разрешениях: {len(perm_events)}")
for e in perm_events:
    say(f"   {e.get('type')}: allow={e.get('allow')} "
        f"scope={e.get('scope')} path={str(e.get('path'))[-40:]}")

say("\n7. Осталось незакрытых запросов: "
    f"{len(get('/api/permissions')['permissions'])}")

# ------------------------------------------------- полный доступ без вопросов
say("\n8. Полный доступ: агент выходит наружу сам, без окна")
post("/api/config", {"access": 3})
state = get("/api/state")
say(f"   access={state['config']['access']} (3 = полный), soft={state['soft_boundary']}")

target3 = f"{OUTSIDE}/full.txt"
os.makedirs(OUTSIDE, exist_ok=True)
with open(target3, "w", encoding="utf-8") as f:
    f.write("полный")

task3 = start(
    f"Измени файл {target3}: замени слово 'полный' на слово 'свободный'. "
    "Используй edit_file.")

final3 = wait_status(task3, {"done", "failed", "cancelled"}, budget=200)
say(f"   статус: {final3['status']} шагов={final3.get('steps')}")
content3 = read(target3)
say(f"   файл: {content3[:60]!r}")
say(f"   ИЗМЕНЁН БЕЗ ВОПРОСА: {'свободный' in content3}")
say(f"   лишних запросов не появилось: "
    f"{len(get('/api/permissions')['permissions']) == 0}")
last3, models3 = outcome(task3)
say(f"   модели: {models3}")
say(f"   итог: {last3[:200]}")

post("/api/config", {"access": 2})
say("   вернул обычный режим (access=2)")

shutil.rmtree(OUTSIDE, ignore_errors=True)
say("\nГотово.")
