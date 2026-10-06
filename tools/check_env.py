"""Диагностика окружения: зависимости, ключи, конфигурация, доступность шлюзов.

Вызывается из check.bat. Печатает только для чтения, ничего не меняет.

Весь вывод — ASCII, потому что консоль Windows по умолчанию cp1251/cp866
и ломается на любом символе за пределами ASCII. Русский текст оставлен
в отчёте Markdown, а не здесь.
"""

from __future__ import annotations

import asyncio
import json
import sys
from importlib.util import find_spec
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from hub.config import ConfigError, load_gateways, project_root  # noqa: E402
from providers.openai_compat import OpenAICompatProvider  # noqa: E402

OK = "OK  "
BAD = "FAIL"
WARN = "WARN"
MISS = "--  "

#: Ответы без ключа подтверждают, что хост доступен.
AUTH_MARKERS = (
    "401", "403", "unauthorized", "invalid api key", "authentication", "missing",
    "authorization", "api key", "token is invalid", "not authenticated", "key",
)


def _print_dependencies() -> bool:
    """Проверить зависимости. True, если обязательные на месте."""
    print("[dependencies]")
    critical = True

    try:
        import httpx as module

        print(f"  {OK} httpx      {module.__version__}")
    except ImportError:
        print(f"  {BAD} httpx      MISSING  ->  pip install -r requirements.txt")
        critical = False

    for name, label, hint in (
        ("PIL", "Pillow", "screenshots"),
        ("playwright", "playwright", "browser"),
        ("pytest", "pytest", "tests"),
    ):
        if find_spec(name):
            print(f"  {OK} {label:<11}installed  ({hint})")
        else:
            print(f"  {MISS} {label:<11}not installed ({hint})")

    return critical


def _print_secrets(root: Path) -> None:
    print("[keys]")
    path = root / "config" / "secrets.local.json"
    if not path.is_file():
        print(f"  {MISS} config/secrets.local.json  MISSING")
        print("        copy config\\secrets.local.json.example config\\secrets.local.json")
        print("        without keys only keyless gateways work (llm7.io, Zen, local Ollama)")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  {BAD} cannot read: {exc}")
        return

    filled = 0
    for key in sorted(data):
        value = str(data[key]).strip()
        if value:
            # Ключ не печатаем: в выводе достаточно факта.
            print(f"  {OK} {key:<22}set ({len(value)} chars)")
            filled += 1
        else:
            print(f"  {MISS} {key:<22}EMPTY")

    print(f"  {filled} of {len(data)} keys filled")


def _print_config(root: Path) -> None:
    print("[config]")
    for name, key_path in (
        ("gateways", ("config", "gateways.json")),
        ("tiers", ("config", "tiers.json")),
        ("models", ("config", "models.json")),
    ):
        path = root.joinpath(*key_path)
        if not path.is_file():
            print(f"  {MISS} {name:<12}missing: {key_path[-1]}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  {BAD} {name:<12}invalid JSON: {exc}")
            continue

        if name == "gateways":
            print(f"  {OK} {name:<12}{len(data.get('gateways', []))} gateways")
        elif name == "tiers":
            specs = data.get("models", [])
            vision = sum(1 for s in specs if s.get("vision"))
            best = [s for s in specs if s.get("tier") == 1]
            print(f"  {OK} {name:<12}{len(specs)} models, {vision} vision, "
                  f"{len(best)} at tier 1")
        else:
            print(f"  {OK} {name:<12}{len(data.get('models', []))} models")


