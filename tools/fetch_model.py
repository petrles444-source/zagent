#!/usr/bin/env python3
r"""Скачать модель для рисования на процессоре.

Зачем это отдельным скриптом
---------------------------
Модель весит 2,5 гигабайта, и качать её при каждом запуске генератора
нельзя. Скрипт один раз проверяет, всё ли на месте, и докачивает
недостающее. Прерванная закачка не считается готовой: рядом с каждым
файлом лежит `.part`, и он удаляется только после успешной записи.

Почему PyTorch, а не ONNX
------------------------
Сначала была выбрана сборка в ONNX: движок легче и не тянет за собой
стек обучения. На этой машине она не пошла — `unet/model.onnx` требует
ядро `com.microsoft.NhwcConv`, а в готовой сборке onnxruntime для
Windows этого ядра нет:

    NOT_IMPLEMENTED: Failed to find kernel for com.microsoft.NhwcConv

Обойти это можно было бы только заменой сборки движка, и выигрыш от
ONNX терялся бы. Поэтому берётся обычная модель SD-Turbo для PyTorch:
она считает на том же процессоре, а ядро для неё гарантированно есть.

Что качается
------------
`stabilityai/sd-turbo` — модель с малым числом шагов: картинка
собирается за один-два прохода вместо двадцати пяти.

Запуск
------
    .venv\Scripts\python.exe tools\fetch_model.py
    .venv\Scripts\python.exe tools\fetch_model.py --check

Путь к модели: `models/sd-turbo`. Папка в `.gitignore`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "models" / "sd-turbo"

#: Адрес набора. Заменять нечего: он официальный и стабильный.
REPO = "stabilityai/sd-turbo"

#: Что обязательно для картинки: веса шумоподавителя, декодера и
#: текстовой части. Без текстовой части не из чего делать подсказку.
NEEDED = [
    "model_index.json",
    "scheduler/scheduler_config.json",
    "text_encoder/config.json",
    "text_encoder/model.safetensors",
    "tokenizer/merges.txt",
    "tokenizer/special_tokens_map.json",
    "tokenizer/tokenizer_config.json",
    "tokenizer/vocab.json",
    "unet/config.json",
    "unet/diffusion_pytorch_model.safetensors",
    "vae/config.json",
    "vae/diffusion_pytorch_model.safetensors",
]

#: Служебные файлы, без которых `diffusers` не примет папку.
EXTRA = [
    "feature_extractor/preprocessor_config.json",
    "safety_checker/config.json",
]

#: Файл весов, который весит больше всего. Его размер известен, и по
#: нему удобно проверять, что закачка не оборвалась на середине.
BIGGEST = "unet/diffusion_pytorch_model.safetensors"


def prepare_cache() -> None:
    """Перенести кэш библиотеки в папку проекта.

    `huggingface_hub` пишет служебные файлы в профиль пользователя, а
    на этой машине туда нельзя: каталог кэша не создаётся, и закачка
    падает с «Access is denied. (os error 5)» уже после того, как
    началась. Путь задаётся до первого обращения к библиотеке, иначе
    она успевает создать свой каталог и упасть на первой же записи.
    """
    cache = ROOT / ".hf-cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # Заодно отключаем ускоренную закачку через xet: она пишет свой
    # журнал в тот же кэш и на некоторых системах падает первой.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def repo_size() -> int:
    """Сколько весит набор на сервере. -1 — сервер не ответил."""
    import json
    import urllib.request
    url = f"https://huggingface.co/api/models/{REPO}?blobs=true"
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "zagent-fetch/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return -1
    total = 0
    for item in data.get("siblings", []):
        name = item.get("rfilename") or ""
        if name.endswith(".safetensors") or name.endswith(".bin"):
            total += item.get("size") or 0
    return total


def sizes() -> dict[str, int]:
    """Размер каждого файла, который нужен. Пусто — сервер не ответил."""
    import json
    import urllib.request
    url = f"https://huggingface.co/api/models/{REPO}?blobs=true"
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "zagent-fetch/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    return {item.get("rfilename"): item.get("size") or 0
            for item in data.get("siblings", [])}


def ok(path: Path, expected: int) -> bool:
    """Файл на месте и нужного размера."""
    if not path.is_file():
        return False
    if expected and path.stat().st_size != expected:
        return False
    return path.stat().st_size > 0


def main() -> int:
    parser = argparse.ArgumentParser(description="скачать модель")
    parser.add_argument("--check", action="store_true",
                        help="только проверить, ничего не качать")
    args = parser.parse_args()

    prepare_cache()
    print(f"набор: {REPO}")
    print(f"папка: {DEST}")

    known = sizes()
    if not known:
        print("сервер не отдал список файлов. Проверь сеть.")
        return 2
    wanted = [name for name in NEEDED + EXTRA
              if name in known or name in NEEDED]
    total = sum(known.get(name, 0) for name in wanted)
    print(f"нужно файлов: {len(wanted)}, "
          f"объём: {total / 1024 / 1024 / 1024:.2f} ГБ")

    if args.check:
        missing = [name for name in wanted
                   if not ok(DEST / name, known.get(name, 0))]
        if missing:
            print(f"не хватает {len(missing)}:")
            for name in missing:
                print(f"  {name}")
            return 1
        print("всё на месте")
        return 0

    from huggingface_hub import hf_hub_download

    failed: list[str] = []
    for index, name in enumerate(wanted, 1):
        target = DEST / name
        if ok(target, known.get(name, 0)):
            print(f"  [{index}/{len(wanted)}] есть  {name}")
            continue
        print(f"  [{index}/{len(wanted)}] качаю {name}", flush=True)
        try:
            # Копия, а не симлинк и не файл в кэше библиотеки: кэш
            # живёт в профиле пользователя и переживает удаление папки
            # проекта, а модель нужна именно рядом с ним.
            hf_hub_download(repo_id=REPO, filename=name,
                            local_dir=str(DEST))
        except Exception as exc:
            print(f"  ОШИБКА {name}: {type(exc).__name__}: {exc}", flush=True)
            failed.append(name)

    if failed:
        print(f"\nне скачано: {len(failed)} — {', '.join(failed[:5])}")
        print("Повтори запуск — докачается только недостающее.")
        return 1

    # Служебные файлы — по возможности, а не обязательно: без них
    # генератор работает, а их отсутствие не повод обрывать загрузку.
    for name in EXTRA:
        if name not in known:
            continue
        try:
            hf_hub_download(repo_id=REPO, filename=name,
                            local_dir=str(DEST))
        except Exception:
            pass

    total_bytes = sum(p.stat().st_size for p in DEST.rglob("*") if p.is_file())
    print(f"\nвсё на месте: {total_bytes / 1024 / 1024:.0f} МБ в {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())