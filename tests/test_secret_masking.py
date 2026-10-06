"""Ключи не должны уезжать из программы вместе с инструкцией.

`/api/connect` отдаёт ключи провайдеров в браузер: их читает интерфейс, чтобы
показать, какие ключи заданы. Ключи попадают в DOM страницы, а страница
тянет шрифты с CDN — при компрометации CDN его скрипт прочитал бы всё, что
лежит в странице, вместе с живыми ключами.

Поэтому в общем ответе ключ замаскирован, а полный отдаётся отдельным
действием и только для одного шлюза.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.connect import build_connect_info, build_guide, reveal_key  # noqa: E402
from hub.tools import mask_secret  # noqa: E402

# Заглушка вместо ключа. Собранная программно, а не вписана строкой:
# проверка формы ключа на стороне GitHub ищет `sk-or-v1-` + 64 символа
# [A-Za-z0-9], и любой литерал такого вида — настоящий ключ или очень
# похожий на него — останавливает пуш. Проверке маскировки формат не важен:
# ей нужно любое значение, которое не должно показываться наружу.
SECRET = "sk-or-v1-" + ("тест-значение-не-настоящий-ключ" * 2)


def registry_with(gateways: list[dict], models: list[tuple[str, str]] = None):
    from hub.registry import FreeModel, Registry

    return Registry(
        gateways=gateways,
        models=[FreeModel(gw, mid, "static") for gw, mid in (models or [])],
    )


def gw(gid: str, key: str = SECRET, has_key: bool = True) -> dict:
    return {
        "id": gid,
        "label": gid.upper(),
        "base_url": f"https://{gid}.test/v1",
        "api_key": key,
        "api_keys": [key],
        "key_count": 1,
        "needs_key": True,
        "has_key": has_key,
    }


# =============================================================== маска


def test_маска_не_раскрывает_ключ() -> None:
    masked = mask_secret(SECRET)
    assert SECRET not in masked
    assert masked.startswith("sk-or")
    assert masked.endswith(SECRET[-4:])


def test_маска_короткого_ключа() -> None:
    assert mask_secret("") == ""
    assert mask_secret("abc").endswith("abc")
    # Даже короткий ключ не показывается целиком, если он длиннее 12.
    assert mask_secret("0123456789abc") != "0123456789abc"


def test_маска_узнаётся_человеком() -> None:
    """Маска обязана позволять отличить свои девять ключей."""
    a = mask_secret(SECRET)
    b = mask_secret("sk-or-v1-" + "0" * 29 + "_" + "1" * 29 + "b")
    assert a != b


# =============================================================== ответы


def test_build_guide_не_отдаёт_полный_ключ() -> None:
    registry = registry_with([gw("openrouter")], [("openrouter", "m")])
    guide = build_guide(registry)

    blob = str(guide)
    assert SECRET not in blob, "полный ключ попал в ответ /api/connect"

    for conn in guide["connections"]:
        assert conn["api_key"] != SECRET
        assert conn["key_masked"]
        assert conn["has_key"] is True


def test_build_connect_info_не_отдаёт_полный_ключ() -> None:
    registry = registry_with([gw("openrouter")], [("openrouter", "m")])
    for info in build_connect_info(registry):
        if info.api_key:
            assert info.to_dict()["api_key"] != SECRET
            assert info.to_dict(reveal=True)["api_key"] == SECRET


def test_reveal_отдаёт_один_шлюз() -> None:
    registry = registry_with(
        [gw("openrouter"), gw("groq", key="gsk_другой_ключ_для_проверки_1234")],
        [("openrouter", "m"), ("groq", "m2")],
    )
    out = reveal_key(registry, "openrouter")
    assert out["ok"] is True
    assert out["api_key"] == SECRET
    assert "groq" not in str(out), "ответ потянул за собой чужой шлюз"


def test_reveal_несуществующего_шлюза() -> None:
    out = reveal_key(registry_with([gw("openrouter")]), "нет-такого")
    assert out["ok"] is False
    assert "не найден" in out["error"].lower()


def test_reveal_без_ключа() -> None:
    registry = registry_with([gw("ollama", key="", has_key=False)], [("ollama", "m")])
    out = reveal_key(registry, "ollama")
    assert out["ok"] is False


def test_число_аккаунтов_сообщается() -> None:
    """Девять аккаунтов — это девять ключей, и интерфейс должен это знать."""
    registry = registry_with([{
        "id": "openrouter", "label": "OpenRouter",
        "base_url": "https://orx.test/v1",
        "api_key": SECRET, "api_keys": [SECRET] * 9,
        "key_count": 9, "needs_key": True, "has_key": True,
    }], [("openrouter", "m")])
    out = reveal_key(registry, "openrouter")
    assert out["key_count"] == 9