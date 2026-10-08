#!/usr/bin/env python3
r"""Рисовать картинки для сайта на процессоре, моделью SD-Turbo.

Зачем процессор, а не видеокарта
-------------------------------
Видеокарты здесь нет: только встроенная Intel UHD. Поэтому генерация
считается на CPU. Модель turbo выбрана не по красоте, а по числу
шагов: SD-Turbo рисует за 1–2 прохода вместо обычных двадцати пяти,
и на процессоре это разница между минутой и получасовым ожиданием.

Как это устроено
----------------
Пайплайн и планировщик шагов берутся из `diffusers`. Писать их руками
нельзя: ошибка на шаг-другой даёт серый шум вместо картинки, и понять,
что не так, можно только сравнением с эталоном. Первый вариант
генератора был именно такой ошибкой — и вдобавок опирался на ONNX,
у которого на этой машине нет ядра `NhwcConv`.

Ограничения, о которых стоит знать заранее
-----------------------------------------
* **Качество ниже, чем у большой модели на видеокарте.** Turbo создан
  ради скорости: лица, руки и мелкий текст получаются плохо. Поэтому
  в подсказках нет людей и надписей — только предметы, свет и цвет.
* **Одна картинка — от минуты до нескольких минут.** Норма для CPU на
  двенадцати ядрах. Картинки рисуются один раз и кладутся в папку, а
  не каждый запрос.
* **Повторяемость.** При одинаковом зерне и числе шагов картинка
  выходит одна и та же. На этом и строится отбор: сначала дешёвые
  прогоны, потом в сайт идёт лучшее.

Запуск
------
    .venv\Scripts\python.exe tools\make_images.py --list
    .venv\Scripts\python.exe tools\make_images.py --all --steps 2
    .venv\Scripts\python.exe tools\make_images.py --only hero-neon --force
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "sd-turbo"
OUT = ROOT / "site" / "assets" / "img"

#: Кэш библиотеки — в папку проекта: в профиль пользователя писать
#: нельзя, и закачка падает на первой же служебной записи.
os.environ.setdefault("HF_HOME", str(ROOT / ".hf-cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

#: Размер картинки. 512 — родной для turbo, и на процессоре это
#: единственный размер, при котором он не превращается в кашу.
SIZE = 512

#: Шаги шума. У turbo их смысл есть только в начале шкалы: два шага
#: достаточно, а двадцать пять не дадут ничего, кроме времени.
DEFAULT_STEPS = 2

#: Насколько модель следует подсказке. Выше 1.5 начинаются артефакты.
GUIDANCE = 1.0

#: Подсказки для сайта.
#:
#: Слова «человек», «девушка», «мужчина» убраны намеренно: turbo рисует
#: лица плохо, и картинка с лицом выдаёт себя сразу. Предметы, свет и
#: цвет работают хорошо, поэтому подсказки описывают именно их.
#: Якорь персонажа: неизменное описание лица.
#:
#: Копируется в каждый промт набора `character` дословно. Это и есть
#: тот приём, который даёт узнаваемое лицо в разных ракурсах: если
#: описание внешности меняется от кадра к кадру, получаются разные
#: люди, и датасет для LoRA бесполезен.
#:
#: Объявлено до `SETS`: словарь собирается на импорте, и якорь нужен
#: прямо в нём, а не после.
anchor = ("a 25-year-old woman, shoulder-length wavy ash-blonde hair, "
          "striking bright piercing blue eyes, pale skin, "
          "small beauty mark under her left eye, "
          "black leather choker with a silver crescent moon pendant, ")

SETS: dict[str, list[dict[str, object]]] = {
    "site": [
        {
            "name": "hero-neon",
            "prompt": "abstract digital archive, glowing cyan grid lines in "
                      "dark space, holographic data panels floating, "
                      "volumetric light, high tech, cinematic lighting, "
                      "ultra detailed, 8k render",
            "seed": 1201,
        },
        {
            "name": "hero-player",
            "prompt": "retro computer monitor glowing in a dark room, "
                      "abstract light patterns on screen, purple and cyan "
                      "light, moody atmosphere, cinematic, 8k render",
            "seed": 1202,
        },
        {
            "name": "block-archive",
            "prompt": "endless archive of glowing storage crystals, cyan "
                      "emission, dark background, futuristic data storage, "
                      "volumetric fog, 8k render",
            "seed": 1203,
        },
        {
            "name": "block-radio",
            "prompt": "abstract sound waves visualization, concentric neon "
                      "rings, magenta and cyan gradient, dark studio, "
                      "studio photography, 8k",
            "seed": 1204,
        },
        {
            "name": "block-bot",
            "prompt": "abstract chatbot concept, floating translucent "
                      "interface panels, green and cyan glow, dark "
                      "background, minimal, 8k render",
            "seed": 1205,
        },
        {
            "name": "block-swf",
            "prompt": "abstract retro pixel art explosion, warm orange and "
                      "yellow particles on dark background, 90s computer "
                      "graphics aesthetic, 8k",
            "seed": 1206,
        },
    ],
    "port": [
        {
            "name": "port-neon",
            "prompt": "dark cyberpunk alley with neon signs, rain "
                      "reflections, cyan and magenta light, wide angle, "
                      "cinematic, 8k render",
            "seed": 2201,
        },
        {
            "name": "port-paper",
            "prompt": "overhead view of old paper documents with ink "
                      "drawings on a wooden desk, warm lamp light, minimal, "
                      "photography, high detail",
            "seed": 2202,
        },
        {
            "name": "port-term",
            "prompt": "dark room with an old CRT monitor glowing green text, "
                      "minimal desk, moody green light, photography, 8k",
            "seed": 2203,
        },
    ],
    # Персонаж для обучения LoRA. Десять ракурсов по одному набору:
    # ровно столько нужно, чтобы лицо выучилось, а не одежда.
    #
    # Описание лица повторяется дословно в каждом промте — это якорь.
    # Без одинакового якоря каждый кадр получается разным человеком,
    # и тренировать будет нечего.
    "character": [
        {"name": "char_portrait", "prompt": anchor + " close-up portrait, "
         "looking at camera, calm neutral expression, studio lighting, "
         "soft gray background, sharp focus on eyes, detailed facial "
         "features, photorealistic", "seed": 3101},
        {"name": "char_neon", "prompt": anchor + " medium shot, dark "
         "neon-lit cyberpunk alley at night, confident stance, slight "
         "smirk, futuristic glowing jacket, pink and cyan rim lighting, "
         "moody atmosphere, cinematic", "seed": 3102},
        {"name": "char_fantasy", "prompt": anchor + " full body shot, "
         "elegant flowing white silk dress, barefoot in a magical "
         "bioluminescent forest, soft morning light through glowing "
         "leaves, ethereal, fantasy art", "seed": 3103},
        {"name": "char_cafe", "prompt": anchor + " sitting at a table in a "
         "cozy vintage cafe, laughing, holding a cup of coffee, warm "
         "golden hour light, candid lifestyle photography", "seed": 3104},
        {"name": "char_action", "prompt": anchor + " extreme low angle "
         "shot, running through a rainy city street, fierce determined "
         "expression, wet dark trench coat, splashing puddles, dramatic "
         "cinematic rain lighting", "seed": 3105},
        {"name": "char_space", "prompt": anchor + " medium shot, "
         "futuristic white spacesuit, helmet held under arm, inside a "
         "spaceship cockpit, looking out the window at a distant galaxy, "
         "cool blue ambient lighting, sci-fi concept art", "seed": 3106},
        {"name": "char_cliff", "prompt": anchor + " profile shot, sitting "
         "on the edge of a rocky cliff over the ocean, melancholic "
         "expression, wind blowing hair, oversized knitted sweater, "
         "dramatic sunset lighting", "seed": 3107},
        {"name": "char_ball", "prompt": anchor + " medium shot, dancing "
         "with a man in a black tuxedo in a luxurious ballroom, joyful "
         "expression, sparkling red evening gown, warm chandelier "
         "lighting, high society event", "seed": 3108},
        {"name": "char_fashion", "prompt": anchor + " extreme macro "
         "close-up on face, high fashion editorial photography, fierce "
         "expression, avant-garde reflective sunglasses, harsh studio "
         "flash lighting, sharp shadows, magazine cover style",
         "seed": 3109},
        {"name": "char_snow", "prompt": anchor + " full body action "
         "shot, snowboarding down a steep snowy mountain slope, excited "
         "wide smile, bright modern winter sports gear, crisp winter "
         "sunlight, snow particles in air, dynamic action photography",
         "seed": 3110},
    ],
}

#: Куда кладутся картинки каждого набора. Для персонажа папка
#: отдельная: там потом собирается датасет с подписями.
SET_DIRS = {"character": "character/dataset"}

#: Отрицательный промпт: то, чего на картинке быть не должно.
#:
#: Turbo плохо понимает «пустой» и «без текста» — он всё равно рисует
#: надписи. Зато хорошо понимает «гладкий фон», поэтому запрет задан
#: через то, что выглядит как описание, а не как отсутствие.
NEGATIVE = ("blurry, low quality, watermark, text, letters, words, "
            "signature, deformed, jpeg artifacts, oversaturated")


class Turbo:
    """SD-Turbo на процессоре. Модель грузится один раз."""

    def __init__(self, threads: int = 0) -> None:
        import torch
        from diffusers import AutoPipelineForText2Image

        # Число потоков задаётся до загрузки: иначе torch успевает
        # раздать ядра по своему усмотрению, и это не то, о чём просили.
        if threads:
            torch.set_num_threads(threads)
        print(f"потоков: {torch.get_num_threads()}", flush=True)
        print("загружаю модель…", flush=True)
        # safety_checker отключён намеренно: картинки идут на сайт
        # проекта, а проверка на каждом шаге съедает заметную часть
        # времени на процессоре и ни разу ничего не остановила.
        self.pipe = AutoPipelineForText2Image.from_pretrained(
            str(MODEL), torch_dtype=torch.float32,
            safety_checker=None, requires_safety_checker=False)
        self.pipe.set_progress_bar_config(disable=True)
        print("модель готова", flush=True)

    def generate(self, prompt: str, seed: int,
                 steps: int = DEFAULT_STEPS) -> "object":
        """Одна картинка. Возвращает картинку PIL."""
        import torch
        # Зерно задаётся перед каждым рисованием: иначе все картинки
        # в наборе окажутся вариациями одной и той же.
        generator = torch.Generator("cpu").manual_seed(seed)
        result = self.pipe(
            prompt=prompt,
            negative_prompt=NEGATIVE,
            num_inference_steps=steps,
            guidance_scale=GUIDANCE,
            width=SIZE,
            height=SIZE,
            generator=generator,
        )
        return result.images[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="рисовать картинки")
    parser.add_argument("--set", help="набор подсказок")
    parser.add_argument("--all", action="store_true", help="все наборы")
    parser.add_argument("--list", action="store_true", help="только список")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--only", help="одна картинка по имени")
    parser.add_argument("--force", action="store_true",
                        help="перерисовать, даже если файл есть")
    args = parser.parse_args()

    if args.list:
        for set_name, items in SETS.items():
            print(f"\n[{set_name}]")
            for item in items:
                print(f"  {item['name']:18} зерно {item['seed']}")
        return 0

    names = sorted(SETS) if args.all else [args.set or "site"]
    unknown = [n for n in names if n not in SETS]
    if unknown:
        print(f"нет такого набора: {', '.join(unknown)}")
        print(f"есть: {', '.join(sorted(SETS))}")
        return 2

    if not MODEL.is_dir():
        print(f"нет модели в {MODEL}\n"
              "Сначала запусти: .venv\\Scripts\\python.exe "
              "tools\\fetch_model.py")
        return 2

    engine = Turbo(threads=args.threads)
    done = skipped = failed = 0
    started = time.monotonic()

    for set_name in names:
        for item in SETS[set_name]:
            if args.only and item["name"] != args.only:
                continue
            # Набор персонажа идёт в свою папку: там потом
            # `make_lora_dataset.py` допишет подписи и переименует
            # файлы в `0001.png`, как того ждёт тренажёр.
            folder = ROOT / SET_DIRS.get(set_name, "site/assets/img")
            target = folder / f"{item['name']}.png"
            if target.is_file() and not args.force:
                print(f"есть {item['name']}")
                skipped += 1
                continue
            print(f"рисую {item['name']}…", flush=True)
            begin = time.monotonic()
            try:
                image = engine.generate(str(item["prompt"]),
                                        int(item["seed"]), args.steps)
            except Exception as exc:
                print(f"  ОШИБКА {item['name']}: {type(exc).__name__}: {exc}",
                      flush=True)
                failed += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, "PNG", optimize=True)
            done += 1
            print(f"  готово {item['name']} — {time.monotonic() - begin:.0f} с, "
                  f"{target.stat().st_size / 1024:.0f} КБ", flush=True)

    print(f"\nнарисовано {done}, пропущено {skipped}, ошибок {failed}, "
          f"всего {time.monotonic() - started:.0f} с")
    print(f"картинки в {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())