"""Голос статуса — идея из update/creativeupdate-07-10-26.txt.

Функции вырезаются из интерфейса и выполняются в node со стабами:
так проверяется не «строка где-то есть», а поведение — молчит ли голос
при выключенном флаге и не падает ли без синтеза речи. Для этого
нужен node — как и для tools/check_ui.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

UI_PATH = Path(__file__).resolve().parent.parent / "hub" / "ui.py"
UI = UI_PATH.read_text(encoding="utf-8")

node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node не установлен")


def extract(name: str) -> str:
    """Вырезать функцию из интерфейса по имени, со всеми скобками."""
    start = UI.index(f"function {name}(")
    depth = 0
    for i in range(start, len(UI)):
        if UI[i] == "{":
            depth += 1
        elif UI[i] == "}":
            depth -= 1
            if depth == 0:
                return UI[start:i + 1]
    raise AssertionError(f"функция {name} не закрылась")


def run(body: str, *, voice: str, synth: bool = True,
        tmp_path: Path | None = None) -> dict:
    """Выполнить кусок JS в node и вернуть JSON-отчёт.

    `voice` — содержимое флага zagent.voice, `synth` — есть ли в
    браузере синтез речи (бывает и нет).
    """
    assert node, "node не установлен"
    # В браузере window.X и X — одно и то же, в node нет: без второй
    # пары строк голос молча ловил бы ReferenceError в своей же catch.
    window_lines = (
        ["global.window = {};"] if not synth else [
            "global.window = {",
            "  speechSynthesis: {speak: u => report.speaks.push("
            "{text: u.text, lang: u.lang})},",
            "  SpeechSynthesisUtterance: class { constructor(t) "
            "{ this.text = t; } },",
            "};",
            "global.speechSynthesis = window.speechSynthesis;",
            "global.SpeechSynthesisUtterance = window.SpeechSynthesisUtterance;",
        ]
    )
    script = "\n".join([
        "const report = {speaks: [], thrown: null, btn: null, stored: null};",
        f"const store = {{'zagent.voice': {json.dumps(voice)}}};",
        "global.localStorage = {",
        "  getItem: k => (k in store ? store[k] : null),",
        "  setItem: (k, v) => { store[k] = String(v); },",
        "};",
        "const btn = {textContent: ''};",
        "const $ = () => btn;",
        *window_lines,
        extract("voiceSay"),
        extract("voiceToggle"),
        extract("renderVoiceBtn"),
        body,
        "report.stored = localStorage.getItem('zagent.voice');",
        "report.btn = btn.textContent;",
        "process.stdout.write(JSON.stringify(report));",
    ])
    path = (tmp_path or Path(__file__).parent) / "voice_run.js"
    path.write_text(script, encoding="utf-8")
    proc = subprocess.run([node, str(path)], capture_output=True, text=True,
                          encoding="utf-8")
    path.unlink(missing_ok=True)
    assert proc.returncode == 0, f"node упал: {proc.stderr}"
    return json.loads(proc.stdout)


def test_выключенный_голос_молчит(tmp_path: Path) -> None:
    report = run("voiceSay('Задача выполнена');", voice="off", tmp_path=tmp_path)
    assert report["speaks"] == [], "голос прозвучал при выключенном флаге"
    assert report["thrown"] is None


def test_включенный_голос_произносит_и_на_русском(tmp_path: Path) -> None:
    report = run("voiceSay('Задача выполнена');", voice="on", tmp_path=tmp_path)
    assert report["speaks"] == [{"text": "Задача выполнена", "lang": "ru-RU"}]


def test_без_синтеза_речи_голос_не_падает(tmp_path: Path) -> None:
    """speechSynthesis есть не везде — его отсутствие не должно ронять
    обработчик события, который этот голос вызывает."""
    report = run(
        "try { voiceSay('проверка'); } catch (e) { report.thrown = String(e); }",
        voice="on", synth=False, tmp_path=tmp_path,
    )
    assert report["thrown"] is None
    assert report["speaks"] == []


def test_переключатель_хранится_и_подписывает_кнопку(tmp_path: Path) -> None:
    off = run("voiceToggle();", voice="off", tmp_path=tmp_path)
    assert off["stored"] == "on"
    assert "вкл" in off["btn"]
    assert off["speaks"], "после включения голос должен сказать, что включён"

    on = run("voiceToggle();", voice="on", tmp_path=tmp_path)
    assert on["stored"] == "off"
    assert "выкл" in on["btn"]
    assert on["speaks"] == [], "после выключения говорить нечего"


def test_голос_зовётся_в_конце_задачи() -> None:
    """Именно эти две фразы: остальное — детали, ради них и затевался голос."""
    assert "voiceSay('Задача выполнена')" in UI
    assert "voiceSay('Задача не удалась')" in UI
    # Без переключателя голос был бы всегда включён либо навсегда выключен —
    # то есть его как не было бы.
    assert "function voiceToggle" in UI
    assert "'zagent.voice'" in UI
    assert 'id="voiceBtn"' in UI
    assert "renderVoiceBtn();" in UI, "кнопка не обновляется при загрузке"
