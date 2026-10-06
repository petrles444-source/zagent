"""Проверка скриншота и vision-запроса через веб-API.

Создаёт тестовую картинку (если снимок экрана недоступен) и спрашивает
vision-модель через /api/ask с images=[data_url].
"""
import base64
import io
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8781"


def post(path, payload=None):
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


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=300) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body[:400]}


print("1. GET /api/shot — снимок экрана")
status, shot = get("/api/shot")
if shot.get("ok"):
    print(f"   status={status} {shot['width']}x{shot['height']} "
          f"data_url={len(shot['data_url'])} симв.")
    image = shot["data_url"]
else:
    print(f"   status={status} ошибка={shot.get('error')} "
          f"нужна_помощь={shot.get('needs_user')}")
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (240, 120), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 110, 110], fill="red")
    draw.rectangle([120, 10, 230, 110], fill="blue")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    image = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    print("   подставил тестовую картинку 240x120: красный квадрат слева, синий справа")

print("\n2. POST /api/mode — включаю только vision-модели")
status, mode = post("/api/mode", {"mode": "auto", "require_vision": True})
print(f"   status={status} моделей в реестре={mode.get('stats', {}).get('total')}")

print("\n3. POST /api/ask со скриншотом")
status, answer = post("/api/ask", {
    "text": "Опиши картинку в одном предложении: что и где нарисовано?",
    "images": [image],
    "max_tokens": 300,
})
if answer.get("ok"):
    print(f"   status={status} модель={answer['model']} {answer['duration_ms']}мс "
          f"{answer['tokens_in']}+{answer['tokens_out']} токенов")
    print(f"   ответ: {answer['answer'][:400]}")
else:
    print(f"   status={status} ошибка={answer.get('error')}")
    for attempt in answer.get("attempts") or []:
        print(f"     пробована {attempt.get('ref')}: {attempt.get('error')}")

print("\n4. POST /api/mode — возвращаю auto без vision")
status, mode = post("/api/mode", {"mode": "auto", "require_vision": False})
print(f"   status={status} текущая={mode.get('stats', {}).get('current')}")
