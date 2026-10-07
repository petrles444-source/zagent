"""Вкладка «Настройки»: писатели ключей и моделей + обработчики сервера.

Здесь проверяется то, что нельзя доверять на слово: файлы конфигурации
меняются из браузера. Отдельно ловится ловушка ручной модели — она молча
выключала бы живой каталог шлюза — и утечка значений в выдачу состояния.
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any

import pytest

from hub.config import (
    ConfigWriteError,
    _default_catalog,
    build_settings,
    edit_gateway_models,
    edit_secret,
    load_gateways,
    load_secrets,
)
from hub.server import ApiServer, Handler
from hub.tiers import TierBook, edit_model

GATEWAYS = {
    "gateways": [
        {
            "id": "openrouter",
            "label": "OpenRouter",
            "base_url": "https://openrouter.ai/api/v1",
            "secret_key": "openrouter",
            "needs_key": True,
            "free_marker": ":free",
        },
        {
            "id": "cloudflare",
            "label": "Cloudflare",
            "base_url": (
                "https://api.cloudflare.com/client/v4/accounts/"
                "{cloudflare_account_id}/ai"
            ),
            "secret_key": "cloudflare_token",
            "needs_key": True,
            "free_models": ["cf/model"],
        },
        {
            "id": "ollama",
            "label": "Ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "secret_key": None,
            "needs_key": False,
        },
        {
            # У zen secret_key: null, а ключ читается legacy-путём под
            # именем zen_api_key — счётчик обязан смотреть туда.
            "id": "zen",
            "label": "Zen",
            "base_url": "https://opencode.ai/zen/v1",
            "secret_key": None,
            "env": "ZEN_API_KEY",
            "needs_key": False,
            "free_models": ["space-bunny-free"],
        },
    ]
}


def make_project(tmp_path: Path) -> Path:
    """Мини-конфигурация: живой каталог, статический список, поле-плейсхолдер."""
    (tmp_path / "config").mkdir(exist_ok=True)
    write = lambda name, data: (  # noqa: E731
        (tmp_path / "config" / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    )
    write("gateways.json", GATEWAYS)
    write("secrets.local.json", {"openrouter": ["k1", "k2"],
                                 "zen_api_key": ["z1", "z2"]})
    write("tiers.json", {"models": [
        {"gateway": "ollama", "model": "m0", "tier": 4},
    ]})
    return tmp_path


class _FakeWorker:
    """Пересборка каталога в тестах не гоняет сеть, но её вызов виден."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.scans = 0

    def scan(self) -> dict[str, Any]:
        self.scans += 1
        return {"ok": True, "models": 0}


def handler_for(tmp_path: Path) -> tuple[Handler, _FakeWorker]:
    worker = _FakeWorker(tmp_path)
    handler = Handler.__new__(Handler)
    handler.api = ApiServer(tmp_path, worker)  # type: ignore[arg-type]
    return handler, worker


# --------------------------------------------------------------- ключи

