"""Фабрика telegram-ботов: границы, секреты и честность перед человеком."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import telegram  # noqa: E402
from hub.telegram import TelegramError, build_bot, check_model, check_name  # noqa: E402


# ============================================================ имя и модель


def test_имя_латиница_цифры_подчёркивание() -> None:
    assert check_name("my_helper") == "my_helper"
    assert check_name("Bot2026") == "Bot2026"


def test_имя_не_проходит_с_кириллицей() -> None:
    """Имя становится папкой, а Telegram допускает только латиницу."""
    for bad in ("помощник", "my helper", "ab", "a" * 40, "../escape"):
        try:
            check_name(bad)
        except TelegramError:
            continue
        raise AssertionError(f"имя {bad!r} должно отвергаться")


def test_локальная_модель_проходит() -> None:
    """Раньше валидатор требовал вид «имя шлюза» и отвергал qwen2.5:3b."""
    assert check_model("qwen2.5:3b") == "qwen2.5:3b"
    assert check_model("openrouter") == "openrouter"


def test_мусор_в_имени_модели() -> None:
    for bad in ("", "  ", "модель", "a b", "../x"):
        try:
            check_model(bad)
        except TelegramError:
            continue
        raise AssertionError(f"модель {bad!r} должна отвергаться")


def test_шлюз_от_личается_от_локальной_модели() -> None:
    assert telegram.model_is_gateway("openrouter") is True
    assert telegram.model_is_gateway("qwen2.5:3b") is False


def test_у_локальной_модели_ключа_не_ищется(monkeypatch) -> None:
    """Про локальную модель шлюзовую конфигурацию не спрашивают вовсе.

    Проверка подменой, а не сравнением результата: раньше тест сравнивал с
    False и проходил даже когда фабрика честно пыталась искать ключ -
    resolve_keys("qwen2.5:3b") возвращает пусто, и вывод совпадал.
    """
    def boom(*args, **kwargs):
        raise AssertionError("шлюзовые ключи не ищутся для локальной модели")

    monkeypatch.setattr(telegram, "resolve_keys", boom)
    assert telegram.has_key("qwen2.5:3b", root=tmp_root()) is False


def tmp_root() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp())


# =============================================================== сборка


def test_сборка_создаёт_три_файла(tmp_path: Path) -> None:
    info = build_bot("my_helper", title="Помощник", root=tmp_path)
    target = Path(info["dir"])
    assert info["ok"] is True
    for name in ("bot.py", "config.json", "README.md"):
        assert (target / name).is_file(), f"нет {name}"


def build_with_token(tmp_path: Path) -> None:
    """Собрать бота, в чей шаблон подмешан токен телеграма."""
    original = telegram.BOT_TEMPLATE
    telegram.BOT_TEMPLATE = original + '\nTOKEN = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"\n'
    try:
        build_bot("sneaky", root=tmp_path)
    finally:
        telegram.BOT_TEMPLATE = original


def test_токен_телеграма_тоже_запрещён(tmp_path: Path) -> None:
    """Токен бота утекает чаще ключей ИИ, и подстрокой его не поймать."""
    try:
        build_with_token(tmp_path)
    except TelegramError as exc:
        assert "токен" in str(exc).lower()
    else:
        raise AssertionError("сборка с токеном в коде должна отвергаться")


def test_в_коде_бота_нет_секретов(tmp_path: Path) -> None:
    """Ключ в коде уехал бы вместе с ботом и заблокировал бы коммит."""
    info = build_bot("my_helper", root=tmp_path)
    target = Path(info["dir"])
    for path in target.iterdir():
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        assert "sk-" not in body, f"похоже на ключ в {path.name}"
        assert "api_key" not in body, f"ключ прокрался в {path.name}"


def test_токен_не_вписывается_в_конфиг(tmp_path: Path) -> None:
    info = build_bot("my_helper", root=tmp_path)
    cfg = json.loads((Path(info["dir"]) / "config.json").read_text("utf-8"))
    assert cfg["token"] == "", "токен должен остаться заполняемым человеком"


def test_повторная_сборка_требует_force(tmp_path: Path) -> None:
    build_bot("my_helper", root=tmp_path)
    try:
        build_bot("my_helper", root=tmp_path)
    except TelegramError as exc:
        assert "force" in str(exc)
    else:
        raise AssertionError("повтор должен требовать явного согласия")
    # С force - перезаписывает.
    assert build_bot("my_helper", root=tmp_path, force=True)["ok"] is True


def test_сломанная_модель_не_оставляет_папку(tmp_path: Path) -> None:
    """Проверка должна быть ДО записи, иначе остаётся полубот."""
    try:
        build_bot("my_helper", model="плохая модель", root=tmp_path)
    except TelegramError:
        pass
    assert not (tmp_path / "projects" / "telegram-bots" / "my_helper").exists(), (
        "папка создана до проверки - остался наполовину собранный бот")


def test_имя_не_уходит_за_пределы_папки(tmp_path: Path) -> None:
    """Имя становится папкой: `..` в него пробраться не должно."""
    try:
        build_bot("../../escape", root=tmp_path)
    except TelegramError:
        return
    raise AssertionError("имя с путём должно отвергаться")


# ==================================================== честность перед человеком


def test_сборка_говорит_что_осталось_человеку(tmp_path: Path) -> None:
    """Без этого агент объявит задачу выполненной, а токена нет."""
    info = build_bot("my_helper", root=tmp_path)
    assert info["human_steps"], "шаги человека не перечислены"
    joined = " ".join(info["human_steps"]).lower()
    assert "botfather" in joined, "не сказано, что нужен @BotFather"


def test_в_readme_есть_граница_возможностей(tmp_path: Path) -> None:
    info = build_bot("my_helper", root=tmp_path)
    readme = (Path(info["dir"]) / "README.md").read_text("utf-8")
    assert "BotFather" in readme
    assert "нет" in readme.lower() or "не умеет" in readme.lower()


def test_в_коде_сказано_что_ключей_нет(tmp_path: Path) -> None:
    """Человек должен понимать, отдавать ли этот файл кому-то."""
    info = build_bot("my_helper", root=tmp_path)
    bot = (Path(info["dir"]) / "bot.py").read_text("utf-8")
    assert "секретов в нём нет" in bot.lower() or "НЕ хранятся" in bot


# ======================================================== список и статус


def test_список_пуст_без_ботов(tmp_path: Path) -> None:
    assert telegram.list_bots(root=tmp_path) == []


def test_список_показывает_факт_а_не_токен(tmp_path: Path) -> None:
    info = build_bot("my_helper", root=tmp_path)
    Path(info["dir"], "config.json").write_text(
        json.dumps({"token": "123456:secret-value", "model": "qwen2.5:3b"}),
        encoding="utf-8")
    rows = telegram.list_bots(root=tmp_path)
    assert rows[0]["token_set"] is True
    assert "secret-value" not in json.dumps(rows, ensure_ascii=False)


def test_статус_без_токена_честен(tmp_path: Path) -> None:
    build_bot("my_helper", root=tmp_path)
    info = telegram.status("my_helper", root=tmp_path)
    assert info["built"] is True
    assert info["telegram_ok"] if "telegram_ok" in info else True
    assert "BotFather" in info.get("error", "") or info.get("token_set") is False


def test_статус_не_собранного_бота() -> None:
    info = telegram.status("no_such_bot", root=tmp_root())
    assert info["built"] is False
    assert info["ok"] is False


# ================================================================== API


def test_без_токена_api_не_зовётся() -> None:
    """Пустой токен - это отсутствие данных, а не запрос в сеть."""
    try:
        telegram.get_me("")
    except TelegramError as exc:
        assert "токен" in str(exc).lower()
    else:
        raise AssertionError("пустой токен должен отвергаться")


def test_план_разделяет_агента_и_человека() -> None:
    """Ровно то, ради чего эта утила: агент знает свою границу."""
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tgbot_cli", ROOT / "tools" / "tgbot.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    import argparse

    args = argparse.Namespace(name="my_helper", model="qwen2.5:3b",
                              root=tmp_root(), func=module.cmd_plan)
    assert module.cmd_plan(args) == 0


def test_план_в_файле_есть() -> None:
    plan = ROOT / "update" / "telegram-bot-factory.md"
    assert plan.is_file(), "плана нет - работать будет нечем"
    body = plan.read_text("utf-8")
    assert "BotFather" in body
    assert "микро-задачи" in body.lower() or "Микро-задачи" in body