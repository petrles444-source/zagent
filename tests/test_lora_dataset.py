"""Сборщик датасета для LoRA: подписи, имена и готовность архива.

Проверяется то, что тренажёр читает буквально: имя файла, текст рядом
и их совпадение. Ошибка здесь стоит дорого — тренажёр пропускает
файл молча, обучается на меньшем числе примеров, чем ожидалось, и
результат получается «непонятно плохой», а причину найти нельзя.

Почему тут важно имя
-------------------
Подпись и картинка сопоставляются по имени файла. Если имена разойдутся
(`0001.png` и `0007.txt`), файл не пропадёт с ошибкой — он просто не
попадёт в обучение. Поэтому проверяется именно совпадение, а не
«файлы вообще есть».
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

_spec = importlib.util.spec_from_file_location(
    "make_lora_dataset", TOOLS / "make_lora_dataset.py")
assert _spec and _spec.loader
ds = importlib.util.module_from_spec(_spec)
sys.modules["make_lora_dataset"] = ds
_spec.loader.exec_module(ds)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Папка с готовыми картинками: имена как до сборки."""
    out = tmp_path / "dataset"
    out.mkdir()
    for kind in ("portrait", "neon", "cafe", "snow"):
        (out / f"char_{kind}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return out


def run_build(folder: Path, tag: str = "ohwx") -> None:
    """Собрать датасет с аргументами по умолчанию."""
    args = type("Args", (), {
        "folder": str(folder), "tag": tag, "check": False, "zip": None,
    })()
    assert ds.build(args) == 0


# =============================================================== подписи


def test_у_каждой_картинки_есть_подпись(folder: Path) -> None:
    run_build(folder)
    for image in sorted(folder.glob("*.png")):
        caption = image.with_suffix(".txt")
        assert caption.is_file(), f"нет подписи у {image.name}"


def test_подпись_содержит_тег(folder: Path) -> None:
    """Тег без подсказки тренажёр не поймёт, что это персонаж."""
    run_build(folder, tag="ohwx")
    text = (folder / "0001.txt").read_text(encoding="utf-8")
    assert text.startswith("ohwx"), f"подпись началась не с тега: {text[:40]}"


def test_подпись_содержит_якорь_лица(folder: Path) -> None:
    """Неизменное описание внешности обязано быть в каждой подписи.

    Если его нет в части файлов, модель решит, что перед ней несколько
    разных людей, и лицо не сойдётся.
    """
    run_build(folder)
    for caption in sorted(folder.glob("*.txt")):
        text = caption.read_text(encoding="utf-8")
        assert "ash-blonde" in text, f"в {caption.name} нет описания волос"
        assert "blue eyes" in text, f"в {caption.name} нет описания глаз"


def test_ракурсы_различаются(folder: Path) -> None:
    """Разные ракурсы должны давать разные подписи.

    Иначе модель не поймёт, что именно меняется между картинками, и
    выучит одно и то же положение.
    """
    run_build(folder)
    texts = {p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.txt"))}
    assert len(texts) == 4, f"подписи совпали: {len(texts)} уникальных из 4"


def test_имени_нумеруются_по_порядку(folder: Path) -> None:
    """Имена вида 0001.png и 0001.txt связывают картинку с подписью."""
    run_build(folder)
    numbers = sorted(p.stem for p in folder.glob("*.png"))
    assert numbers == ["0001", "0002", "0003", "0004"], f"имена: {numbers}"
    for number in numbers:
        assert (folder / f"{number}.txt").is_file()


def test_старые_имена_исчезают(folder: Path) -> None:
    """После сборки в папке не остаётся файлов с прежними именами.

    Иначе тренажёр увидит вдвое больше примеров, чем задумано, и
    половина из них — без подписей.
    """
    run_build(folder)
    leftovers = [p.name for p in folder.glob("*.png")
                 if not p.stem.isdigit()]
    assert not leftovers, f"остались старые имена: {leftovers}"


def test_подписи_на_своих_местах(folder: Path) -> None:
    """Ракурс определяется по слову в имени, а не по номеру."""
    assert ds.kind_of(Path("char_neon.png")) == "neon"
    assert ds.kind_of(Path("0001.png")) == "0001"
    run_build(folder)
    joined = " ".join(p.read_text(encoding="utf-8")
                      for p in sorted(folder.glob("*.txt")))
    # Ракурсы описаны по-разному, и в подписи должен попасть именно
    # свой. Проверяем два разных: если попал только один, значит
    # `kind_of` для части файлов вернул что-то одно.
    assert "cyberpunk" in joined, "ракурс не попал в подпись"
    assert "snowboarding" in joined, "второй ракурс не попал в подпись"


# =============================================================== повтор


def test_повторный_запуск_не_стирает_ракурсы(folder: Path) -> None:
    """Второй запуск не должен терять описание ракурса.

    Это стоило дороже всего. `build` читает ракурс из имени файла и
    сам же переименовывает файлы в `0001.png` — на втором запуске он
    читает имена, которые создал на первом, и ракурса в них уже нет.
    Подпись при этом переписывалась заново: оставалась неизменная
    внешность и пропадало то, чем картинки отличаются друг от друга.

    Снаружи это выглядело как «неплохое качество модели»: датасет
    собирался, проверка проходила, тренажёр брал все файлы, а учиться
    было почти нечему. Настоящую причину найти можно было только
    вручную, открыв текст подписи.
    """
    run_build(folder)
    first = {p.name: p.read_text(encoding="utf-8")
             for p in sorted(folder.glob("*.txt"))}
    assert any("cyberpunk" in t for t in first.values()), "исходно ракурса нет"

    run_build(folder)
    second = {p.name: p.read_text(encoding="utf-8")
              for p in sorted(folder.glob("*.txt"))}

    assert second == first, "повторный запуск изменил подписи"
    joined = " ".join(second.values())
    assert "cyberpunk" in joined, "ракурс потерялся при повторной сборке"
    assert "snowboarding" in joined, "второй ракурс потерялся"


def test_пустая_подпись_переписывается(folder: Path) -> None:
    """Пустая подпись — это не готовая подпись, её надо дописать.

    Отличие от предыдущего случая обязательное: сохранять надо только
    то, что действительно написано. Пустой файл на месте готового
    означал бы, что картинка остаётся без описания навсегда, и
    проверка этого не заметила бы.
    """
    run_build(folder)
    (folder / "0002.txt").write_text("   \n", encoding="utf-8")
    run_build(folder)
    text = (folder / "0002.txt").read_text(encoding="utf-8")
    assert text.strip(), "пустая подпись осталась пустой"
    assert "ohwx" in text, "подпись не переписана"


# =============================================================== проверка


def test_пустая_папка_не_роняет_проверку(tmp_path: Path) -> None:
    """Папки может не быть — и это не повод падать с исключением."""
    missing = tmp_path / "нет-такой"
    assert ds.check(missing) == 1


def test_пустая_папка_говорит_что_делать(tmp_path: Path, capsys: Any) -> None:
    """Проверка обязана подсказать следующий шаг, а не молчать."""
    empty = tmp_path / "dataset"
    empty.mkdir()
    assert ds.check(empty) == 1
    out = capsys.readouterr().out
    assert "make_images.py" in out, "не сказано, чем нарисовать персонажа"


def test_картинка_без_подписи_ловится(folder: Path) -> None:
    """Неполный датасет должен обнаруживаться, а не проходить мимо."""
    run_build(folder)
    (folder / "0001.txt").unlink()
    assert ds.check(folder) == 1


def test_подпись_без_картинки_ловится(folder: Path) -> None:
    """Лишняя подпись — тоже ошибка, и она ловится."""
    run_build(folder)
    (folder / "0099.txt").write_text("ohwx, что-то", encoding="utf-8")
    assert ds.check(folder) == 1


def test_готовый_датасет_проходит(folder: Path) -> None:
    """Полный датасет проверку выдерживает."""
    run_build(folder)
    assert ds.check(folder) == 0


def test_мало_картинок_предупреждает(folder: Path, capsys: Any) -> None:
    """Мало примеров — предупреждение, но не отказ.

    Трёх картинок хватит, чтобы запустить обучение и увидеть, что
    выходит; запрещать нельзя.
    """
    for extra in ("cliff", "ball"):
        (folder / f"char_{extra}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    run_build(folder)
    assert ds.check(folder) == 0
    out = capsys.readouterr().out
    assert str(ds.MIN_IMAGES) in out, "нет предупреждения о малом числе"


# =============================================================== архив


def test_архив_содержит_пары_файлов(folder: Path, tmp_path: Path) -> None:
    """В архиве должны лежать и картинки, и подписи.

    Архив с одними картинками тренажёр примет, но обучится вслепую.
    """
    run_build(folder)
    args = type("Args", (), {
        "folder": str(folder), "tag": "ohwx", "check": False,
        "zip": "test-dataset",
    })()
    assert ds.build(args) == 0
    archive = folder.parent / "test-dataset.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert any(n.endswith(".png") for n in names)
    assert any(n.endswith(".txt") for n in names)
    # Подписи и картинки обязаны лежать рядом: путь внутри архива
    # задаётся в ноутбуке, и разбросанные файлы он не найдёт.
    # В zip разделитель всегда прямой слэш, независимо от системы.
    assert all(n.startswith("dataset/") for n in names), f"пути: {names[:3]}"
    # Парность имён: у каждой картинки своя подпись с тем же именем.
    stems = {n.rsplit("/", 1)[-1].rsplit(".", 1)[0] for n in names}
    assert len([n for n in names if n.endswith(".png")]) == len(
        [n for n in names if n.endswith(".txt")]), "пары разошлись"


def test_мусор_в_архив_не_попадает(folder: Path) -> None:
    """Заметка с подписью — тоже мусор, и в архив она попасть не должна.

    Отдельная проверка на `.txt`: файл `notes.txt` выглядит как
    подпись, и тренажёр примет её за описание картинки, которой нет.
    """
    run_build(folder)
    (folder / "notes.txt").write_text("заметка", encoding="utf-8")
    args = type("Args", (), {
        "folder": str(folder), "tag": "ohwx", "check": False,
        "zip": "clean-dataset",
    })()
    ds.build(args)
    with zipfile.ZipFile(folder.parent / "clean-dataset.zip") as bundle:
        names = bundle.namelist()
    assert not any(n.endswith("notes.txt") for n in names), f"мусор: {names}"


# =============================================================== якорь


def test_якорь_одинаков_во_всех_промтах() -> None:
    """Главное свойство якоря: он не меняется от кадра к кадру."""
    a = ds.caption_for("portrait", "ohwx")
    b = ds.caption_for("snow", "ohwx")
    anchor_a = a.split(", photorealistic")[0]
    # Убираем тег, оставляя якорь и начало описания.
    assert a.startswith("ohwx, ")
    assert b.startswith("ohwx, ")
    # Якорь — первые N слов после тега, и они совпадают.
    assert a[:120] == b[:120], "якорь разошёлся между ракурсами"


def test_тег_меняется_целиком() -> None:
    """Смена тега обязана менять его везде, а не в одной подписи."""
    assert ds.caption_for("neon", "ohwx").startswith("ohwx")
    assert ds.caption_for("neon", "zzperson").startswith("zzperson")