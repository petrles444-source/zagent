#!/usr/bin/env python3
r"""zcli — консольный клиент агента zagent: задачи, зрение, перевод.

Уровень детализации 5/10: основные команды работают, зрение включается
только когда установлены mss и opencv, перевод идёт через локальную
модель. Чего сознательно нет — разбора ошибок в глубину, веб-интерфейса
и фонового планировщика: это делает сам агент.

Связь с уже работающим агентом
------------------------------
Программа не поднимает ничего своего: она говорит с тем же сервером, что
и веб-панель, теми же маршрутами из `hub/protocol`. Поэтому задача,
отправленная отсюда, видна в браузере, и наоборот.

    .venv\Scripts\python.exe tools\zcli.py ask почини падающий тест
    .venv\Scripts\python.exe tools\zcli.py models
    .venv\Scripts\python.exe tools\zcli.py shot out.png
    .venv\Scripts\python.exe tools\zcli.py vision что на экране?
    .venv\Scripts\python.exe tools\zcli.py translate Hello, world

Зрение
------
Захват экрана - mss, обработка - OpenCV (нарезка на области, уменьшение,
подсветка текстовых прямоугольников). Кадр уходит в мультимодальную
модель как base64 JPEG, ответ сохраняется в `document/`.

Ключи моделей берутся из `config/secrets.local.json` и никуда не
записываются: в отчёт попадает имя модели, а не значение ключа.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import local_llm  # noqa: E402
from hub.config import load_gateways, resolve_keys  # noqa: E402
from hub.protocol import Routes, Server, task_payload  # noqa: E402

#: Куда складываются отчёты. Именно та папка, о которой говорилось в
#: задании, и именно она исключена из репозитория.
DOCUMENTS_DIR = ROOT / "document"

#: Сколько ждём локальную модель. Перевод идёт после анализа, поэтому
#: времени достаточно, но и не бесконечно.
LOCAL_TIMEOUT_S = 240.0

#: Предел JPEG-энкодера OpenCV по большей стороне кадра. Превышение
#: даёт пустой результат imencode без внятной ошибки, поэтому масштаб
#: считается с запасом.
JPEG_MAX_SIDE = 65000

#: Какая доля кириллицы считается «ответ на русском».
RUSSIAN_SHARE = 0.3


# ============================================================ сервер агента


def server_request(path: str, payload: dict[str, Any] | None = None,
                   base: str = Server.BASE, timeout: float = 30.0) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            parsed = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.URLError as exc:
        return {"ok": False,
                "error": f"сервер агента не отвечает ({type(exc).__name__})"}
    except Exception as exc:  # noqa: BLE001 - клиент должен говорить, а не падать
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return parsed if isinstance(parsed, dict) else {"ok": False, "error": "не объект"}


def cmd_ask(args: argparse.Namespace) -> int:
    data = server_request(Routes.SEND_TASK, task_payload(args.text))
    if not data.get("ok"):
        print(f"Ошибка: {data.get('error') or 'агент не принял задачу'}")
        return 1
    print(f"Задача #{data.get('task_id')} принята. Следить: в панели 8783")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    data = server_request(Routes.STATE, timeout=15.0)
    if data.get("error"):
        print(f"Ошибка: {data['error']}")
        return 1
    print(f"Моделей в реестре: {len(data.get('candidates') or [])}")
    print(f"Задач в базе:     {len(data.get('tasks') or [])}")
    print(f"Текущая:          {data.get('current_task') or '—'}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Модели: из моста и локальные. Ключи не показываются."""
    data = server_request(Routes.MODELS_STATUS, timeout=45.0)
    rows = data.get("models") or []
    if not rows:
        print("Моделей нет. Мост поднят?", data.get("bridge", {}).get("error", ""))
        return 1
    marks = {"ok": "отвечает", "local": "локально", "fail": "отказала",
             "cooling": "остывает", "unknown": "не проверена"}
    for row in rows:
        state = marks.get(str(row.get("state")), "?")
        ms = row.get("last_ms") or row.get("cooldown_left_s") or ""
        print(f"  {str(row.get('id')):38} {state:12} {ms}")
    return 0


