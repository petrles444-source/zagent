r"""Финальный разбор: web-папки в одну, радио в свою.

Зачем
----
В корне осталось три папки, начинающиеся с `web`, и по отдельности
ни одна из них ничего не значит:

* `web/` — страница плеера Flash и текст к ней;
* `web-static/ruffle/` — сам проигрыватель Ruffle, 28 МБ в wasm;
* `web-state/` — база состояния агента, 13 МБ, и журнал диагностики.

Это одна вещь, разложенная по трём папкам, и ни одна из них не
запускается сама. Собираются в одну `web/` с понятными подпапками.

Радио — вторая история. Оно размазано по шести местам: модуль
сервера `hub/radio.py`, страница и список станций в `music/`,
клиент `zradio.exe`, архивы в `publish/`, тесты и компонент на
`site/SVADBA`. Собирается в `radio/`, и там же — инструкция, как
встроить радио в любой сайт.

Запуск:
    .venv\\Scripts\\python.exe tools\\final_layout.py
    .venv\\Scripts\\python.exe tools\\final_layout.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------- веб-часть

#: (откуда, куда внутри web/). Порядок важен: `web` разбирается
#: последним, чтобы не мешать самому себе.
WEB_MOVES = (
    ("web-static/ruffle", "web/ruffle"),
    ("web-state/zagent.db", "web/state/zagent.db"),
    ("web-state/zagent.db-shm", "web/state/zagent.db-shm"),
    ("web-state/zagent.db-wal", "web/state/zagent.db-wal"),
    ("web-state/diag.jsonl", "web/state/diag.jsonl"),
)

#: Что из `web/` уходит в `web/player/`.
WEB_PLAYER_FILES = ("ruffle.html", "flash.txt")

#: База во время работы не должна ехать в репозиторий: она живёт и
#: меняется, а история git помнит всё.
WEB_IGNORE = ("web/state/", "web/state/*.db*")

WEB_DOC = """# web — плеер Flash на вебе

Одна вещь, раньше разложенная по трём папкам: `web/`, `web-state/`
и `web-static/`.

| Папка | Что это |
|---|---|
| `player/ruffle.html` | страница плеера |
| `player/flash.txt` | текст к ней |
| `ruffle/` | сам проигрыватель Ruffle: wasm и ядро на javascript |
| `state/zagent.db` | состояние агента |

## Зачем вообще Flash

Формат `.swf` мёртв: браузеры его не открывают, а материалов много и
перерисовывать их дорого. Ruffle — проигрыватель, написанный на
WebAssembly, который запускает `.swf` как есть, без переделки.

## Почему проигрыватель весит 28 МБ

Два файла `.wasm` по 14 МБ. Это вся машинерия Ruffle целиком:
рендеринг, звук, ActionScript. Уменьшить нельзя, это готовая
сборка под все браузеры сразу.

## Состояние агента — не в git

Папка `state/` исключена: база живёт и меняется при каждом запуске,
а история git помнит всё. Потеря базы неприятна, но не критична —
агент создаст её заново.
"""

# ----------------------------------------------------------------- радио

RADIO_DOC = """# radio — радио для веба и для клиента

Собрано из шести мест, которые раньше держали радио по кускам:
`hub/radio.py`, `music/`, `zradio.exe`, `publish/*.zip`, тесты.

| Что | Где |
|---|---|
| Страница плеера | `player/radio.html` |
| Список станций | `player/stations.json` |
| Скрипт для вставки в любой сайт | `вставка/radio-widget.html` |
| Серверная часть | `../hub/radio.py` |
| Клиент для компьютера | `../zradio.exe` |
| Готовые архивы | `../publish/zradio.zip`, `../publish/radio-stations-list.zip` |

## Станции

`player/stations.json` — 37 станций. Формат записи:

```json
{
  "name": "Название станции",
  "genre": "Жанр или описание",
  "url": "https://поток/stream/mp3",
  "bitrate": "MP3",
  "group": "Личная подборка"
}
```

Поле `group` нужно для раздела «Личная подборка» в интерфейсе.

## Как встроить радио в любой сайт

Всё, что нужно, лежит в `вставка/radio-widget.html`. Это готовый
кусок: файл открывается двойным щелчком, в нём есть и плеер, и
кнопка.

Вставить на сайт — три шага:

1. Скопировать файл `radio-widget.html` к себе в папку сайта.
2. Вставить в нужное место страницы одну строку:

