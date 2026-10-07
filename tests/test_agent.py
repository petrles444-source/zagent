"""Тесты ядра агента: приоритеты, failover, права, инструменты, sanity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub.agent import build_system_prompt, parse_tool_calls
from hub.autonomy import (
    AccessLevel,
    Autonomy,
    Escalation,
    Guard,
    inspect_shell,
)
from hub.sanity import (
    build_probe_prompt,
    check_context,
    check_follow,
    check_language,
    check_not_degenerate,
    evaluate,
)
from hub.selector import COOLDOWN, Mode, Selector
from hub.tiers import TierBook, guess_tier, rank_models
from hub.tools import (
    edit_file,
    list_dir,
    read_file,
    search_text,
    tool_catalog_for_prompt,
    write_file,
)


def gw(**kw) -> dict:
    base = {
        "id": "test", "label": "Test", "base_url": "https://example.test/v1",
        "resolved_url": "https://example.test/v1", "api_key": "", "needs_key": True,
        "has_key": False, "free_models": [], "catalog": [], "supports_responses": False,
    }
    base.update(kw)
    return base


def make_registry(gateways: list[dict], models: list):
    from hub.registry import FreeModel, Registry

    return Registry(gateways=gateways, models=[FreeModel(*m) for m in models])


# ------------------------------------------------------------- разбор вызовов


def test_parse_single_tool_call() -> None:
    text = '```json\n{"tool": "read_file", "args": {"path": "a.py"}}\n```'
    calls = parse_tool_calls(text)

    assert calls == [{"tool": "read_file", "args": {"path": "a.py"}}]


def test_parse_bare_json_without_fence() -> None:
    calls = parse_tool_calls('{"tool": "list_dir", "args": {"path": "."}}')
    assert calls[0]["tool"] == "list_dir"


def test_parse_nested_objects_in_args() -> None:
    """Вложенные объекты в args не должны обрывать разбор."""
    text = json.dumps({
        "tool": "write_file",
        "args": {"path": "x.json", "content": '{"a": 1, "b": {"c": 2}}'},
    })
    calls = parse_tool_calls(text)

    assert len(calls) == 1
    assert calls[0]["args"]["path"] == "x.json"


def test_parse_multiline_string_with_braces() -> None:
    """Строки с фигурными скобками внутри args — реальный случай с кодом Python."""
    args = {"path": "t.py", "old": 'def test():\n    assert {"k": 1} == {"k": 1}\n',
            "new": 'def test():\n    assert {"k": 2} == {"k": 2}\n'}
    calls = parse_tool_calls(json.dumps({"tool": "edit_file", "args": args}))

    assert len(calls) == 1
    assert calls[0]["args"]["old"] == args["old"]


def test_parse_escaped_quotes() -> None:
    calls = parse_tool_calls('{"tool": "write_file", "args": {"content": "say \\"hi\\" ok"}}')
    assert calls[0]["args"]["content"] == 'say "hi" ok'


def test_parse_deduplicates_repeat() -> None:
    text = '{"tool": "read_file", "args": {"path": "a.py"}}\nи ещё\n{"tool": "read_file", "args": {"path": "a.py"}}'
    calls = parse_tool_calls(text)
    assert len(calls) == 1


def test_parse_batch_list() -> None:
    calls = parse_tool_calls(json.dumps([
        {"tool": "read_file", "args": {"path": "a"}},
        {"tool": "read_file", "args": {"path": "b"}},
    ]))
    assert [c["args"]["path"] for c in calls] == ["a", "b"]


def test_parse_ignores_prose_without_calls() -> None:
    assert parse_tool_calls("Готово, файл создан.") == []
    assert parse_tool_calls("Смотри код: def f(): pass") == []


def test_parse_unbalanced_braces_ignored() -> None:
    assert parse_tool_calls('{"tool": "read_file", "args": {"path": ') == []


def test_parse_empty() -> None:
    assert parse_tool_calls("") == []


def test_parse_handles_non_dict_args() -> None:
    calls = parse_tool_calls('{"tool": "read_file", "args": "path"}')
    assert calls[0]["args"] == {}


# ------------------------------------------------------------------- тиры


def test_guess_tier_by_size() -> None:
    assert guess_tier("nvidia/nemotron-3-ultra-550b-a55b:free", "openrouter") == 1
    assert guess_tier("openai/gpt-oss-120b", "groq") == 1
    assert guess_tier("some/llama-3.3-70b-instruct", "x") == 2
    assert guess_tier("vendor/thing-27b", "x") == 3
    assert guess_tier("vendor/thing-8b", "x") == 4


def test_keyless_gateways_rank_low() -> None:
    assert guess_tier("some-big-model-70b", "llm7") == 4
    assert guess_tier("anything", "ollama") == 4


def test_tierbook_loads_config() -> None:
    root = Path(__file__).resolve().parent.parent
    book = TierBook.load(root)

    assert len(book) > 10
    # Nemotron Ultra помечен как лучший.
    assert book.tier_of("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free") == 1


def test_tierbook_marks_vision() -> None:
    root = Path(__file__).resolve().parent.parent
    book = TierBook.load(root)

    assert book.get("cloudflare", "@cf/google/gemma-4-26b-a4b-it").vision is True
    assert book.get("groq", "openai/gpt-oss-120b").vision is False


def test_tierbook_falls_back_to_heuristic() -> None:
    book = TierBook({})
    # 20B не описан в tiers.json — эвристика относит его к среднему уровню.
    assert book.get("groq", "openai/gpt-oss-20b").tier == 4


def test_rank_models_orders_by_tier() -> None:
    from hub.registry import FreeModel

    root = Path(__file__).resolve().parent.parent
    book = TierBook.load(root)
    models = [
        FreeModel("groq", "openai/gpt-oss-120b", "static"),
        FreeModel("llm7", "minimax-m2.7", "static"),
        FreeModel("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", "live"),
    ]
    ranked = rank_models(models, book)

    assert ranked[0].model_id == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert ranked[-1].model_id == "minimax-m2.7"


def test_rank_models_filter_vision() -> None:
    from hub.registry import FreeModel

    root = Path(__file__).resolve().parent.parent
    book = TierBook.load(root)
    models = [
        FreeModel("groq", "openai/gpt-oss-120b", "static"),
        FreeModel("cloudflare", "@cf/google/gemma-4-26b-a4b-it", "static"),
    ]
    ranked = rank_models(models, book, require_vision=True)

    assert len(ranked) == 1
    assert ranked[0].model_id == "@cf/google/gemma-4-26b-a4b-it"


def test_rank_models_prefer_speed_uses_latency() -> None:
    """При равном тире быстрая модель идёт первой.

    Берём две модели одного тира (обе тир 2) с разной задержкой.
    """
    from hub.registry import FreeModel

    root = Path(__file__).resolve().parent.parent
    book = TierBook.load(root)
    models = [
        # Обе модели тир 2 в tiers.json, различается только задержка.
        FreeModel("groq", "qwen/qwen3.8-27b", "static"),
        FreeModel("z_ai", "glm-4.7-flash", "static"),
    ]
    assert book.tier_of("groq", "qwen/qwen3.8-27b") == book.tier_of("z_ai", "glm-4.7-flash")

    latencies = {"groq/qwen/qwen3.8-27b": 3.0, "z_ai/glm-4.7-flash": 0.1}
    ranked = rank_models(models, book, prefer_speed=True, latencies=latencies)

    assert ranked[0].ref == "z_ai/glm-4.7-flash"


# --------------------------------------------------------------- селектор


def build_selector(**kw) -> Selector:
    registry = make_registry(
        [gw(id="groq", has_key=True), gw(id="llm7", needs_key=False, has_key=False)],
        [
            ("groq", "openai/gpt-oss-120b", "static"),
            ("groq", "openai/gpt-oss-20b", "static"),
            ("llm7", "minimax-m2.7", "static"),
        ],
    )
    root = Path(__file__).resolve().parent.parent
    return Selector(registry, TierBook.load(root), **kw)


def test_selector_auto_picks_tier_one() -> None:
    selector = build_selector()
    ref = selector.next_model()
    assert ref in ("groq/openai/gpt-oss-120b", "llm7/minimax-m2.7"), (
        "gpt-oss-120b отмечена как рабочая по замеру на настоящей задаче "
        "06.10.2026 (вызвала write_file, создала файл), поэтому её "
        "нельзя исключать; gpt-oss-20b исключена — она инструмент не вызвала"
    )


def test_selector_не_берёт_модели_без_инструментов() -> None:
    """Переключение при отказе не должно приводить к модели без инструментов.

    Такая модель не выдаст вызов, и задача выглядела бы сделанной: агент
    описал словами то, чего не сделал, и цикл завершился успехом.

    Список моделей, которые нельзя выбирать, берётся из config/tiers.json,
    а не выписывается здесь: пометки про инструменты меняются по мере
    замеров, и копия их в проверке осталась бы правдой ровно до первого же
    нового замера.
    """
    from hub.tiers import TierBook

    book = TierBook.load(Path(__file__).resolve().parent.parent)
    forbidden = {f"{s.gateway}/{s.model}" for s in book.specs() if not s.tools}
    assert forbidden, "в tiers.json должно быть хоть одно поле без инструментов"

    selector = build_selector()
    for _ in range(4):
        ref = str(selector.next_model())
        for bad in forbidden:
            assert ref != bad and not ref.endswith(bad.split("/", 1)[1]), (
                f"выбрана модель без инструментов: {ref}"
            )


def test_selector_record_ok_clears_cooldown() -> None:
    selector = build_selector()
    ref = "groq/openai/gpt-oss-120b"

    selector.record(ref, "limited")
    assert selector.states[ref].in_cooldown

    selector.record(ref, "ok", duration_ms=500)
    assert not selector.states[ref].in_cooldown
    assert selector.states[ref].ok_count == 1


def test_selector_skips_cooling_model() -> None:
    selector = build_selector()
    best = "llm7/minimax-m2.7"
    selector.record(best, "limited")

    assert selector.next_model() != best


def test_selector_manual_mode_pins_model() -> None:
    selector = build_selector(mode=Mode.MANUAL, manual_ref="llm7/minimax-m2.7")
    assert selector.next_model() == "llm7/minimax-m2.7"


def test_selector_chain_order() -> None:
    selector = build_selector(mode=Mode.CHAIN, chain=[
        "llm7/minimax-m2.7", "groq/openai/gpt-oss-120b",
    ])
    assert selector.next_model() == "llm7/minimax-m2.7"


def test_selector_exclude_skips_tried() -> None:
    selector = build_selector()
    nxt = selector.next_model(exclude={"llm7/minimax-m2.7"})
    assert nxt != "llm7/minimax-m2.7"


def test_selector_blocked_gets_long_cooldown() -> None:
    selector = build_selector()
    ref = "groq/openai/gpt-oss-120b"
    selector.record(ref, "blocked")

    assert selector.states[ref].blocked
    assert selector.states[ref].cooldown_left >= COOLDOWN["blocked"] - 5


def test_selector_backoff_grows_with_repeats() -> None:
    selector = build_selector()
    ref = "groq/openai/gpt-oss-120b"

    selector.record(ref, "down")
    first = selector.states[ref].cooldown_until
    selector.record(ref, "down")
    second = selector.states[ref].cooldown_until

    assert second > first


def test_selector_recovers_after_ok() -> None:
    selector = build_selector()
    ref = "groq/openai/gpt-oss-120b"

    selector.record(ref, "limited")
    selector.record(ref, "limited")
    assert selector.states[ref].fails == 2

    selector.record(ref, "ok")
    assert selector.states[ref].fails == 0
    assert selector.states[ref].in_cooldown is False


def test_selector_avg_latency_smoothed() -> None:
    selector = build_selector()
    ref = "groq/openai/gpt-oss-120b"

    selector.record(ref, "ok", duration_ms=1000)
    selector.record(ref, "ok", duration_ms=1000)
    # Второе обновление должно усреднить, а не заменить.
    assert 900 < selector.states[ref].avg_ms <= 1000


def test_selector_stats_counts() -> None:
    selector = build_selector()
    selector.record("groq/openai/gpt-oss-120b", "ok")
    selector.record("groq/openai/gpt-oss-20b", "limited")

    stats = selector.stats()
    assert stats["total"] == 3
    assert stats["ok"] == 1
    assert stats["cooling"] == 1


def test_selector_candidates_sorted() -> None:
    selector = build_selector()
    rows = selector.candidates()
    tiers = [r["tier"] for r in rows]

    assert tiers == sorted(tiers)


# ------------------------------------------------------------------- Guard


def test_guard_read_level_blocks_write() -> None:
    guard = Guard(access=AccessLevel.READ)

    assert guard.check_access("read").allowed is True
    assert guard.check_access("write").allowed is False
    assert guard.check_access("delete").allowed is False
    assert guard.check_access("shell").allowed is False


def test_guard_write_level_allows_write_but_not_delete() -> None:
    guard = Guard(access=AccessLevel.WRITE)

    assert guard.check_access("write").allowed is True
    assert guard.check_access("delete").allowed is False


def test_guard_full_level_allows_everything() -> None:
    guard = Guard(access=AccessLevel.FULL)
    for operation in ("read", "write", "delete", "shell", "capture_screen"):
        assert guard.check_access(operation).allowed is True


def test_guard_protects_git_directory() -> None:
    guard = Guard(access=AccessLevel.FULL)

    allowed, reason = guard.check_path("/repo/.git/config", writing=True)
    assert allowed is False
    assert ".git" in reason


def test_guard_protects_venv() -> None:
    guard = Guard(access=AccessLevel.FULL)
    allowed, _ = guard.check_path("/repo/.venv/lib/x.py", writing=True)
    assert allowed is False


def test_guard_allows_normal_path() -> None:
    guard = Guard(access=AccessLevel.FULL)
    assert guard.check_path("/repo/src/main.py", writing=True)[0] is True


def test_guard_write_roots_limit_scope() -> None:
    guard = Guard(access=AccessLevel.FULL, write_roots=["/repo/work"])

    assert guard.check_path("/repo/work/a.py", writing=True)[0] is True
    assert guard.check_path("/etc/passwd", writing=True)[0] is False


def test_guard_yolo_never_confirms() -> None:
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.YOLO)
    assert guard.needs_confirmation("delete") is False
    assert guard.needs_confirmation("write") is False


def test_guard_strict_confirms_everything() -> None:
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.STRICT)
    assert guard.needs_confirmation("read") is True
    assert guard.needs_confirmation("write") is True


def test_guard_normal_confirms_destructive_only() -> None:
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.NORMAL)
    assert guard.needs_confirmation("read") is False
    assert guard.needs_confirmation("write") is True
    assert guard.needs_confirmation("delete") is True


def test_guard_confirmation_is_remembered() -> None:
    guard = Guard(access=AccessLevel.FULL, autonomy=Autonomy.NORMAL)

    assert guard.needs_confirmation("delete", "a.txt") is True
    guard.confirm("delete", "a.txt")
    assert guard.needs_confirmation("delete", "a.txt") is False


def test_guard_escalation_off_never_asks() -> None:
    guard = Guard(access=AccessLevel.READ, escalation=Escalation.OFF)
    assert guard.should_escalate("write", "требует уровня") is False


def test_guard_escalation_auto_asks_on_blocked_op() -> None:
    guard = Guard(access=AccessLevel.READ, escalation=Escalation.AUTO)
    assert guard.should_escalate("write", "требует уровня «полный»") is True


def test_guard_escalation_auto_stays_quiet_on_allowed_op() -> None:
    guard = Guard(access=AccessLevel.FULL, escalation=Escalation.AUTO)
    assert guard.should_escalate("write", "требует уровня") is False


def test_guard_escalation_on_always_asks() -> None:
    guard = Guard(access=AccessLevel.FULL, escalation=Escalation.ON)
    assert guard.should_escalate("write", "что угодно") is True


def test_inspect_shell_flags_dangerous() -> None:
    assert inspect_shell("rm -rf /tmp/x")["dangerous"] is True
    assert inspect_shell("git status")["dangerous"] is False
    assert "curl" in inspect_shell("curl https://x")["markers"]


def test_build_system_prompt_lists_tools() -> None:
    from hub.agent import AgentConfig

    guard = Guard(access=AccessLevel.FULL)
    prompt = build_system_prompt(guard, AgentConfig(), workspace="C:/repo")

    assert "C:/repo" in prompt
    assert "read_file" in prompt
    assert "run_shell" in prompt


def test_system_prompt_read_only_hides_destructive_tools() -> None:
    from hub.agent import AgentConfig

    guard = Guard(access=AccessLevel.READ)
    prompt = build_system_prompt(guard, AgentConfig(), workspace="C:/repo")

    assert "read_file" in prompt
    assert "run_shell" not in prompt
    assert "delete_path" not in prompt


def test_system_prompt_plan_mode_mentions_plan() -> None:
    from hub.agent import AgentConfig

    guard = Guard(access=AccessLevel.WRITE, autonomy=Autonomy.PLAN)
    prompt = build_system_prompt(guard, AgentConfig(), workspace="C:/repo")

    assert "план" in prompt.lower()


# ------------------------------------------------------------ граница воркспейса


def test_soft_boundary_prompt_allows_asking() -> None:
    """Мягкая граница: модель должна знать, что выход за неё — вопрос, а не отказ.

    Без этого блока модель отказывается заранее и до разрешения не доходит.
    """
    from hub.agent import AgentConfig

    guard = Guard(access=AccessLevel.WRITE)
    guard.set_workspace("C:/repo", "work", soft_boundary=True)
    prompt = build_system_prompt(guard, AgentConfig(), workspace="C:/repo")

    assert "Граница рабочей директории" in prompt
    # Ключевое: не отказывать, а вызвать инструмент и дождаться окна.
    assert "НЕ отказывай" in prompt
    assert "спросит" in prompt
    assert "откажет" in prompt


def test_hard_boundary_prompt_forbids_leaving() -> None:
    from hub.agent import AgentConfig

    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace("C:/repo", "work", soft_boundary=False)
    prompt = build_system_prompt(guard, AgentConfig(), workspace="C:/repo")

    assert "недоступны" in prompt
    assert "не пытайся" in prompt
    assert "НЕ отказывай" not in prompt


def test_prompt_without_workspace_has_no_boundary_block() -> None:
    """Без воркспейса границы нет — лишний текст про неё только путает."""
    from hub.agent import AgentConfig

    guard = Guard(access=AccessLevel.FULL)
    prompt = build_system_prompt(guard, AgentConfig(), workspace="C:/repo")

    assert "Граница рабочей директории" not in prompt


def test_full_access_prompt_says_no_asking() -> None:
    """При полном доступе модель не должна рассуждать про запрос разрешения."""
    from hub.agent import AgentConfig

    guard = Guard(access=AccessLevel.FULL)
    guard.set_workspace("C:/repo", "work", soft_boundary=True)
    prompt = build_system_prompt(guard, AgentConfig(), workspace="C:/repo")

    assert "Граница рабочей директории" in prompt
    assert "без спроса" in prompt
    assert "Не отказывайся" in prompt
    # Инструкции про окно с кнопками тут быть не должно.
    assert "НЕ отказывай" not in prompt
    assert "система сама спросит" not in prompt


# --------------------------------------------------------------- инструменты


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    written = write_file(tmp_path / "a.txt", "привет", base=tmp_path)
    assert written.ok

    read = read_file("a.txt", base=tmp_path)
    assert read.ok
    assert "привет" in read.data["content"]


def test_read_missing_file_reports_error(tmp_path: Path) -> None:
    result = read_file("nope.txt", base=tmp_path)
    assert result.ok is False
    assert "не найден" in result.error.lower()


def test_read_binary_file_skips_without_asking(tmp_path: Path) -> None:
    """Двоичный файл не останавливает задачу.

    Раньше здесь стояло `assert result.needs_user is True`: инструмент
    запрашивал у человека вопрос («Сделать скриншот или прочитать
    метаданные?») и работа вставала. На такой вопрос нельзя ответить —
    прочитать PNG как текст нельзя, а делать скриншот ради одного файла среди
    двадцати никто не станет. Практически это выглядело так: агент доходил до
    первой картинки и ждал человека.

    Теперь это обычный отказ с указанием, что делать: пропустить файл и
    работать дальше.
    """
    (tmp_path / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    result = read_file("img.png", base=tmp_path)

    assert result.ok is False, "двоичный файл нельзя прочитать как текст"
    assert result.needs_user is False, (
        "задачу нельзя останавливать из-за одного файла")
    assert "Пропусти" in result.error, result.error


def test_edit_replaces_first_occurrence(tmp_path: Path) -> None:
    write_file(tmp_path / "b.txt", "aaa aaa", base=tmp_path)
    result = edit_file("b.txt", "aaa", "bbb", base=tmp_path, allow_multiple=True)

    assert result.ok
    assert read_file("b.txt", base=tmp_path).data["content"] == "bbb aaa"


def test_edit_ambiguous_asks_user(tmp_path: Path) -> None:
    write_file(tmp_path / "c.txt", "x x x", base=tmp_path)
    result = edit_file("c.txt", "x", "y", base=tmp_path)

    assert result.ok is False
    assert result.needs_user is True
    assert "3 раз" in result.question


def test_edit_replace_all(tmp_path: Path) -> None:
    write_file(tmp_path / "d.txt", "x x x", base=tmp_path)
    result = edit_file("d.txt", "x", "y", base=tmp_path, replace_all=True)

    assert result.ok
    assert read_file("d.txt", base=tmp_path).data["content"] == "y y y"


def test_edit_not_found_asks_for_content(tmp_path: Path) -> None:
    write_file(tmp_path / "e.txt", "hello", base=tmp_path)
    result = edit_file("e.txt", "nope", "x", base=tmp_path)

    assert result.ok is False
    assert result.needs_user is True


def test_list_dir_reports_types(tmp_path: Path) -> None:
    write_file(tmp_path / "f.py", "x", base=tmp_path)
    (tmp_path / "sub").mkdir()

    result = list_dir(tmp_path, base=tmp_path)
    types = {e["name"]: e["type"] for e in result.data["entries"]}

    assert types["f.py"] == "file"
    assert types["sub"] == "dir"


def test_search_text_finds_matches(tmp_path: Path) -> None:
    write_file(tmp_path / "g.py", "needle here", base=tmp_path)
    write_file(tmp_path / "h.py", "nothing", base=tmp_path)

    result = search_text("needle", tmp_path, base=tmp_path)
    assert result.data["count"] == 1


def test_tool_catalog_reflects_access() -> None:
    read_only = tool_catalog_for_prompt(Guard(access=AccessLevel.READ))
    full = tool_catalog_for_prompt(Guard(access=AccessLevel.FULL))

    assert "run_shell" not in read_only
    assert "run_shell" in full


# ------------------------------------------------------------------- sanity


def test_sanity_good_response() -> None:
    _, user, token = build_probe_prompt("ru")
    answer = '{"status": "ready", "code": "ZEBRA-7391"}'

    report = evaluate("m", answer, question=user, token=token, duration_ms=800)

    assert report.verdict in ("good", "usable")
    assert all(c.passed for c in report.checks if c.name in ("context", "follow"))


def test_sanity_detects_lost_context() -> None:
    _, user, token = build_probe_prompt("ru")
    answer = '{"status": "ready", "code": "WRONG"}'

    report = evaluate("m", answer, question=user, token=token, duration_ms=800)
    assert not next(c for c in report.checks if c.name == "context").passed


def test_sanity_detects_language_mixing() -> None:
    _, user, token = build_probe_prompt("ru")
    answer = '{"status": "ready", "code": "ZEBRA-7391", "note": "The quick brown fox jumps"}'

    report = evaluate("m", answer, question=user, token=token, duration_ms=800)
    assert not next(c for c in report.checks if c.name == "language").passed


def test_sanity_detects_repetition() -> None:
    _, user, token = build_probe_prompt("ru")
    answer = "ZEBRA-7391 ready ready ready ready ready ready ready ready ready"

    report = evaluate("m", answer, question=user, token=token, duration_ms=800)
    assert not next(c for c in report.checks if c.name == "not_degenerate").passed


def test_sanity_detects_empty() -> None:
    _, user, token = build_probe_prompt("ru")
    report = evaluate("m", "", question=user, token=token, duration_ms=800)

    assert not next(c for c in report.checks if c.name == "not_degenerate").passed
    assert report.verdict == "poor"


def test_sanity_penalises_slow_model() -> None:
    _, user, token = build_probe_prompt("ru")
    fast = evaluate("m", '{"status": "ready", "code": "ZEBRA-7391"}',
                    question=user, token=token, duration_ms=800)
    slow = evaluate("m", '{"status": "ready", "code": "ZEBRA-7391"}',
                    question=user, token=token, duration_ms=25000)

    assert slow.score < fast.score


def test_probe_prompt_hides_token_in_filler() -> None:
    system, user, token = build_probe_prompt("ru")

    assert token in user
    assert token not in system
    assert len(user) > 400
    assert "JSON" in user


def test_check_follow_tolerates_prose() -> None:
    check = check_follow('Готово: {"status": "ready"}')
    assert check.passed is True


def test_check_follow_rejects_wrong_keys() -> None:
    check = check_follow('{"status": "error"}')
    assert check.passed is False


def test_check_language_ignores_non_cyrillic_question() -> None:
    check = check_language("Python is great", "What is Python?")
    assert check.passed is True


def test_check_not_degenerate_flags_refusal() -> None:
    check = check_not_degenerate("I'm sorry, I cannot assist with that.")
    assert check.passed is False
