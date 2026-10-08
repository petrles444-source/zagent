r"""Сгенерировать абстрактные картинки через LoRA на процессоре.

Зачем
----
Пять подач-заглушек сделаны на стоковых абстрактных картинках.
Картинки, похожие именно на них, делаются собственными весами: DreamShaper 8
как база плюс одна из шести LoRA, которые уже лежат в проекте.

Почему на процессоре, а не на видеокарте
----------------------------------------
Видеокарты на машине нет: `torch 2.14.1+cpu`, `cuda.is_available()` —
ложь. Остаётся процессор, и это меняет всё: картинка считается
минутами, а не секундами. Поэтому шагов немного, размер небольшой, а
генерация идёт в фоне, пока делается остальная работа.

Что стоит знать про скорость
----------------------------
SD 1.5 на 512×512 и 20 шагов на восьми потоках но��бука — это минуты
на картинку, не секунды. Полный прогон пятнадцати картинок занимает
десятки минут, и обрывать его нельзя: прерванная загрузка модели
оставляет на диске файл в два гигабайта, который потом мешает.

Порядок загрузки важен
----------------------
Сначала база, потом LoRA. Иначе пиковое потребление памяти выше, а на
процессоре память та же, что везде, — упереться легко.

Запуск:
    .venv\\Scripts\\python.exe tools\\gen_abstract.py --steps 20 --size 512
    .venv\\Scripts\\python.exe tools\\gen_abstract.py --probe
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: ComfyUI с моделями больше не лежит внутри агента: он вынесен рядом,
#: потому что весит 2,7 ГБ и к агенту отношения не имеет.
#:
#: Путь ищется в двух местах, потому что ComfyUI мог быть установлен
#: и рядом с агентом, и в другое место. Раньше путь был жёстко задан
#: на `WaveLora` внутри проекта, и после переноса инструмент молча
#: работал бы вхолостую, не найдя моделей.
MODELS_CANDIDATES = (
    ROOT.parent / "WaveLora" / "comfyui" / "models",
    ROOT / "WaveLora" / "comfyui" / "models",
)


def find_models_dir() -> Path | None:
    """Папка моделей ComfyUI, если она есть хотя бы в одном месте."""
    for candidate in MODELS_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


MODELS = find_models_dir() or MODELS_CANDIDATES[0]

BASE = MODELS / "checkpoints" / "dreamshaper_8.safetensors"

#: Шесть LoRA проекта и что каждая даёт. Брать по одной: две LoRA
#: на одной картинке спорят друг с другом, и результат становится
#: кашей из двух стилей вместо одного.
LORAS = {
    "diffuse": MODELS / "loras" / "diffuse_texture_v11.safetensors",
    "water":   MODELS / "loras" / "water.safetensors",
    "ocean":   MODELS / "loras" / "aivazovsky_ocean_v1.safetensors",
    "watercolor": MODELS / "loras" / "watercolor_v1.safetensors",
}

OUT = ROOT / "publish" / "generated"

#: Кэш моделей. По умолчанию HuggingFace берёт `C:\Users\<имя>\.cache`,
#: и на этой машине запись в неё запрещена: `PermissionError: [WinError 5]`.
#: Загрузка базовой модели прерывалась на середине, а в коде это
#: выглядело как «модель сломана». Поэтому кэш уводится в папку проекта,
#: на запись в которую точно есть права.
os.environ.setdefault("HF_HOME", str(ROOT / ".hf-cache"))

#: Подсказки под каждую картинку. Слова «abstract» и «texture» в
#: названиях LoRA значат разное, и подсказка должна это повторять,
#: иначе база уведёт в фигуратив.
PROMPTS = {
    "diffuse": ("abstract soft gradient texture, blurred bokeh light, "
                "smooth flowing colour fields, no objects, no text"),
    "water":   ("abstract liquid surface, swirling ripples, dark teal and "
                "cyan, macro photography of water, no objects"),
    "ocean":   ("abstract ocean waves from above, foam patterns, deep blue "
                "and white, aerial view, no objects"),
    "watercolor": ("abstract watercolour wash on paper, bleeding pigment, "
                   "warm beige and soft grey, texture of cotton paper"),
}

NEGATIVE = ("people, person, face, hands, text, letters, watermark, logo, "
            "signature, frame, border, collage, ui, interface")


def load(pipe, lora_path: Path | None, weight: float):
    """Подключить LoRA. `pipe` меняется на месте, возврат — для ясности."""
    if lora_path is None:
        return pipe
    if not lora_path.is_file():
        print(f"    LoRA нет: {lora_path.name}", file=sys.stderr)
        return pipe
    pipe.load_lora_weights(str(lora_path))
    pipe.fuse_lora(lora_weight=weight)
    pipe.unload_lora_weights()
    print(f"    LoRA: {lora_path.name}, вес {weight}")
    return pipe


def main() -> int:
    parser = argparse.ArgumentParser(description="абстрактные картинки")
    parser.add_argument("--steps", type=int, default=20,
                        help="шагов: больше — качество, меньше — скорость")
    parser.add_argument("--size", type=int, default=512,
                        help="сторона в пикселях")
    parser.add_argument("--weight", type=float, default=0.7,
                        help="вес LoRA: выше 1.2 картинка плывёт")
    parser.add_argument("--probe", action="store_true",
                        help="сгенерировать одну картинку и засечь время")
    parser.add_argument("--only", choices=sorted(PROMPTS),
                        help="только одна LoRA")
    args = parser.parse_args()

    if not BASE.is_file():
        print(f"нет базовой модели: {BASE}", file=sys.stderr)
        return 2

    try:
        import torch
        from diffusers import StableDiffusionPipeline
    except ImportError as exc:
        print(f"не хватает пакетов: {exc}", file=sys.stderr)
        print("  .venv\\Scripts\\python.exe -m pip install diffusers "
              "transformers accelerate", file=sys.stderr)
        return 2

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    print(f"устройство: {device}")
    print(f"потоков:    {torch.get_num_threads()}")
    print(f"размер:     {args.size}×{args.size}, шагов: {args.steps}")
    print(f"база:       {BASE.name} "
          f"({BASE.stat().st_size / 1024**2:.0f} МБ)")

    if device == "cpu":
        print("\nВНИМАНИЕ: видеокарты нет, считает процессор.")
        print("Картинка 512×512 на 20 шагов — минуты, не секунды.")

    started = time.monotonic()
    print("\nзагрузка модели...")
    pipe = StableDiffusionPipeline.from_single_file(
        str(BASE), torch_dtype=dtype, safety_checker=None,
        requires_safety_checker=False)
    pipe = pipe.to(device)
    pipe.set_progress_bar_config(disable=True)
    print(f"  готово за {time.monotonic() - started:.0f} с")

    keys = [args.only] if args.only else list(PROMPTS)
    if args.probe:
        keys = keys[:1]

    OUT.mkdir(parents=True, exist_ok=True)
    print()
    for index, key in enumerate(keys, 1):
        prompt = PROMPTS[key]
        print(f"[{index}/{len(keys)}] {key}")
        tick = time.monotonic()
        pipe = load(pipe, LORAS.get(key), args.weight)
        image = pipe(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            num_inference_steps=args.steps,
            guidance_scale=7.0,
            height=args.size,
            width=args.size,
            generator=torch.Generator(device).manual_seed(1000 + index),
        ).images[0]
        spent = time.monotonic() - tick
        target = OUT / f"{key}.jpg"
        image.save(target, "JPEG", quality=88, optimize=True)
        print(f"    {target.relative_to(ROOT)}  "
              f"{target.stat().st_size / 1024:.0f} КБ  за {spent:.0f} с")

    print(f"\nвсего: {time.monotonic() - started:.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