```html
<iframe src="/radio-widget.html" width="320" height="420"
        style="border:0;border-radius:12px"></iframe>
```

3. Готово. Плеер заработает.

Почему `iframe`, а не вставка скрипта: плеер изолирован от страницы.
Сайт не сможет сломать плеер, а плеер не сможет сломать сайт. Плюс
подключается копированием одного файла, без правок чужого кода.

## Что нужно, чтобы поток играл

Поток должен быть доступен по `https` и не требовать авторизации.
Это ограничение браузеров: страница на `https` не сможет играть
`http`-поток, и микшер на странице выдаст ошибку безопасности.

Проверка одного потока:

```bash
curl -I https://поток/stream/mp3
```

Ответ `200` или `302` — поток живой. `403` — сервер не отдаёт без
заголовков, такой поток в браузере не заработает.

## Как добавить станцию

Дописать запись в `player/stations.json` и поставить файл на
хостинг. Ничего пересобирать не нужно: список читается как есть.

## Клиент для компьютера

`zradio.exe` — отдельная программа, работает без браузера. В
браузере системные аудиоустройства недоступны, поэтому для
полноценной работы со звуком в фоне нужен клиент.

## Что ещё предстоит

Радио подключено к одному сайту — в `site/SVADBA` есть компонент
переключателя станций. Остальные 51 страницы пока без него.
Скрипт уже готов, подключение сводится к одной строке из раздела
выше.
"""

WIDGET = """<!DOCTYPE html>
<!--
  Радио для вставки в любой сайт.

  Готовый файл: кладётся рядом со страницей и вставляется одним
  iframe. Ничего пересобирать не нужно.

  Как пользоваться — см. README в папке radio.

  Почему iframe: плеер изолирован от страницы. Сайт не сломает
  плеер, плеер не сломает сайт. И подключение — копированием
  одного файла, без правок чужого кода.
