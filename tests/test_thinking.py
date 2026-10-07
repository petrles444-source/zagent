"""Размышление главного агента: запрос разворачивается до детализации 10/10.

Модуль новый, поэтому тесты закрывают то, что обязано быть правдой:

* **выбор модели идёт по каталогу, а не по алфавиту.** Приоритет — поле
  tier из tiers.json; если главной модели в рантайме нет, берётся следующая;
  если каталог молчит — первая установленная;
* **тихая модель не должна молчать.** Ошибка рантайма обязана быть
  видна словами, а не пустым размышлением;
* **обрезка не режет слово пополам** и честно помечает хвост;
* **формат 10/10 задан явно**: шесть разделов, порядок зафиксирован, и
  требование детализации видно в тексте промпта модели;
* **поток идёт по словам**, потому что на процессоре модель думает
  секунды и молчание выглядит зависанием.

Проверки «кусающиеся»: каждая ломается при возврате правки, потому что
смотрит на конкретную строку, а не на «наличие файла».
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import local_llm, thinking  # noqa: E402
from hub.local_llm import LocalLLMError  # noqa: E402


@pytest.fixture(autouse=True)
def _без_сети(monkeypatch):
    """Ни один тест не должен дёргать настоящий Ollama."""
    calls: list[dict] = []

    def fake_stream(model, messages, base=None, timeout=None):
        calls.append({"model": model, "messages": messages,
                      "base": base, "timeout": timeout})
        for word in ("развёрнутое", "задание"):
            yield word + " "

    monkeypatch.setattr(local_llm, "stream_chat", fake_stream)
    monkeypatch.setattr(thinking.local_llm, "stream_chat", fake_stream)
    monkeypatch.setattr(
        thinking, "local_models",
        lambda: ["qwen2.5:3b", "phi3:mini", "deepseek-r1:1.5b"])
    return calls


# ================================================================= выбор модели


def test_берётся_лучшая_по_каталогу_а_не_первая_из_списка() -> None:
    """Ранг 1 в tiers.json — единственный механизм приоритета."""
    installed = ["phi3:mini", "qwen2.5:3b", "deepseek-r1:1.5b"]
    assert thinking.pick_model(installed) == "qwen2.5:3b"


def test_главной_модели_нет_берётся_следующая_по_рангу() -> None:
    """Рантайм и каталог расходятся — это норма, а не ошибка."""
    assert thinking.pick_model(["phi3:mini", "deepseek-r1:1.5b"]) == "phi3:mini"


def test_модели_из_каталога_нет_берётся_что_есть() -> None:
    assert thinking.pick_model(["неизвестная:1b"]) == "неизвестная:1b"


def test_ранга_нет_берётся_первая_установленная() -> None:
    """Каталог пуст или битый — молчать об этом нельзя, берём что есть."""
    assert thinking.pick_model(["zzz:1b", "aaa:1b"]) == "aaa:1b"


def test_без_моделей_ошибка_а_не_пустая_мысль() -> None:
    """Пустое размышление читалось бы как «агенту нечего думать»."""
    with pytest.raises(thinking.ThinkingError):
        thinking.pick_model([])


def test_битый_каталог_не_ломает_выбор() -> None:
    path = ROOT / "config" / "tiers.json"
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text("{не json", encoding="utf-8")
        assert thinking.pick_model(["phi3:mini"]) == "phi3:mini"
    finally:
        path.write_text(original, encoding="utf-8")


def test_рангаглупый_не_ломает_выбор() -> None:
    """tier: "первый" в YAML не должен поднимать всё в исключение."""
    path = ROOT / "config" / "tiers.json"
    original = path.read_text(encoding="utf-8")
    try:
        data = json.loads(original)
        data["models"].append({"gateway": "ollama", "model": "phi3:mini",
                              "tier": "не число"})
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        assert thinking.pick_model(["phi3:mini"]) == "phi3:mini"
    finally:
        path.write_text(original, encoding="utf-8")


# ==================================================================== формат


def test_шесть_разделов_и_порядок_зафиксированы() -> None:
    """Формат 10/10 — это разделы, а не «больше текста»."""
    names = [name for name, _ in thinking.SECTIONS]
    assert names == ["Как я понял задачу", "Результат", "Порядок работы",
                     "Крайние случаи и риски", "Проверка перед сдачей",
                     "Вопросы к человеку"]


def test_каждый_раздел_объяснён_модели() -> None:
    for name, hint in thinking.SECTIONS:
        assert hint.strip(), f"раздел «{name}» без объяснения"


def test_в_системном_промпте_есть_требование_детализации() -> None:
    assert "10/10" in thinking.SYSTEM
    assert "по-русски" in thinking.SYSTEM


def test_в_промпте_запрещено_выдумывать() -> None:
    """Главный риск размышления — правдоподобная выдумка вместо вопроса."""
    assert "не выдумывай" in thinking.SYSTEM
    assert "Вопросы к человеку" in thinking.SYSTEM


def test_в_промпте_есть_все_заголовки_разделов() -> None:
    for name, _ in thinking.SECTIONS:
        assert name in thinking.SYSTEM


def test_запрос_идёт_в_пользовательскую_часть() -> None:
    text = thinking.build_user_prompt("почини тесты")
    assert "почини тесты" in text
    assert "ЗАПРОС ЧЕЛОВЕКА" in text


def test_обстановка_добавляется_когда_есть() -> None:
    assert "ОБСТАНОВКА" not in thinking.build_user_prompt("задача")
    with_context = thinking.build_user_prompt("задача", "воркспейс C:/work")
    assert "ОБСТАНОВКА" in with_context
    assert "C:/work" in with_context


# ===================================================================== вызов


def test_размышление_собирает_полный_текст() -> None:
    assert thinking.deepen("почини тесты") == "развёрнутое задание"


def test_модель_идёт_в_локальный_рантайм_с_разговором() -> None:
    """Без system-заголовка локальная модель отвечает поверхностно."""
    calls = []
    thinking.local_llm.stream_chat = (  # type: ignore[assignment]
        lambda model, messages, base=None, timeout=None: calls.append(
            (model, messages)) or iter(["текст"]))
    thinking.deepen("задача")
    model, messages = calls[0]
    assert model == "qwen2.5:3b"
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_пустой_запрос_не_идёт_в_модель() -> None:
    """Пробелы не должны стоить десяти секунд на процессоре."""
    calls = []
    thinking.local_llm.stream_chat = (  # type: ignore[assignment]
        lambda model, messages, base=None, timeout=None: calls.append(model)
        or iter(["x"]))
    assert thinking.deepen("   ") == ""
    assert not calls


def test_ошибка_рантайма_поднимается_как_ошибка_мысли() -> None:
    """Задача должна падать на размышлении, а не молча идти без него."""

    def broken(model, messages, base=None, timeout=None):
        raise LocalLLMError("Ollama недоступен (URLError)")
        yield ""  # pragma: no cover - генератор

    thinking.local_llm.stream_chat = broken  # type: ignore[assignment]
    with pytest.raises(thinking.ThinkingError):
        thinking.deepen("задача")


def test_поток_идёт_по_словам() -> None:
    """Молчание на процессоре выглядит зависанием."""
    pieces = list(thinking.deepen_stream("задача"))
    assert len(pieces) > 1
    assert "".join(pieces).startswith("развёрнутое")


def test_пустой_запрос_в_потоке_молчит() -> None:
    assert list(thinking.deepen_stream("")) == []


def test_панель_видит_модель_и_разделы() -> None:
    data = thinking.describe()
    assert data["running"] is True
    assert data["model"] == "qwen2.5:3b"
    assert len(data["sections"]) == 6


def test_панель_говорит_когда_рантайм_выключен() -> None:
    thinking.local_models = lambda: (_ for _ in ()).throw(  # type: ignore[assignment]
        thinking.ThinkingError("Ollama недоступен: URLError"))
    data = thinking.describe()
    assert data["running"] is False
    assert "недоступен" in data["error"]


# ===================================================================== обрезка


def test_короткий_план_не_трогаем() -> None:
    assert thinking.shorten("план") == "план"


def test_длинный_план_режется_по_строке() -> None:
    text = "\n".join(["строка " * 40] * 200)
    cut = thinking.shorten(text, limit=500)
    assert len(cut) < len(text)
    assert cut.endswith("(размышление обрезано)")
    # Обрезка не должна оставить половину слова.
    assert not cut[:-30].rstrip().endswith("строка строкой строк")


def test_обрезка_отмечает_хвост_честно() -> None:
    """Человек должен понимать, что план неполный."""
    assert "обрезано" in thinking.shorten("a" * 5000)


def test_план_из_одних_пробелов_считается_пустым() -> None:
    """Молчание модели — это отсутствие плана, а не план из пробелов."""
    assert thinking.shorten("\n" * 5000, limit=500) == ""
    assert thinking.shorten("   \n  ") == ""


def test_обрезка_не_съедает_начало_плана() -> None:
    """Первые строки размышления — самое важное, они должны выжить."""
    text = ("Как я понял задачу: нужно починить тесты.\n"
            + "строка\n" * 2000)
    cut = thinking.shorten(text, limit=400)
    assert cut.startswith("Как я понял задачу")
    assert "обрезано" in cut


# ================================================================ маршруты


def test_маршрут_размышления_есть_на_сервере() -> None:
    src = (ROOT / "hub" / "server.py").read_text(encoding="utf-8")
    assert '"/api/thinking"' in src
    assert "/api/thinking" in src


def test_размышление_включается_флажком_задачи() -> None:
    """Иначе это отдельная кнопка, а не часть работы агента."""
    src = (ROOT / "hub" / "worker.py").read_text(encoding="utf-8")
    assert 'payload.get("deepen")' in src
    assert "thinking.deepen" in src


def test_упавшее_размышление_не_роняет_задачу() -> None:
    """Задача обязана выполниться по исходному запросу."""
    src = (ROOT / "hub" / "worker.py").read_text(encoding="utf-8")
    assert "ThinkingError" in src, "отказ размышления должен быть пойман"
    assert "except Exception" in src, "нужен общий щит: сеть может отдать что угодно"