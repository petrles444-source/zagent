"""Проверка веб-интерфейса: главная страница и все эндпоинты."""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8781"


def get(path: str):
    """GET, возвращающий распарсенный JSON (или текст для /)."""
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        body = r.read().decode("utf-8")
    try:
        return r.status, json.loads(body)
    except json.JSONDecodeError:
        return r.status, body


def post(path: str, payload: dict | None = None):
    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"raw": body[:400]}
        print(f"   !! {path} вернул {exc.code}")
        for line in str(parsed.get("trace") or body)[:1500].splitlines():
            print(f"      {line}")
        return exc.code, parsed


print("1. GET /")
status, html = get("/")
print(f"   status={status} bytes={len(html)}")
for marker in ("zagent", "Статус моделей", "Агент", "Скриншот",
               "pingAll", "sanityAll", "askVision", "agentRun"):
    print(f"   {'OK ' if marker in html else 'MISS'} {marker}")

print("2. GET /api/state")
status, state = get("/api/state")
print(f"   status={status} шлюзов={len(state['gateways'])} моделей={len(state['candidates'])}")
print(f"   stats={state['stats']}")

print("3. POST /api/ping (одна модель)")
status, ping = post("/api/ping", {"ref": "groq/openai/gpt-oss-120b"})
print(f"   status={status} pinged={ping.get('pinged')}")
for ref, res in (ping.get("results") or {}).items():
    print(f"   {ref}: {res['status']} {res.get('duration_ms')}мс")

print("4. POST /api/sanity (одна модель)")
status, sanity = post("/api/sanity", {"ref": "groq/openai/gpt-oss-120b", "lang": "ru"})
print(f"   status={status} checked={sanity.get('checked')} good={sanity.get('good')}")
for ref, rep in (sanity.get("reports") or {}).items():
    print(f"   {ref}: {rep['verdict']} score={rep['score']}")
    for chk in rep["checks"]:
        print(f"      {'OK ' if chk['passed'] else 'NO '} {chk['name']}: {chk['detail']}")

print("5. POST /api/mode (manual)")
status, mode = post("/api/mode", {"mode": "manual", "manual_ref": "groq/openai/gpt-oss-120b"})
print(f"   status={status} {mode.get('stats')}")

print("6. POST /api/ask (failover)")
status, answer = post("/api/ask", {"text": "Ответь одним словом: да или нет. Работает?"})
print(f"   status={status} model={answer.get('model')} {answer.get('duration_ms')}мс")
print(f"   ответ: {str(answer.get('answer'))[:100]}")
print(f"   попыток: {len(answer.get('attempts') or [])}")

print("7. POST /api/mode (auto)")
status, mode = post("/api/mode", {"mode": "auto"})
print(f"   status={status} {mode.get('stats')}")

print("8. POST /api/agent/config")
status, cfg = post("/api/agent/config", {"access": 2, "autonomy": "normal",
                                         "escalation": "auto"})
print(f"   status={status} {cfg.get('config')}")

print("9. POST /api/agent/task + step")
status, task = post("/api/agent/task", {"task": "Создай файл tests/test_web.py "
                                                 "с тестом test_web: assert True"})
print(f"   task status={status} {task}")
status, step = post("/api/agent/step", {})
print(f"   step status={status} фаза={step.get('phase')} шагов={len(step.get('steps') or [])}")
for s in (step.get("steps") or [])[:4]:
    print(f"   [{'ok' if s['ok'] else '!!'}] {s['phase']}: {s['text'][:90]}")

print("10. POST /api/agent/run (до конца)")
status, run = post("/api/agent/run", {"max_steps": 6})
print(f"   status={status} фаза={run.get('phase')} finished-шагов={len(run.get('steps') or [])}")
res = run.get("result") or {}
print(f"   result ok={res.get('ok')} шагов={res.get('steps')} модели={res.get('models_used')}")

print("11. GET /api/agent/state")
status, agent_state = get("/api/agent/state")
print(f"   status={status} phase={agent_state.get('phase')}")

print("12. POST /api/agent/run — удаление файла (полный доступ)")
post("/api/agent/config", {"access": 3, "autonomy": "yolo"})
post("/api/agent/task", {"task": "Удали файл tests/test_web.py"})
status, run2 = post("/api/agent/run", {"max_steps": 6})
for s in (run2.get("steps") or []):
    print(f"   [{'ok' if s['ok'] else '!!'}] {s['phase']}: {s['text'][:80]}")

print("13. GET /api/shot")
try:
    status, shot = get("/api/shot")
    if shot.get("ok"):
        print(f"   status={status} {shot['width']}x{shot['height']} "
              f"data_url={len(shot['data_url'])} символов")
    else:
        print(f"   status={status} ошибка={shot.get('error')} "
              f"нужна_помощь={shot.get('needs_user')}")
except Exception as exc:
    print(f"   исключение: {exc}")

print("14. 404")
try:
    get("/api/nope")
except urllib.error.HTTPError as exc:
    print(f"   status={exc.code}")

print("\nВсе проверки выполнены.")