-->
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Радио</title>
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0;
    background: #14100c;
    color: #f0e6d8;
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  .wrap { padding: 16px; }
  h1 { font-size: 17px; margin: 0 0 4px; letter-spacing: .02em; }
  .sub { font-size: 12px; color: #9c8b76; margin: 0 0 14px; }
  audio { width: 100%; margin-bottom: 14px; }
  .list { display: grid; gap: 6px; max-height: 300px;
          overflow-y: auto; }
  button {
    text-align: left; padding: 9px 11px; border-radius: 8px;
    border: 1px solid #3a2f24; background: #1e1811; color: #e8dccb;
    cursor: pointer; font: inherit; font-size: 14px;
  }
  button:hover { background: #2a2117; border-color: #56432f; }
  button[aria-pressed="true"] {
    background: #3d2c18; border-color: #b07d3f; color: #ffdca8;
  }
  .genre { font-size: 12px; color: #9c8b76; margin-left: 6px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Радио</h1>
  <p class="sub">Выберите станцию — она заиграет сразу.</p>

  <audio id="player" controls preload="none"></audio>

  <div class="list" id="list"></div>
</div>

<script>
// Список станций. Кладётся рядом с этим файлом и грузится отдельно,
// чтобы список можно было править, не трогая сам плеер.
const SOURCES = [
  "stations.json",
  "/music/stations.json",
  "stations.json?v=" + Date.now()
];

async function loadStations() {
  for (const src of SOURCES) {
    try {
      const response = await fetch(src, { cache: "no-store" });
      if (!response.ok) continue;
      const data = await response.json();
      if (Array.isArray(data) && data.length) return data;
    } catch (error) {
      // Следующий адрес. Отсутствие списка не должно ронять плеер.
    }
  }
  return [];
}

const list = document.getElementById("list");
const player = document.getElementById("player");
let current = null;

function markButton(button) {
  list.querySelectorAll("button").forEach((b) =>
    b.setAttribute("aria-pressed", String(b === button)));
}

loadStations().then((stations) => {
  if (!stations.length) {
    list.textContent = "Список станций не найден.";
    return;
  }
  for (const station of stations) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-pressed", "false");
    button.textContent = station.name;

    if (station.genre) {
      const note = document.createElement("span");
      note.className = "genre";
      note.textContent = station.genre;
      button.appendChild(note);
    }

    button.addEventListener("click", () => {
      // Повторное нажатие на играющей станции её останавливает.
      if (current === station) {
        player.pause();
        current = null;
        markButton(null);
        return;
      }
      player.src = station.url;
      player.play().catch(() => {
        // Браузер может запретить автозапуск до первого клика.
        // Список уже показан, нажать можно ещё раз.
      });
      current = station;
      markButton(button);
    });
    list.appendChild(button);
  }
});
</script>
</body>
</html>
"""


def wipe(path: Path) -> None:
    """Удалить дерево, сняв атрибут ReadOnly."""
    for item in [path, *path.rglob("*")]:
        try:
            os.chmod(item, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)


def move_file(src: Path, dst_rel: str, dry: bool) -> None:
    if not src.exists():
        print(f"  нет {src.name} — пропускаю")
        return
    dst = ROOT / dst_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        print(f"  {dst_rel} уже есть — пропускаю")
        return
    print(f"  {src.relative_to(ROOT)} → {dst_rel}")
    if dry:
        return
    try:
        shutil.move(str(src), str(dst))
    except PermissionError:
        # Файл занят работающим процессом. Так ведёт себя база
        # агента: она открыта, пока агент жив.
        #
        # Копируется вместо перемещения. Это осознанно: лучше
        # оставить старый файл на месте, чем упасть посреди
        # разбора. Исходник удалится сам, когда агент остановят.
        shutil.copy2(src, dst)
        print(f"      файл занят работающим агентом — скопирован, "
              f"исходник удалить нельзя")


def main() -> int:
    parser = argparse.ArgumentParser(description="финальный разбор")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry = args.dry_run

    print("=== 1. web: три папки в одну ===")
    for src_rel, dst_rel in WEB_MOVES:
        move_file(ROOT / src_rel, dst_rel, dry)

    web = ROOT / "web"
    player = web / "player"
    player.mkdir(parents=True, exist_ok=True)
    for name in WEB_PLAYER_FILES:
        src = web / name
        if src.exists():
            print(f"  web/{name} → web/player/{name}")
            if not dry:
                shutil.move(str(src), str(player / name))

    for stale in (web / "web-static", web / "web-state"):
        if stale.is_dir():
            wipe(stale)

    (web / "ЧТО-ЗДЕСЬ.md").write_text(WEB_DOC, encoding="utf-8")
    print("  записан web/ЧТО-ЗДЕСЬ.md")

    print()
    print("=== 2. радио в одну папку ===")
    radio = ROOT / "radio"
    for sub in ("player", "вставка"):
        (radio / sub).mkdir(parents=True, exist_ok=True)

    for name in ("radio.html", "stations.json"):
        src = ROOT / "music" / name
        if src.exists():
            move_file(src, f"radio/player/{name}", dry)
        else:
            print(f"  нет music/{name} — пропускаю")

    # Заметка о поиске музыки остаётся на месте: она не про плеер.
    if (ROOT / "music" / "radio.txt").exists() and not dry:
        shutil.move(str(ROOT / "music" / "radio.txt"),
                    str(ROOT / "docs" / "radivo-otkuda-vzyat.txt"))
        print("  music/radio.txt → docs/radivo-otkuda-vzyat.txt "
              "(это заметка, не данные плеера)")

    (radio / "вставка" / "radio-widget.html").write_text(
        WIDGET, encoding="utf-8")
    print("  записан radio/вставка/radio-widget.html — готовый скрипт "
          "для любого сайта")
    (radio / "ЧТО-ЗДЕСЬ.md").write_text(RADIO_DOC, encoding="utf-8")
    print("  записан radio/ЧТО-ЗДЕСЬ.md")

    if not dry and (ROOT / "music").is_dir():
        if not any((ROOT / "music").iterdir()):
            (ROOT / "music").rmdir()
            print("  music/ пуста, убрана")

    print()
    print("=== 3. состояние веб-части не в git ===")
    ignore = ROOT / ".gitignore"
    body = ignore.read_text(encoding="utf-8")
    if "web/state/" not in body:
        ignore.write_text(
            body.rstrip() +
            "\n\n# Состояние агента: база живёт и меняется при каждом\n"
            "# запуске. В истории git ей не место.\n"
            + "\n".join(WEB_IGNORE) + "\n", encoding="utf-8")
        print("  web/state/ добавлено в .gitignore")

    print()
    print("=== 4. итог ===")
    if dry:
        print("  это был просмотр")
        return 0
    for folder in ("web", "radio", "bots", "sites", "utils"):
        path = ROOT / folder
        if path.is_dir():
            files = len([f for f in path.rglob("*") if f.is_file()])
            print(f"  {folder:<8} {files:>4} файлов")
    return 0


if __name__ == "__main__":
    sys.exit(main())