async def _probe(gateway: dict) -> tuple[str, str, str]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=25.0) as client:
        provider = OpenAICompatProvider(
            gateway["id"], gateway["resolved_url"], gateway["api_key"], client=client
        )
        try:
            response = await client.get(
                f"{gateway['resolved_url']}/models", headers=provider._headers(), timeout=25.0
            )
        except httpx.TimeoutException:
            return "timeout", "host does not respond", "0"
        except Exception as exc:
            return "network", f"{type(exc).__name__}", "0"

        status = response.status_code
        body = " ".join(response.text.split())[:50]

        if status == 200:
            try:
                data = response.json()
            except ValueError:
                return "no json", body, "0"
            items = data.get("data") or data.get("models") if isinstance(data, dict) else data
            if not isinstance(items, list):
                return "ok", "catalog in other form", "0"
            return "ok", "catalog open", str(len(items))

        if status in (404, 405):
            # Cloudflare Workers AI: GET /models нет, есть нативный поиск.
            try:
                native = await client.get(
                    f"{gateway['base_url'].rstrip('/')}/models/search",
                    headers=provider._headers(),
                    timeout=25.0,
                )
            except Exception:
                native = None
            if native is not None and native.status_code == 200:
                try:
                    items = native.json().get("result") or []
                except ValueError:
                    items = []
                return "ok", "native catalog", str(len(items))
            return "ok", "list from config, no GET /models", "0"

        if status in (401, 403):
            if any(marker in body.lower() for marker in AUTH_MARKERS):
                if gateway.get("api_key"):
                    return "key", "host answers, key rejected", "0"
                return "no key", "host reachable, catalog needs key", "0"
            return "blocked", f"HTTP {status}: {body}", "0"

        if status == 451:
            return "region", "HTTP 451 blocked by jurisdiction", "0"
        if status == 429:
            return "limit", "HTTP 429", "0"

        return f"HTTP {status}", body, "0"


#: Метки шлюзов, которые печатаем как есть.
_ASCII_LABELS = {
    "Ollama (локально)": "Ollama (local)",
}


def _ascii_label(label: str) -> str:
    """Привести метку к ASCII: консоль Windows не любит кириллицу в cmd."""
    if label in _ASCII_LABELS:
        return _ASCII_LABELS[label]
    try:
        label.encode("ascii")
        return label
    except UnicodeEncodeError:
        return label.encode("ascii", "replace").decode("ascii")


async def _print_gateways(root: Path) -> bool:
    print("[gateways]")
    try:
        gateways = load_gateways(root, env={})
    except ConfigError as exc:
        print(f"  {BAD} config error: {exc}")
        return False

    results = await asyncio.gather(*(_probe(g) for g in gateways))

    marks = {"ok": OK, "no key": WARN, "key": BAD, "region": BAD,
             "timeout": BAD, "network": BAD, "limit": WARN}
    alive = 0

    for gateway, (status, detail, count) in zip(gateways, results):
        if status in ("ok", "no key", "key"):
            alive += 1
        mark = marks.get(status, WARN if status == "limit" else BAD)
        models = f"{count} models" if count != "0" else ""
        # Метки шлюзов из конфига содержат кириллицу — в ASCII-выводе заменяем.
        label = _ascii_label(gateway["label"])
        print(f"  {mark} {label[:26]:<26} {status:<8} {detail[:34]:<34} {models}")

    print(f"  reachable: {alive} of {len(gateways)}")
    return alive > 0


def _print_browser(root: Path) -> None:
    print("[browser]")
    if find_spec("playwright"):
        print(f"  {OK} playwright installed")
    else:
        print(f"  {MISS} playwright not installed  ->  pip install playwright")
        print("        then: python -m playwright install chromium")

    profile = root / "browser-profile"
    if profile.is_dir():
        size = sum(f.stat().st_size for f in profile.rglob("*") if f.is_file())
        print(f"  {OK} profile exists, {size / 1024:.0f} KB (session is saved here)")
    else:
        print(f"  {MISS} no profile yet (first login will not be remembered)")


async def main() -> int:
    # Консоль Windows может быть cp1251/cp866 — принудительно UTF-8 не поможет,
    # поэтому весь вывод ASCII. Это осознанное решение, не недоработка.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

    root = project_root()
    print()
    print("  zagent - environment check")
    print("  " + "=" * 50)
    print()

    deps_ok = _print_dependencies()
    print()
    _print_secrets(root)
    print()
    _print_config(root)
    print()
    gateways_ok = await _print_gateways(root)
    print()
    _print_browser(root)
    print()

    if deps_ok and gateways_ok:
        print("  Ready. Launch with run.bat")
        print()
        return 0

    print("  Problems found:")
    if not deps_ok:
        print("    - install dependencies: pip install -r requirements.txt")
    if not gateways_ok:
        print("    - no gateway reachable; check the internet connection")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