def test_пакет_ключей_добавляется_с_дедупликацией(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    out = edit_secret("openrouter", "k3\nk4\nk1", action="add", root=root)
    assert out["ok"] is True
    assert out["added"] == 2 and out["duplicates"] == 1
    assert load_secrets(root)["openrouter"] == ["k1", "k2", "k3", "k4"]
    # Ответ уходит в браузер: значений там быть не должно.
    assert "k3" not in json.dumps(out, ensure_ascii=False)


def test_замена_затирает_поле_целиком(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    out = edit_secret("openrouter", "n1\nn2", action="replace", root=root)
    assert out["total"] == 2 and out["was"] == 2
    assert load_secrets(root)["openrouter"] == ["n1", "n2"]


def test_удаление_бросает_только_вставленные(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    out = edit_secret("openrouter", "k1\nнету", action="remove", root=root)
    assert out["ok"] is True and out["removed"] == 1
    assert load_secrets(root)["openrouter"] == ["k2"]

    out = edit_secret("openrouter", "нету", action="remove", root=root)
    assert out["ok"] is False and "не найден" in out["error"]
    assert load_secrets(root)["openrouter"] == ["k2"]


def test_поле_плейсхолдер_хранится_строкой(tmp_path: Path) -> None:
    """Account ID подставляется в URL как str(): список сломал бы base_url."""
    root = make_project(tmp_path)
    edit_secret("cloudflare_account_id", "acct-1", action="replace", root=root)
    assert load_secrets(root)["cloudflare_account_id"] == "acct-1"

    edit_secret("cloudflare_account_id", "acct-2", action="replace", root=root)
    assert load_secrets(root)["cloudflare_account_id"] == "acct-2"

    # Список аккаунтов на плейсхолдере бессмыслен — отклоняем, а не молчим.
    with pytest.raises(ConfigWriteError):
        edit_secret("cloudflare_account_id", "a\nb", action="add", root=root)


@pytest.mark.parametrize("bad, why", [
    ("", "пусто"),
    ("x" * 513, "длинный ключ"),
    ("a\0b", "управляющий символ"),
    ("\n".join(f"k{i}" for i in range(501)), "слишком много"),
])
def test_плохой_ввод_не_пишется(tmp_path: Path, bad: str, why: str) -> None:
    root = make_project(tmp_path)
    before = (root / "config" / "secrets.local.json").read_bytes()
    with pytest.raises(ConfigWriteError):
        edit_secret("openrouter", bad, action="add", root=root)
    assert (root / "config" / "secrets.local.json").read_bytes() == before, why


@pytest.mark.parametrize("name", ["; rm -rf", "../x", "a b", "", "x" * 65])
def test_имя_поля_не_несёт_мусор(tmp_path: Path, name: str) -> None:
    root = make_project(tmp_path)
    with pytest.raises(ConfigWriteError):
        edit_secret(name, "key", action="add", root=root)


# --------------------------------------------------------------- выдача

def test_настройки_не_выдают_значения_ключей() -> None:
    """Настройки уходят в интерфейс целиком: ни одного настоящего ключа."""
    dump = json.dumps(build_settings(), ensure_ascii=False)
    secrets = load_secrets()
    leaked = []
    for value in secrets.values():
        for key in (value if isinstance(value, list) else [value]):
            key = str(key)
            if len(key) >= 8 and key in dump:
                leaked.append(key[:6] + "…")
    assert not leaked, f"в выдачу попали ключи: {leaked}"


def test_настройки_описывают_поля_без_значений(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    out = build_settings(root, env={})
    assert out["ok"] is True
    by_id = {g["id"]: g for g in out["gateways"]}
    assert by_id["openrouter"]["key_field"] == "openrouter"
    assert by_id["openrouter"]["key_count"] == 2
    assert by_id["ollama"]["needs_key"] is False
    # Второй секрет Cloudflare лежит в {placeholder} base_url, а не в полях.
    extras = [e["name"] for e in by_id["cloudflare"]["extra_fields"]]
    assert extras == ["cloudflare_account_id"]
    assert "k1" not in json.dumps(out, ensure_ascii=False)


def test_четыре_состояния_ключа_разведены() -> None:
    """Настоящая конфигурация: поле, литерал, legacy-поле и ключless.

    Одинаковый вид «поле: — · ключей: 1» у всех четырёх вводил человека в
    тупик: непонятно, куда вставлять ключ и нужен ли он вообще.
    """
    out = {g["id"]: g for g in build_settings()["gateways"]}
    # zen: secret_key: null, но ключ читается load_api_key() — поле обязано быть.
    assert out["zen"]["key_field"] == "zen_api_key"
    assert out["zen"]["env_var"] == "ZAGENT_ZEN_API_KEY"
    # ollama: api_key_literal, вводить нечего.
    assert out["ollama"]["key_field"] is None
    assert out["ollama"]["literal"] is True
    # llm7: анонимный доступ.
    assert out["llm7"]["key_field"] is None
    assert out["llm7"]["needs_key"] is False and out["llm7"]["literal"] is False
    # обычный шлюз с полем
    assert out["openrouter"]["literal"] is False
    assert out["openrouter"]["env_var"] == "ZAGENT_OPENROUTER_API_KEY"


# --------------------------------------------------------------- модели

def test_ручная_модель_не_выключает_живой_каталог(tmp_path: Path) -> None:
    """Ловушка: free_models один — _default_catalog() уходит в static.

    То есть без явного catalog первая же ручная модель молча убивает
    живой каталог шлюза (список моделей, который сеть приносит сама).
    Проверяем и саму ловушку, и то, что писатель её обходит.
    """
    root = make_project(tmp_path)
    naive = _default_catalog({"free_models": ["m"], "free_marker": ":free"})
    assert naive == ["static"], "ловушка исчезла — тест перестал кусаться"

    out = edit_gateway_models("openrouter", "deepseek/deepseek-chat-v3:free", root=root)
    assert out["ok"] is True and out["added"] == 1

    gw = next(g for g in load_gateways(root, env={}) if g["id"] == "openrouter")
    assert "live" in gw["catalog"] and "static" in gw["catalog"]
    assert gw["free_models"] == ["deepseek/deepseek-chat-v3:free"]


def test_удаление_ручной_модели_возвращает_живой_каталог(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    edit_gateway_models("openrouter", "a/b", root=root)
    out = edit_gateway_models("openrouter", "a/b", action="remove", root=root)
    assert out["ok"] is True and out["total"] == 0

    out = edit_gateway_models("openrouter", "other/model", action="remove", root=root)
    assert out["ok"] is False and "живой" in out["error"]


def test_неизвестный_шлюз_отклоняется(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    with pytest.raises(ConfigWriteError):
        edit_gateway_models("никакой", "m", root=root)


def test_правка_сохраняет_отступ_файла(tmp_path: Path) -> None:
    """Правка одной строки не должна переформатировать весь файл."""
    root = make_project(tmp_path)
    path = root / "config" / "gateways.json"
    before = path.read_text(encoding="utf-8").splitlines()
    edit_gateway_models("openrouter", "a/b", root=root)
    after = path.read_text(encoding="utf-8").splitlines()
    assert after[1].startswith(" ") and not after[1].startswith("  "), \
        "отступ исходного формата не сохранён"
    changed = list(difflib.unified_diff(before, after, n=0))
    added = [l for l in changed if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in changed if l.startswith("-") and not l.startswith("---")]
    # Единственное «снятое» — строка, получившая запятую перед новым полем.
    assert len(removed) <= 1 and len(added) <= 12, changed


def test_паспорт_пишется_в_tiers_и_виден_книге(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    out = edit_model("openrouter", "a/b", tier=2, notes="вручную", root=root)
    assert out["ok"] is True and out["changed"] == "added"
    assert TierBook.load(root).tier_of("openrouter", "a/b") == 2

    # Без tier ранг достаётся по имени — тот же приём, что у пустой книги.
    out = edit_model("openrouter", "big-400b", root=root)
    assert 1 <= out["tier"] <= 5
    assert TierBook.load(root).tier_of("openrouter", "big-400b") == out["tier"]

    out = edit_model("openrouter", "a/b", action="remove", root=root)
    assert out["ok"] is True
    assert TierBook.load(root).tier_of("openrouter", "a/b") != 2


@pytest.mark.parametrize("tier", ["0", "6", "abc"])
def test_приоритет_только_в_шкале(tmp_path: Path, tier: str) -> None:
    root = make_project(tmp_path)
    with pytest.raises(ConfigWriteError):
        edit_model("openrouter", "a/b", tier=tier, root=root)


# --------------------------------------------------------------- обработчики

def test_обработчик_ключей_пересобирает_каталог(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    handler, worker = handler_for(root)
    out = Handler._keys(handler, {"gateway": "openrouter", "keys": "k3\nk4"})
    assert out["ok"] is True and worker.scans == 1
    assert out["scan"] == {"ok": True, "models": 0}
    assert load_secrets(root)["openrouter"] == ["k1", "k2", "k3", "k4"]


def test_обработчик_ключей_ловит_плохой_ввод(tmp_path: Path) -> None:
    handler, worker = handler_for(make_project(tmp_path))
    out = Handler._keys(handler, {"gateway": "openrouter", "keys": "  "})
    assert out["ok"] is False and out["error"]
    assert worker.scans == 0, "каталог пересобирать нечего"


def test_обработчик_моделей_пишет_оба_файла(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    handler, worker = handler_for(root)
    out = Handler._models(handler, {
        "gateway": "openrouter", "model": "a/b", "tier": 3,
    })
    assert out["ok"] is True and worker.scans == 1
    assert TierBook.load(root).tier_of("openrouter", "a/b") == 3
    gw = next(g for g in load_gateways(root, env={}) if g["id"] == "openrouter")
    assert "a/b" in gw["free_models"] and "live" in gw["catalog"]

    out = Handler._models(handler, {"gateway": "openrouter", "model": "a/b",
                                    "action": "remove"})
    assert out["ok"] is True
    tiers = json.loads((root / "config" / "tiers.json").read_text(encoding="utf-8"))
    assert all(m["model"] != "a/b" for m in tiers["models"]), "паспорт остался"
    gw = next(g for g in load_gateways(root, env={}) if g["id"] == "openrouter")
    assert "a/b" not in gw["free_models"]


def test_неизвестный_шлюз_откатывает_паспорт(tmp_path: Path) -> None:
    """Файлы не должны разъехаться: нет шлюза — нет и записанного паспорта."""
    root = make_project(tmp_path)
    handler, worker = handler_for(root)
    out = Handler._models(handler, {"gateway": "nope-gateway", "model": "a/b"})
    assert out["ok"] is False and "шлюз" in out["error"]
    data = json.loads((root / "config" / "tiers.json").read_text(encoding="utf-8"))
    assert all(m["model"] != "a/b" for m in data["models"])
    assert worker.scans == 0


def test_настройки_в_обработчике(tmp_path: Path) -> None:
    handler, _worker = handler_for(make_project(tmp_path))
    out = Handler._settings(handler, {})
    assert out["ok"] is True
    assert {g["id"] for g in out["gateways"]} == {
        "openrouter", "cloudflare", "ollama", "zen",
    }


def test_счётчик_zen_смотрит_в_legacy_поле(tmp_path: Path) -> None:
    """Ключ zen лежит в zen_api_key, а сам шлюз об этом в конфиге не знает.

    Брать key_count из load_gateways — и в интерфейсе всегда ноль, хотя в
    файле два ключа и `load_api_key()` их читает.
    """
    root = make_project(tmp_path)
    out = {g["id"]: g for g in build_settings(root, env={})["gateways"]}
    assert out["zen"]["key_field"] == "zen_api_key"
    assert out["zen"]["env_var"] == "ZAGENT_ZEN_API_KEY"
    assert out["zen"]["key_count"] == 2

    edit_secret("zen_api_key", "z3", action="add", root=root)
    out = {g["id"]: g for g in build_settings(root, env={})["gateways"]}
    assert out["zen"]["key_count"] == 3


# --------------------------------------------------------------- интерфейс

def test_вкладка_настроек_в_интерфейсе() -> None:
    """Вкладка, поля и обработчики должны существовать: без них правка мертва."""
    from hub.ui import UI_HTML

    assert 'data-p="settings"' in UI_HTML
    assert 'id="p-settings"' in UI_HTML
    assert '<textarea id="keyText"' in UI_HTML
    for fn in ("function loadSettings", "function keysSend", "function extraSave",
               "function modelSend", "function modelDrop", "function renderKeySide",
               "function renderModelList", "function keysSummary"):
        assert fn in UI_HTML, f"нет {fn}"
    for label in ("Добавить", "Заменить всё", "Удалить вставленные",
                  "Добавить модель", "Удалить модель"):
        assert label in UI_HTML, f"нет кнопки «{label}»"


def test_данные_уходят_в_data_атрибуты(tmp_path: Path) -> None:
    """Плейсхолдеры и id моделей уходят в data-*, а не в onclick.

    `esc()` превращает апостроф в `&#39;`, HTML-парсер декодирует сущности
    до компиляции JavaScript — и строка рвётся. Сюда попадают имена полей
    вида `cloudflare_account_id` и идентификаторы моделей.
    """
    from hub.ui import UI_HTML

    assert 'onclick="extraSave(this)"' in UI_HTML
    assert 'onclick="modelDrop(this)"' in UI_HTML
    assert 'data-name=' in UI_HTML and 'data-model=' in UI_HTML


def test_настройки_доступны_get() -> None:
    """Интерфейс зовёт /api/settings без тела: GET-маршрут обязан быть."""
    import inspect

    src = inspect.getsource(Handler.do_GET)
    assert '"/api/settings"' in src
