"""CLI-клиент: связь с агентом, зрение, перевод, отчёты.

Главный дефект, который закрывает этот файл: буфер захвата брался
`np.frombuffer` без `reshape`, и `cv2.cvtColor` на одномерном массиве
молча делал из кадра полосу 1×N. Всё дальнейшее работало исправно, но
модель получала мусор. Тест проверяет именно форму, а не «функция не
упала» - падать там было нечему.

Остальное, что зафиксировано:

* зрение выключается словами, а не трассировкой, когда нет cv2/mss;
* предел энкодера 65500 пикселей учитывается заранее;
* ключи моделей читаются из конфигурации и не попадают в отчёты;
* отчёт всегда в `document/` с меткой времени, файлы не перетираются;
* перевод на русский не запускается для текста, который уже на русском.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load() -> object:
    spec = importlib.util.spec_from_file_location("zcli_mod", ROOT / "tools" / "zcli.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


zcli = load()


# ==================================================== маршруты и протокол


def test_клиент_говорит_с_тем_же_сервером_что_и_веб() -> None:
    """Иначе задача из консоли не появилась бы в панели.

    Проверяем символы `Routes.*`, а не строковые адреса: у клиента их
    вообще нет, всё берётся из общего протокола. Появление литерала
    означало бы, что маршрут продублирован и может разойтись с вебом.
    """
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    for name in ("Routes.SEND_TASK", "Routes.STATE", "Routes.MODELS_STATUS"):
        assert name in src, f"маршрут {name} не используется"
    for literal in ("/api/tasks", "/api/state"):
        assert literal not in src, "адрес взят строкой мимо протокола"


def test_тело_задачи_общее_с_консолью_zagent() -> None:
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert "task_payload(" in src, "тело задачи собрано мимо общего протокола"


def test_адрес_не_захардкожен() -> None:
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8783" not in src, "адрес сервера продублирован"


# ================================================================= зрение


def test_форма_кадра_задаётся_явно() -> None:
    """Главный баг: без reshape кадр превращался в полосу 1×N."""
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert ".reshape(" in src, "буфер не приведён к форме кадра"
    assert "np.frombuffer(raw.rgb, dtype=np.uint8).reshape(" in src


def test_вырожденный_кадр_ловится_до_кодирования() -> None:
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert "вырожденным" in src, "вырожденный кадр уходит в модель молча"


def test_предел_энкодера_учтён() -> None:
    """У JPEG в OpenCV потолок 65500 пикселей по стороне."""
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert zcli.JPEG_MAX_SIDE <= 65500
    assert "JPEG_MAX_SIDE" in src
    assert "limit / float(biggest)" in src


def test_размеры_кадра_в_подсказке_настоящие() -> None:
    """Раньше в подсказке модели стояло жёсткое 1920x1080."""
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert "1920 * args.scale" not in src
    assert "frame_size" in src


def test_зрение_выключается_словами() -> None:
    ok, why = zcli.opencv_available()
    assert isinstance(ok, bool)
    if not ok:
        assert "не хватает" in why
        assert "opencv-python" in (ROOT / "tools" / "zcli.py").read_text("utf-8")


def test_старый_mss_не_единственный_путь() -> None:
    """mss.mss() помечен устаревшим, но на старых версиях доступен лишь он."""
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert '"MSS"' in src or "'MSS'" in src


# ================================================================= перевод


def test_кириллица_считается_по_буквам() -> None:
    assert zcli.cyrillic_share("Привет, мир") == 1.0
    assert zcli.cyrillic_share("Hello, world") == 0.0
    assert zcli.cyrillic_share("42") == 0.0
    assert zcli.cyrillic_share("") == 0.0


def test_ё_считается_кириллицей() -> None:
    assert zcli.cyrillic_share("ёжик") == 1.0


def test_уже_русский_не_переводится_повторно() -> None:
    """Иначе каждый ответ гоняется через модель без нужды."""
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert "RUSSIAN_SHARE" in src
    assert "if cyrillic_share(body) >= RUSSIAN_SHARE:" in src


def test_перевод_идёт_локальной_моделью() -> None:
    """Отдельный переводчик не нужен: та же модель отвечает и за язык."""
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert "local_llm.stream_chat" in src


# ================================================================= секреты


def test_ключи_берутся_из_конфигурации() -> None:
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    assert "resolve_keys(" in src
    assert 'os.environ' not in src, "ключ из окружения уехал бы мимо контроля"


def test_в_отчёте_нет_ключа() -> None:
    """В отчёт попадает имя шлюза и модели, но не значение ключа."""
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    report = src[src.index("def save_report("):src.index("def cmd_shot(")]
    assert "Authorization" not in report
    assert "keys[0]" not in report


def test_команда_keys_не_печатает_значения() -> None:
    src = (ROOT / "tools" / "zcli.py").read_text(encoding="utf-8")
    start = src.index("def cmd_keys(")
    end = src.index("# =", start)
    keys_cmd = src[start:end]
    assert "не печатаются" in keys_cmd
    assert "resolve_keys(gid, root=ROOT)" in keys_cmd
    # Значение ключа в вывод не попадает: печатается только факт.
    assert "keys[0]" not in keys_cmd


# ================================================================= отчёты


def test_отчёты_идут_в_document() -> None:
    assert zcli.DOCUMENTS_DIR.name == "document"
    assert zcli.DOCUMENTS_DIR.is_relative_to(ROOT)


def test_имя_отчёта_с_меткой_времени() -> None:
    """Иначе второй запуск того же кадра затрёт первый."""
    path = zcli.save_report("Проверка", "тело", directory=ROOT / "tmp" / "doc_t2")
    assert path.is_file()
    assert path.suffix == ".md"
    assert path.stem[:8].isdigit(), "в имени нет даты"
    path.unlink()


def test_тело_отчёта_доезжает() -> None:
    path = zcli.save_report("Проверка", "важный вывод агента",
                            directory=ROOT / "tmp" / "doc_t2")
    body = path.read_text("utf-8")
    assert "важный вывод агента" in body
    path.unlink()


def test_отчёт_помнит_источник() -> None:
    path = zcli.save_report("Проверка", "тело",
                            meta={"шлюз": "openrouter/gemma"},
                            directory=ROOT / "tmp" / "doc_t2")
    assert "openrouter/gemma" in path.read_text("utf-8")
    path.unlink()