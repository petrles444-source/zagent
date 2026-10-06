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
    return model_id, "vision", txt[:90]


async def main():
    root = pathlib.Path(".")
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
            mark = "VISION" if status == "vision" else "  ---  "
            print(f"[{mark}] {m.ref:<62} {detail}", flush=True)
            await asyncio.sleep(2.5)


def httpx_client():
    import httpx
    return httpx.AsyncClient(follow_redirects=True)


asyncio.run(main())
