"""Проверка: какие бесплатные модели принимают изображения (vision).

Отправляем крошечную картинку 4x4 с двумя цветами и спрашиваем, какого цвета
больше пикселей. Модель без vision либо отвергнет формат, либо ответит наугад.
"""
import asyncio, base64, io, json, pathlib, sys, zlib, struct

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from hub.config import load_gateways
from hub.registry import collect
from providers.openai_compat import OpenAICompatProvider

K = json.loads(pathlib.Path("config/secrets.local.json").read_text(encoding="utf-8"))


def png(width: int, height: int, rgb_rows) -> bytes:
    """Минимальный PNG без внешних зависимостей."""
    raw = b"".join(b"\x00" + bytes(row) for row in rgb_rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# 32x32: 60% красных, 40% синих — Cloudflare требует минимум 10px по стороне.
SIZE = 32
ROWS = []
for y in range(SIZE):
    row = []
    for x in range(SIZE):
        red = (y * SIZE + x) % 5 < 3
        row += [255, 0, 0] if red else [0, 0, 255]
    ROWS.append(row)

BLUE_TOTAL = sum(1 for y in range(SIZE) for x in range(SIZE) if (y * SIZE + x) % 5 >= 3)

DATA_URL = "data:image/png;base64," + base64.b64encode(png(SIZE, SIZE, ROWS)).decode()

QUESTION = (
    "This image is a grid of red and blue pixels. "
    "About what fraction of the pixels are blue? Answer with a single number between 0 and 1."
)


async def check(client, gateway, model_id):
    body = {
        "model": model_id,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": QUESTION},
                {"type": "image_url", "image_url": {"url": DATA_URL}},
            ],
        }],
        "max_tokens": 64,
    }
    try:
        r = await client.post(f"{gateway['resolved_url']}/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {gateway['api_key']}",
                                       "Content-Type": "application/json"},
                              timeout=90.0)
    except Exception as e:
        return model_id, "err", f"{type(e).__name__}"
    if r.status_code != 200:
        return model_id, "err", f"HTTP {r.status_code}: " + " ".join(r.text.split())[:120]
    try:
        d = r.json()
    except Exception:
        return model_id, "err", "not json"
    ch = d.get("choices") or []
    msg = (ch[0].get("message") or {}) if ch else {}
    txt = str(msg.get("content") or msg.get("reasoning") or "").strip()

    # Вердикт — от ответа, а не от кода 200.
    #
    # Раньше любой ответ с кодом 200 означал «vision». Модель, которая
    # изображение проигнорировала и написала «не могу видеть картинки»,
    # попадала в список умеющих видеть — и дальше селектор отправлял ей
    # задачи с картинками по несуществующей способности. Проверка, которая
    # не проверяет, хуже отсутствия проверки: она даёт уверенный неверный
    # ответ.
    verdict = judge(txt)
    return model_id, verdict, txt[:90]


#: Отказ вместо ответа. Модель может честно сказать, что не видит, — и это
#: полезнее, чем угадать, но слово «не вижу» в тексте само по себе не
#: приговор, поэтому проверяется осмысленно.
REFUSALS = ("не могу вид", "не вижу", "no image", "cannot see", "can't see",
            "не поддержива", "not support", "unable to", "no vision")


def judge(text: str) -> str:
    """`vision`, `unsure` или `no` — по тому, что модель написала.

    Эвристика, и это сказано прямо: картинка собрана так, что синих пикселей
    `BLUE_TOTAL` из `SIZE * SIZE`, то есть верная доля около 0.40. Ответ
    принимается в коридоре, а не в точке: честная модель считает
    приблизительно и пишет «0.4», «40%», «около 40 процентов».

    Коридор узкий — 0.30…0.48. Шире он был бы нечестным: угадавший наугад
    попадает в любой разумный коридор с заметной вероятностью, и тогда
    проверка сообщала бы уверенность, которой у неё нет.

    Ответ вне коридора, но близко к нему, — это `unsure`, а не `no`: скорее
    всего модель посчитала неудачно, но сказать «не умеет видеть» на
    основании одной попытки нельзя. Такие строки видно в отчёте, и решает
    человек.
    """
    lowered = text.lower()
    if any(word in lowered for word in REFUSALS):
        return "no"
    number = first_number(text)
    if number is None:
        return "no"
    if number > 1.0 and number <= 100.0:
        number /= 100.0          # «40%» и «40 процентов»
    if 0.30 <= number <= 0.48:
        return "vision"
    if 0.15 <= number <= 0.75:
        return "unsure"
    return "no"


def first_number(text: str) -> float | None:
    """Первое число в ответе: `0.4`, `40%`, «около 40 процентов»."""
    import re

    match = re.search(r"\d+(?:[.,]\d+)?", text.replace(",", "."))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


async def main():
    root = pathlib.Path(".")
    tally: dict[str, int] = {}
    gateways = load_gateways(root, env={})
    registry = await collect(gateways, root=root, check_price=False)

    # Кандидаты: только те, у кого в имени/шлюзе намек на vision
    hints = ("gemma", "vision", "omni", "vl", "-vl", "pixtral", "multimodal", "llava")
    candidates = []
    for m in registry.chat_models:
        low = m.model_id.lower()
        if any(h in low for h in hints):
            candidates.append(m)
        elif m.gateway_id in ("z_ai", "openrouter") and any(h in low for h in ("glm-4.6v",)):
            candidates.append(m)

    print(f"Кандидатов на vision: {len(candidates)} (синих пикселей: {BLUE_TOTAL})\n", flush=True)
    by_id = {g["id"]: g for g in gateways}

    async with httpx_client() as client:
        for m in candidates:
            g = by_id[m.gateway_id]
            mid, status, detail = await check(client, g, m.model_id)
            mark = {"vision": "VISION", "no": "  no  ", "unsure": " ???? ",
                    "err": "  err  "}[status]
            print(f"[{mark}] {m.ref:<62} {detail}", flush=True)
            tally[status] = tally.get(status, 0) + 1
            await asyncio.sleep(2.5)

    if tally:
        print(f"\nумеют видеть: {tally.get('vision', 0)}, "
              f"неясно: {tally.get('unsure', 0)}, "
              f"нет: {tally.get('no', 0)}, ошибок: {tally.get('err', 0)}")
        print("«????» — ответ рядом с верным, но не в коридоре: скорее всего "
              "модель посчитала неудачно. Смотреть глазами, а не считать "
              "уверенностью.")


def httpx_client():
    import httpx
    return httpx.AsyncClient(follow_redirects=True)


#: Запуск под `__main__`, а не на верхнем уровне: иначе `import` запускал бы
#: проверку по всем моделям. Из-за этого разбор ответа нельзя было закрыть
#: тестом — а именно он и решает, кого считать умеющим видеть.
if __name__ == "__main__":
    asyncio.run(main())
