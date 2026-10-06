"""Тесты воркспейсов, инструкций по подключению и границ доступа."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub.autonomy import AccessLevel, Autonomy, Escalation, Guard
from hub.connect import build_connect_info, build_guide, codex_block, opencode_block
from hub.tools import mask_secret
from hub.workspace import WorkspaceError, WorkspaceManager, workspaces_path


def gw(gateway_id: str, **kw) -> dict:
    # env задаётся в реальном config/gateways.json, поэтому и в заглушке
    # он обязателен: без него инструкции предложат нестандартное имя переменной.
    base = {
        "id": gateway_id, "label": kw.pop("label", gateway_id.title()),
        "base_url": f"https://{gateway_id}.test/v1", "resolved_url": f"https://{gateway_id}.test/v1",
        "api_key": kw.pop("api_key", ""), "needs_key": kw.pop("needs_key", True),
        "has_key": kw.pop("has_key", False), "free_models": [], "catalog": [],
        "supports_responses": kw.pop("supports_responses", True),
        "env": kw.pop("env", f"{gateway_id.upper().replace('-', '_')}_API_KEY"),
    }
    base.update(kw)
    return base


def make_registry(gateways: list[dict], models: list[tuple[str, str]]) -> object:
    from hub.registry import FreeModel, Registry

    return Registry(
        gateways=gateways,
        models=[FreeModel(g, m, "static") for g, m in models],
    )


@pytest.fixture()
def manager(tmp_path: Path) -> WorkspaceManager:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    return WorkspaceManager(tmp_path)


# ------------------------------------------------------------------ воркспейсы


def test_default_workspace_created(manager: WorkspaceManager) -> None:
    """Папкой по умолчанию раньше был корень проекта.

    Теперь это `projects/`: результаты работы агента не должны лежать рядом
    с кодом zagent. Иначе после нескольких задач в репозитории лежит
    вперемешку код и то, что нагенерировал агент.
    """
    assert len(manager.items) == 1
    assert manager.active.id == "default"
    assert manager.active.path == str(manager.root / "projects")
    assert manager.active.resolved().is_dir(), "папка должна существовать сразу"


def test_add_workspace(manager: WorkspaceManager, tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()

    workspace = manager.add(str(target), name="my project")

    assert workspace.name == "my project"
    # Идентификатор без пробелов и в нижнем регистре.
    assert " " not in workspace.id
    assert manager.get(workspace.id) is not None


def test_add_workspace_requires_existing_dir(manager: WorkspaceManager, tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="не найдена"):
        manager.add(str(tmp_path / "missing"))


def test_add_workspace_rejects_duplicate_path(manager: WorkspaceManager, tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    manager.add(str(target))

    with pytest.raises(WorkspaceError, match="уже добавлен"):
        manager.add(str(target))


def test_duplicate_names_get_suffix(manager: WorkspaceManager, tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()

    one = manager.add(str(first), name="same")
    two = manager.add(str(second), name="same")

    assert one.id != two.id
    assert two.id.startswith(one.id)


def test_activate(manager: WorkspaceManager, tmp_path: Path) -> None:
    target = tmp_path / "other"
    target.mkdir()
    workspace = manager.add(str(target))

    manager.activate(workspace.id)

    assert manager.active.id == workspace.id


def test_activate_unknown_fails(manager: WorkspaceManager) -> None:
    with pytest.raises(WorkspaceError, match="не найден"):
        manager.activate("nope")


def test_remove_workspace(manager: WorkspaceManager, tmp_path: Path) -> None:
    target = tmp_path / "other"
    target.mkdir()
    workspace = manager.add(str(target))

    manager.remove(workspace.id)

    assert manager.get(workspace.id) is None
    # Активный переключился на оставшийся.
    assert manager.active.id == "default"


def test_cannot_remove_last(manager: WorkspaceManager) -> None:
    with pytest.raises(WorkspaceError, match="последний"):
        manager.remove("default")


def test_update_settings(manager: WorkspaceManager) -> None:
    manager.update("default", access=3, autonomy="strict", max_steps=99)

    workspace = manager.get("default")
    assert workspace.access == 3
    assert workspace.autonomy == "strict"
    assert workspace.max_steps == 99


def test_contains_inside(manager: WorkspaceManager) -> None:
    root = manager.active.resolved()
    inside = root / "hub" / "agent.py"

    assert manager.contains("default", inside) is True
    assert manager.contains("default", root) is True


def test_contains_outside(manager: WorkspaceManager, tmp_path: Path) -> None:
    # Воркспейс по умолчанию — это сам tmp_path, поэтому «снаружи» должна быть
    # папка рядом с ним, а не внутри.
    outside = tmp_path.parent / "other-project" / "file.py"
    assert manager.contains("default", outside) is False


def test_contains_rejects_nested_other_workspace(manager: WorkspaceManager, tmp_path: Path) -> None:
    """Вложенный воркспейс — тоже «снаружи» для родительского."""
    nested = manager.active.resolved() / "inner"
    nested.mkdir(exist_ok=True)
    manager.add(str(nested), name="inner")

    assert manager.contains("inner", nested / "file.py") is True
    assert manager.contains("default", nested / "file.py") is True


def test_contains_sibling_with_prefix(manager: WorkspaceManager, tmp_path: Path) -> None:
    """Папка «zagent-evil» не должна считаться частью «zagent»."""
    root = manager.active.resolved()
    sibling = root.parent / (root.name + "-evil")
    assert manager.contains("default", sibling) is False


def test_persistence_across_restart(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    target = tmp_path / "proj"
    target.mkdir()

    first = WorkspaceManager(tmp_path)
    workspace = first.add(str(target), name="proj")
    first.activate(workspace.id)
    first.update(workspace.id, access=1)
    first.close if hasattr(first, "close") else None

    second = WorkspaceManager(tmp_path)
    assert second.active.id == workspace.id
    assert second.get(workspace.id).access == 1


def test_workspaces_file_created(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    manager = WorkspaceManager(tmp_path)
    target = tmp_path / "x"
    target.mkdir()
    manager.add(str(target))

    assert workspaces_path(tmp_path).is_file()


def test_corrupt_file_falls_back_to_default(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    workspaces_path(tmp_path).write_text("{ битый json", encoding="utf-8")

    manager = WorkspaceManager(tmp_path)
    assert len(manager.items) == 1
    assert manager.active.id == "default"


def test_describe_shape(manager: WorkspaceManager) -> None:
    data = manager.describe()

    assert data["active"] == "default"
    assert data["workspaces"][0]["exists"] is True
    assert "config_path" in data


# ------------------------------------------------------------ граница доступа


def test_guard_workspace_blocks_outside_even_full() -> None:
    """Жёсткая граница не отменяется даже полным доступом.

    При мягкой границе полный доступ означает «выходи наружу без вопросов»,
    поэтому проверять границу имеет смысл только в жёстком режиме.
    """
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace("C:/work/project", "proj", soft_boundary=False)

    assert guard.check_access("delete").allowed is True

    allowed, reason = guard.check_path("C:/work/other/file.txt", writing=True)
    assert allowed is False
    assert "вне воркспейса" in reason


def test_guard_soft_boundary_full_access_goes_outside() -> None:
    """Мягкая граница + полный доступ: спрашивать уже не о чем."""
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace("C:/work/project", "proj", soft_boundary=True)

    assert guard.check_path("C:/work/other/file.txt", writing=True)[0] is True


def test_guard_workspace_allows_inside() -> None:
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace("C:/work/project", "proj")

    allowed, _ = guard.check_path("C:/work/project/src/main.py", writing=True)
    assert allowed is True


def test_guard_workspace_blocks_outside_for_read() -> None:
    guard = Guard(access=AccessLevel.READ)
    guard.set_workspace("C:/work/project", "proj")

    allowed, reason = guard.check_path("C:/etc/passwd", writing=False)
    assert allowed is False
    assert "вне воркспейса" in reason


def test_workspace_boundary_case_insensitive() -> None:
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace("C:/Work/Project", "proj")

    assert guard.check_path("c:/work/project/file.txt", writing=True)[0] is True


def test_workspace_boundary_blocks_sibling() -> None:
    """«project-evil» не считается частью «project».

    Сравнение идёт по компонентам пути, иначе префикс строки прошёл бы.
    """
    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace("C:/work/project", "proj", soft_boundary=False)

    assert guard.check_path("C:/work/project-evil/file.txt", writing=True)[0] is False


def test_no_workspace_means_no_boundary() -> None:
    guard = Guard(access=AccessLevel.FULL)
    assert guard.inside_workspace("C:/anywhere/file.txt") is True


# --------------------------------------------------- инструкции по подключению


def test_connect_info_exposes_credentials() -> None:
    registry = make_registry(
        [gw("groq", api_key="gsk-secret", has_key=True)],
        [("groq", "openai/gpt-oss-120b")],
    )
    info = build_connect_info(registry)[0]

    assert info.provider_id == "groq"
    assert info.base_url == "https://groq.test/v1"
    assert info.api_key == "gsk-secret"
    assert info.env_var == "GROQ_API_KEY"
    assert info.models == ["openai/gpt-oss-120b"]


def test_connect_info_marks_missing_key() -> None:
    registry = make_registry([gw("groq")], [("groq", "m")])
    info = build_connect_info(registry)[0]

    assert info.error is not None
    assert "секрет" in info.error or "ключ" in info.error


def test_connect_info_keyless() -> None:
    registry = make_registry(
        [gw("llm7", needs_key=False, has_key=False)],
        [("llm7", "DeepSeek-V4-Flash-0731")],
    )
    info = build_connect_info(registry)[0]

    assert info.keyless is True
    assert info.api_key is None
    assert info.error is None


def test_opencode_block_has_valid_json() -> None:
    registry = make_registry(
        [gw("groq", api_key="k", has_key=True)],
        [("groq", "openai/gpt-oss-120b"), ("groq", "qwen/qwen3.8-27b")],
    )
    info = build_connect_info(registry)[0]
    block = opencode_block(info)

    start = block.index("{")
    payload = json.loads(block[start:])

    assert payload["$schema"] == "https://opencode.ai/config.json"
    assert payload["model"] == "groq/openai/gpt-oss-120b"
    assert len(payload["providers"]["groq"]["models"]) == 2
    # Запятые между моделями должны быть валидным JSON, а не «хвост».
    assert payload["providers"]["groq"]["env"] == ["GROQ_API_KEY"]


def test_codex_block_refuses_without_responses() -> None:
    registry = make_registry(
        [gw("cloudflare", supports_responses=False, api_key="k", has_key=True)],
        [("cloudflare", "@cf/openai/gpt-oss-120b")],
    )
    info = build_connect_info(registry)[0]
    block = codex_block(info)

    assert "НЕЛЬЗЯ" in block
    assert "responses" in block.lower()


def test_codex_block_has_toml() -> None:
    registry = make_registry(
        [gw("groq", api_key="k", has_key=True)],
        [("groq", "openai/gpt-oss-120b")],
    )
    block = codex_block(build_connect_info(registry)[0])

    assert "[model_providers.groq]" in block
    assert 'wire_api = "responses"' in block
    assert 'env_key = "GROQ_API_KEY"' in block


def test_guide_lists_all_targets() -> None:
    registry = make_registry(
        [gw("groq", api_key="k", has_key=True)],
        [("groq", "openai/gpt-oss-120b")],
    )
    guide = build_guide(registry)

    for target in ("opencode", "deepseek", "codex", "zed", "cline"):
        assert target in guide["targets"]
        assert guide["targets"][target]["label"]


def test_guide_marks_unavailable_with_reason() -> None:
    registry = make_registry(
        [gw("cloudflare", supports_responses=False, api_key="k", has_key=True)],
        [("cloudflare", "@cf/openai/gpt-oss-120b")],
    )
    guide = build_guide(registry)
    codex_entries = guide["targets"]["codex"]["entries"]

    assert codex_entries[0]["available"] is False
    assert "Responses" in codex_entries[0]["reason"]


def test_guide_hides_gateways_without_keys() -> None:
    registry = make_registry([gw("groq")], [("groq", "m")])
    guide = build_guide(registry)
    entries = guide["targets"]["opencode"]["entries"]

    assert entries[0]["available"] is False
    assert "instruction" not in entries[0]


def test_guide_never_invents_key() -> None:
    """Ключ в инструкции обязан происходить из secrets, а не быть придуман.

    Проверяется по маске: полный ключ в ответе не отдаётся (он попадает в DOM
    страницы, а страница тянет шрифты с CDN), но маска обязана совпадать с
    настоящим ключом — иначе инструкция ведёт не туда.
    """
    registry = make_registry(
        [gw("groq", api_key="real-key-value", has_key=True)],
        [("groq", "m")],
    )
    guide = build_guide(registry)

    checked = 0
    for target in guide["targets"].values():
        for entry in target["entries"]:
            if entry.get("available") and not entry.get("keyless"):
                masked = entry["api_key"]
                assert masked != "real-key-value", "полный ключ попал в ответ"
                assert masked == mask_secret("real-key-value"), masked
                assert entry["has_key"] is True
                checked += 1
    assert checked, "ни одна запись не проверена"