def cmd_keys(args: argparse.Namespace) -> int:
    """Какие шлюзы настроены. Значения ключей не печатаются."""
    for gateway in load_gateways(ROOT):
        gid = str(gateway.get("id") or "")
        if not gid:
            continue
        if gateway.get("keyless"):
            mark = "без ключа"
        else:
            mark = "ключ есть" if resolve_keys(gid, root=ROOT) else "КЛЮЧА НЕТ"
        print(f"  {gid:16} {mark}")
    return 0


# ================================================================= перевод


def cyrillic_share(text: str) -> float:
    """Доля кириллицы среди букв. Ноль - переводить нечего."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    cyr = sum(1 for c in letters if "а" <= c.lower() <= "я" or c.lower() == "ё")
    return cyr / len(letters)


def translate_to_russian(text: str, *, model: str = "qwen2.5:3b",
                         base: str = local_llm.DEFAULT_BASE,
                         timeout: float = LOCAL_TIMEOUT_S) -> str:
    """Перевести на русский локальной моделью.

    Отдельный переводчик не нужен: та же локальная модель отвечает и за
    анализ, и за язык. Ключ не требуется, интернет не требуется.
    """
    body = str(text or "").strip()
    if not body:
        return ""
    if cyrillic_share(body) >= RUSSIAN_SHARE:
        return body
    prompt = (
        "Переведи текст ниже на русский язык. Сохрани смысл, структуру и "
        "технические термины (имена файлов, команд, API - не переводи). "
        "Верни только перевод, без пояснений.\n\n"
        + body[:6000]
    )
    messages = [{"role": "user", "content": prompt}]
    return "".join(local_llm.stream_chat(model, messages, base=base,
                                         timeout=timeout)).strip()


# ================================================================== зрение


def scaled_size(width: int, height: int, scale: float = 1.0,
                limit: int = JPEG_MAX_SIDE) -> tuple[int, int]:
    """Размер кадра после уменьшения, с учётом предела энкодера.

    У JPEG в OpenCV потолок 65500 пикселей по стороне, и его превышение
    даёт пустой результат без внятной ошибки. На мультимониторном столе
    ширина кадра превышает этот предел всегда, поэтому масштаб доводится
    по большей стороне.

    Отдельная функция без OpenCV и без экрана - именно потому, что её
    надо проверять: внутри захвата проверять нечем, там всё упирается в
    железо машины.
    """
    factor = min(float(scale) if scale and scale > 0 else 1.0, 1.0)
    biggest = max(int(width), int(height))
    if biggest > limit:
        factor = min(factor, limit / float(biggest))
    return (max(1, int(int(width) * factor)),
            max(1, int(int(height) * factor)))


def looks_degenerate(shape) -> bool:
    """Похоже ли, что вместо изображения пришла полоса.

    Именно это выдаёт `np.frombuffer` без `reshape`: кадр 1xN вместо
    1920x1200. Ловим до отправки модели, где такой кадр выглядел бы как
    «зрение работает, ответ бессмысленный».
    """
    height, width = shape[0], shape[1]
    return height < 8 or width < 8


def vision_prompt(prompt: str, regions: list[str],
                  frame_size: tuple[int, int]) -> str:
    """Вопрос модели плюс найденные области и настоящие размеры кадра.

    Координаты областей приходят уже после уменьшения, и подсказка
    «в координатах кадра 1920x1080» была бы просто неверной на любом
    другом экране.
    """
    text = str(prompt or "")
    if not regions:
        return text
    width, height = frame_size
    return (text + "\n\nOpenCV нашёл на кадре области (в координатах "
            f"кадра {width}x{height}):\n- " + "\n- ".join(regions))


def opencv_available() -> tuple[bool, str]:
    """Есть ли что включать. Нет - говорим словами, а не падаем."""
    missing = []
    for name in ("cv2", "numpy", "mss"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        return False, "не хватает: " + ", ".join(missing)
    return True, ""


def capture_screen(monitor: int = 1, scale: float = 0.65) -> tuple[bytes, int]:
    """Снимок экрана как JPEG-байты и его размер в байтах.

    Уменьшаем картинку перед отправкой: мультимодальные API считают по
    токенам картинки, и полноэкранный 4K-снимок стоит дороже, чем даёт.
    """
    import cv2
    import numpy as np
    import mss as mss_module

    # `mss.mss()` помечен устаревшим; старая форма остаётся запасным
    # вариантом - на старых версиях `MSS` может ещё не быть.
    grab_factory = getattr(mss_module, "MSS", None) or mss_module.mss

    with grab_factory() as grab:
        targets = grab.monitors
        index = monitor if monitor < len(targets) else 1
        raw = grab.grab(targets[index])

    # Буфер от mss - одномерный. cvtColor на одномерном массиве не падает:
    # она молча делает картинку шириной во весь буфер и высотой в один
    # пиксель, и дальше всё исправно работает с этой полосой. Поэтому
    # форму задаём явно.
    frame = np.frombuffer(raw.rgb, dtype=np.uint8).reshape(
        int(raw.height), int(raw.width), 3)
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    # У JPEG-энкодера OpenCV жёсткий предел по стороне: 65500 пикселей.
    # На мультимониторном рабочем столе ширина кадра превышает его
    # всегда, и imencode молча возвращает False - снимок не создаётся
    # вообще. Масштаб считаем от большей стороны и доводим до предела.
    height, width = frame.shape[:2]
    new_width, new_height = scaled_size(width, height, scale)
    if (new_width, new_height) != (width, height):
        # Размер задаём явно: в OpenCV 5 вызов resize с dsize=None и
        # fx/fy падает с «!dsize.empty()». Считаем сами - так ещё и
        # понятно, каким получился кадр.
        frame = cv2.resize(frame, (new_width, new_height),
                           interpolation=cv2.INTER_AREA)
    if looks_degenerate(frame.shape):
        raise RuntimeError(
            f"кадр получился вырожденным ({frame.shape[1]}x{frame.shape[0]}) - "
            "захват вернул не изображение. Проверьте монитор: --monitor 1")
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise RuntimeError(
            f"OpenCV не смог закодировать JPEG (кадр {frame.shape[1]}x"
            f"{frame.shape[0]}) - проверьте предел размера")
    data = encoded.tobytes()
    return data, len(data), (frame.shape[1], frame.shape[0])


def describe_regions(data: bytes) -> list[str]:
    """Где на кадре текст и крупные блоки — подсказка для модели.

    Наивная эвристика, а не полноценный детектор: находим контуры и
    считаем, сколько тёмных пикселей в каждом. Модели этого достаточно,
    чтобы знать, где читать текст, а не гадать по всему кадру.
    """
    import cv2
    import numpy as np

    buf = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if frame is None:
        return []
    _, binary = cv2.threshold(frame, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    height, width = frame.shape[:2]
    out: list[str] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 40 or h < 12:
            continue
        if w * h < width * height * 0.002:
            continue
        share = cv2.countNonZero(binary[y:y + h, x:x + w]) / float(w * h)
        kind = "текст" if share > 0.35 else "блок"
        out.append(f"{kind} x={x} y={y} w={w} h={h}")
    return out


def ask_vision_model(prompt: str, image_b64: str, *, gateway: str,
                     model: str, timeout: float = 180.0) -> str:
    """Спросить модель с картинкой через наш failover-контур.

    Ключ берётся из конфигурации проекта и уходит в заголовке; в отчёт
    попадает только имя модели.
    """
    import urllib.error
    import urllib.request

    from hub.config import load_gateways

    base_url = ""
    for gateway_cfg in load_gateways(ROOT):
        if str(gateway_cfg.get("id") or "") == gateway:
            base_url = str(gateway_cfg.get("base_url") or "")
            break
    if not base_url:
        raise RuntimeError(f"шлюз {gateway!r} не найден в config/gateways.json")
    keys = resolve_keys(gateway, root=ROOT)
    headers = {"Content-Type": "application/json"}
    if keys:
        headers["Authorization"] = f"Bearer {keys[0]}"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        }],
    }
    req = urllib.request.Request(f"{base_url.rstrip('/')}/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{gateway} ответил HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{gateway} недоступен: {type(exc).__name__}") from exc
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"{gateway}: {data['error']}")
    choices = (data or {}).get("choices") or []
    first = choices[0] if isinstance(choices, list) and choices else {}
    content = ((first.get("message") or {}).get("content") or "") if isinstance(first, dict) else ""
    return str(content).strip()


def save_report(title: str, body: str, *, meta: dict[str, Any] | None = None,
                directory: Path = DOCUMENTS_DIR) -> Path:
    """Отчёт в `document/`. Метка времени в имени - файлы не перетираются."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch for ch in title.lower() if ch.isalnum() or ch in "-_")[:40]
    path = directory / f"{stamp}-{safe or 'report'}.md"
    lines = [f"# {title}", "",
             f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    for key, value in (meta or {}).items():
        lines.append(f"{key}: {value}")
    lines += ["", "---", "", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def cmd_shot(args: argparse.Namespace) -> int:
    ok, why = opencv_available()
    if not ok:
        print(f"Зрение недоступно: {why}")
        print("Установите:  .venv\\Scripts\\pip.exe install opencv-python mss numpy")
        return 1
    data, size, _ = capture_screen(args.monitor, args.scale)
    target = Path(args.out) if args.out else DOCUMENTS_DIR / f"shot-{int(time.time())}.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"Снимок: {target} ({size // 1024} КБ)")
    return 0


def cmd_vision(args: argparse.Namespace) -> int:
    ok, why = opencv_available()
    if not ok:
        print(f"Зрение недоступно: {why}")
        print("Установите:  .venv\\Scripts\\pip.exe install opencv-python mss numpy")
        return 1
    print("Захват экрана...")
    data, size, frame_size = capture_screen(args.monitor, args.scale)
    b64 = base64.b64encode(data).decode("ascii")
    regions = describe_regions(data)

    prompt = vision_prompt(args.prompt, regions, frame_size)

    print(f"Кадр {size // 1024} КБ, спрашиваю {args.gateway}/{args.model}...")
    try:
        answer = ask_vision_model(prompt, b64, gateway=args.gateway,
                                  model=args.model)
    except RuntimeError as exc:
        print(f"Модель не ответила: {exc}")
        print("Зрение включено, но для мультимодального анализа нужен шлюз "
              "с картинками (например openrouter или nvidia).")
        return 1

    translated = ""
    if args.russian:
        print("Перевожу на русский...")
        try:
            translated = translate_to_russian(answer, model=args.translate_model)
        except local_llm.LocalLLMError as exc:
            print(f"Перевод не удался ({exc}); сохраняю как есть.")

    body = translated or answer
    path = save_report(
        args.title or "Разбор кадра",
        body,
        meta={"шлюз": f"{args.gateway}/{args.model}",
              "переведено": "да" if translated else "нет",
              "кадр, КБ": size // 1024,
              "областей найдено": len(regions),
              "вопрос": args.prompt[:200]})
    print(f"\nОтчёт: {path}")
    print(body[:600])
    return 0


def cmd_translate(args: argparse.Namespace) -> int:
    try:
        print(translate_to_russian(args.text, model=args.model))
    except local_llm.LocalLLMError as exc:
        print(f"Перевод не удался: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zcli", description="Консольный клиент агента zagent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask", help="задать задачу агенту")
    ask.add_argument("text")
    ask.set_defaults(func=cmd_ask)

    sub.add_parser("status", help="состояние агента").set_defaults(func=cmd_status)
    sub.add_parser("models", help="все модели и их статус").set_defaults(func=cmd_models)
    sub.add_parser("keys", help="какие шлюзы настроены").set_defaults(func=cmd_keys)

    shot = sub.add_parser("shot", help="снимок экрана в файл")
    shot.add_argument("--monitor", type=int, default=1)
    shot.add_argument("--scale", type=float, default=0.65)
    shot.add_argument("--out", default="")
    shot.set_defaults(func=cmd_shot)

    vision = sub.add_parser("vision", help="снимок → модель → отчёт в document/")
    vision.add_argument("prompt", help="вопрос о том, что на экране")
    vision.add_argument("--gateway", default="openrouter")
    vision.add_argument("--model", default="google/gemma-4-26b-a4b-it")
    vision.add_argument("--monitor", type=int, default=1)
    vision.add_argument("--scale", type=float, default=0.65)
    vision.add_argument("--title", default="")
    vision.add_argument("--translate-model", default="qwen2.5:3b")
    vision.add_argument("--no-russian", dest="russian", action="store_false")
    vision.set_defaults(func=cmd_vision, russian=True)

    tr = sub.add_parser("translate", help="перевести текст на русский")
    tr.add_argument("text")
    tr.add_argument("--model", default="qwen2.5:3b")
    tr.set_defaults(func=cmd_translate)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())