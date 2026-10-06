"""Локальный веб-интерфейс: статус моделей, пинг, проверка адекватности, агент.

Запуск: python tools/web.py  ->  http://127.0.0.1:8777

Сделано на стандартной библиотеке (http.server) без Flask/FastAPI: зависимостей
у проекта ровно одна — httpx, и веб-интерфейс не должен её ломать.

Эндпоинты:
    GET  /                      панель
    GET  /api/state             текущее состояние реестра и селектора
    POST /api/scan              пересобрать каталог шлюзов
    POST /api/ping              пинг одной модели или всех
    POST /api/sanity            проверка адекватности одной или нескольких моделей
    POST /api/mode              переключить auto / manual / chain
    POST /api/ask               одиночный вопрос через failover
    POST /api/consult           спросить несколько моделей (режим questions)
    GET  /api/agent/state       состояние агента
    POST /api/agent/task        поставить задачу
    POST /api/agent/step        выполнить один шаг
    POST /api/agent/run         прогнать до конца
    POST /api/agent/answer      ответить на вопрос агента
    POST /api/agent/config      уровни доступа и автономии
    GET  /api/shot              снимок экрана как data-URL
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hub.agent import Agent, AgentConfig, Phase, make_guard, selector_from_registry
from hub.autonomy import AccessLevel, Autonomy, Escalation
from hub.config import ConfigError, load_gateways, project_root
from hub.failover import AutoCaller, FailoverError
from hub.registry import collect, probe_models
from hub.report import ALIVE_STATUSES, build_snapshot, render_legend
from hub.sanity import build_probe_prompt, evaluate
from hub.tools import capture_screen, image_to_data_url

HOST = "127.0.0.1"
PORT = 8777

ROOT = project_root()


class AppState:
    """Общее состояние приложения между запросами."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.selector: Any = None
        self.gateways: list[dict[str, Any]] = []
        self.snapshot: dict[str, Any] = {}
        self.probes: dict[str, dict[str, Any]] = {}
        self.sanity: dict[str, dict[str, Any]] = {}
        self.agent: Agent | None = None
        self.config = AgentConfig(base_dir=str(ROOT))
        self.last_ping: str | None = None
        self.busy = False
        self.events: list[dict[str, Any]] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    def note(self, message: str) -> None:
        self.events.append({"at": time.strftime("%H:%M:%S"), "message": message})
        del self.events[:-50]

    async def bootstrap(self) -> None:
        """Первичная загрузка реестра."""
        self.gateways = load_gateways(ROOT, env={})
        registry = await collect(self.gateways, root=ROOT)
        self.selector = selector_from_registry(registry, root=str(ROOT))
        self._refresh_snapshot(registry)

    def _refresh_snapshot(self, registry: Any) -> None:
        self.snapshot = build_snapshot(registry, self.probes)
        self.snapshot["legend"] = render_legend()

    def on_agent_event(self, event: dict[str, Any]) -> None:
        self.events.append({"at": time.strftime("%H:%M:%S"), **event})
        del self.events[:-120]


STATE = AppState()


# ------------------------------------------------------------------ helpers


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def run_async(coro: Any) -> Any:
    """Выполнить корутину в фоновом loop (HTTP-сервер синхронный)."""
    if STATE.loop is None:
        STATE.loop = asyncio.new_event_loop()
        threading.Thread(target=STATE.loop.run_forever, daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(coro, STATE.loop)
    return future.result(timeout=300)


# ----------------------------------------------------------------- handlers


class Handler(BaseHTTPRequestHandler):
    server_version = "zagent"

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # тихий режим

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._serve_page()
        try:
            if path == "/api/state":
                return json_response(self, self._state())
            if path == "/api/agent/state":
                return json_response(self, self._agent_state())
            if path == "/api/shot":
                return json_response(self, self._shot())
        except Exception as exc:
            traceback.print_exc()
            return json_response(
                self,
                {"error": _short(exc), "type": type(exc).__name__,
                 "trace": traceback.format_exc()[-1200:]},
                500,
            )
        return json_response(self, {"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = read_body(self)
        try:
            routes = {
                "/api/scan": self._scan,
                "/api/ping": self._ping,
                "/api/sanity": self._sanity,
                "/api/mode": self._mode,
                "/api/ask": self._ask,
                "/api/consult": self._consult,
                "/api/agent/task": self._agent_task,
                "/api/agent/step": self._agent_step,
                "/api/agent/run": self._agent_run,
                "/api/agent/answer": self._agent_answer,
                "/api/agent/approve": self._agent_approve,
                "/api/agent/config": self._agent_config,
            }
            handler = routes.get(path)
            if handler is None:
                return json_response(self, {"error": "not found"}, 404)
            return json_response(self, handler(body))
        except Exception as exc:
            traceback.print_exc()
            return json_response(
                self,
                {"error": _short(exc), "type": type(exc).__name__,
                 "trace": traceback.format_exc()[-1500:]},
                500,
            )

    # ---------------------------------------------------------------- pages

    def _serve_page(self) -> None:
        html = INDEX_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    # --------------------------------------------------------------- API: state

    def _state(self) -> dict[str, Any]:
        candidates = []
        if STATE.selector is not None:
            for row in STATE.selector.candidates():
                ref = row["ref"]
                probe = STATE.probes.get(ref) or {}
                sanity = STATE.sanity.get(ref) or {}
                candidates.append({
                    **row,
                    "probe": {
                        "status": probe.get("status"),
                        "duration_ms": probe.get("duration_ms"),
                        "tokens_in": probe.get("tokens_in"),
                        "tokens_out": probe.get("tokens_out"),
                        "error": probe.get("error"),
                    },
                    "sanity": {
                        "score": sanity.get("score"),
                        "verdict": sanity.get("verdict"),
                    },
                })
        return {
            "gateways": STATE.snapshot.get("gateways", []),
            "models": STATE.snapshot.get("models", []),
            "candidates": candidates,
            "stats": STATE.selector.stats() if STATE.selector else {},
            "legend": render_legend(),
            "events": STATE.events[-30:],
            "last_ping": STATE.last_ping,
            "busy": STATE.busy,
            "config": STATE.config.to_dict(),
            "generated_at": STATE.snapshot.get("generated_at"),
            "status_counts": STATE.snapshot.get("status_counts", {}),
        }

    # -------------------------------------------------------------- API: scan

    def _scan(self, body: dict[str, Any]) -> dict[str, Any]:
        async def job() -> dict[str, Any]:
            gateways = load_gateways(ROOT, env={})
            registry = await collect(gateways, root=ROOT)
            STATE.gateways = gateways
            STATE.selector = selector_from_registry(registry, root=str(ROOT))
            STATE._refresh_snapshot(registry)
            STATE.note("Каталог пересобран")
            return {"ok": True, "models": len(registry.chat_models)}

        return run_async(job())

    # -------------------------------------------------------------- API: ping

    def _ping(self, body: dict[str, Any]) -> dict[str, Any]:
        ref = body.get("ref")

        async def job() -> dict[str, Any]:
            if STATE.selector is None:
                await STATE.bootstrap()
            registry = STATE.selector.registry

            if ref:
                target = [m for m in registry.chat_models if m.ref == ref]
                if not target:
                    return {"ok": False, "error": f"Модель не найдена: {ref}"}
            else:
                target = registry.chat_models

            probes = await probe_models(STATE.gateways, target, timeout=90.0)
            STATE.probes.update(probes)
            STATE._refresh_snapshot(registry)
            STATE.last_ping = time.strftime("%Y-%m-%d %H:%M:%S")

            # Пинг обновляет и карантины селектора: упавшая модель уходит в откат.
            for model_ref, probe in probes.items():
                if STATE.selector.states.get(model_ref):
                    STATE.selector.record(
                        model_ref, probe.get("status") or "down",
                        error=probe.get("error"),
                        duration_ms=probe.get("duration_ms") or 0,
                    )
            return {"ok": True, "pinged": len(probes), "results": probes}

        return run_async(job())

    # ------------------------------------------------------------ API: sanity

    def _sanity(self, body: dict[str, Any]) -> dict[str, Any]:
        ref = body.get("ref")
        lang = body.get("lang", "ru")
        use_vision = bool(body.get("vision"))

        async def job() -> dict[str, Any]:
            if STATE.selector is None:
                await STATE.bootstrap()
            registry = STATE.selector.registry
            system, user, token = build_probe_prompt(lang)

            if ref:
                targets = [m for m in registry.chat_models if m.ref == ref]
            else:
                targets = registry.chat_models

            import httpx
            from providers.openai_compat import OpenAICompatProvider

            reports = {}
            for model in targets:
                gateway = next(
                    (g for g in STATE.gateways if g["id"] == model.gateway_id), None
                )
                if gateway is None:
                    continue

                client = httpx.AsyncClient(follow_redirects=True)
                try:
                    provider = OpenAICompatProvider(
                        model.gateway_id, gateway["resolved_url"], gateway["api_key"],
                        timeout=90.0, client=client,
                    )
                    messages = [{"role": "system", "content": system},
                                {"role": "user", "content": user}]
                    result = await provider.chat(
                        model.model_id, messages, temperature=0, max_tokens=400
                    )
                finally:
                    await client.aclose()

                duration = int(result.get("duration_ms") or 0)
                answer = str(result.get("text") or result.get("reasoning") or "")

                if result.get("error"):
                    reports[model.ref] = {
                        "ref": model.ref, "score": 0.0, "verdict": "unreachable",
                        "latency_ms": duration, "sample": "",
                        "checks": [{"name": "reachable", "passed": False,
                                    "detail": str(result["error"]), "score": 0.0}],
                    }
                    continue

                report = evaluate(
                    model.ref, answer, question=user, token=token,
                    duration_ms=duration, lang=lang,
                )
                reports[model.ref] = report.to_dict()

            STATE.sanity.update(reports)
            good = sum(1 for r in reports.values() if r["verdict"] in ("good", "usable"))
            return {
                "ok": True,
                "checked": len(reports),
                "good": good,
                "vision_tested": use_vision,
                "reports": reports,
            }

        return run_async(job())

    # -------------------------------------------------------------- API: mode

    def _mode(self, body: dict[str, Any]) -> dict[str, Any]:
        if STATE.selector is None:
            return {"ok": False, "error": "Сначала выполните scan"}
        mode = str(body.get("mode") or "auto")
        manual = body.get("manual_ref")
        chain = body.get("chain")
        prefer_speed = bool(body.get("prefer_speed"))

        if mode == "manual" and not manual:
            return {"ok": False, "error": "Для ручного режима укажите модель"}
        if manual and manual not in STATE.selector.states:
            return {"ok": False, "error": f"Модель не найдена: {manual}"}

        STATE.selector.set_mode(
            mode,
            manual_ref=manual,
            chain=chain if isinstance(chain, list) else None,
        )
        STATE.selector.prefer_speed = prefer_speed
        STATE.selector.require_vision = bool(body.get("require_vision"))
        STATE.note(f"Режим: {mode}" + (f" ({manual})" if manual else ""))
        return {"ok": True, "stats": STATE.selector.stats()}

    # -------------------------------------------------------------- API: ask

    def _ask(self, body: dict[str, Any]) -> dict[str, Any]:
        text = str(body.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "Пустой запрос"}

        async def job() -> dict[str, Any]:
            if STATE.selector is None:
                await STATE.bootstrap()
            caller = AutoCaller(STATE.selector, timeout=120.0)
            images = body.get("images") or None
            try:
                result = await caller.ask(
                    [{"role": "user", "content": text}],
                    max_tokens=int(body.get("max_tokens") or 2000),
                    images=images,
                    include_attempts=True,
                )
            except FailoverError as exc:
                return {"ok": False, "error": str(exc),
                        "attempts": [a.__dict__ for a in exc.attempts]}

            answer = str(result.get("text") or result.get("reasoning") or "")
            return {
                "ok": True,
                "model": result.get("model"),
                "status": result.get("status"),
                "duration_ms": result.get("duration_ms"),
                "tokens_in": result.get("tokens_in"),
                "tokens_out": result.get("tokens_out"),
                "cost": result.get("cost"),
                "answer": answer,
                "hops": result.get("hops", 0),
                "attempts": result.get("attempts") or [],
            }

        return run_async(job())

    # ---------------------------------------------------------- API: consult

    def _consult(self, body: dict[str, Any]) -> dict[str, Any]:
        question = str(body.get("question") or "").strip()
        count = int(body.get("models") or 3)

        async def job() -> dict[str, Any]:
            if STATE.selector is None:
                await STATE.bootstrap()
            agent = STATE.agent or Agent(
                STATE.selector, make_guard(STATE.config), STATE.config,
                on_event=STATE.on_agent_event,
            )
            STATE.agent = agent
            opinions = await agent.consult(question, models=count)
            return {"ok": True, "opinions": opinions}

        return run_async(job())

    # ----------------------------------------------------------- API: agent

    def _ensure_agent(self) -> Agent:
        if STATE.agent is None:
            if STATE.selector is None:
                raise RuntimeError("Сначала выполните scan")
            STATE.agent = Agent(
                STATE.selector,
                make_guard(STATE.config),
                STATE.config,
                on_event=STATE.on_agent_event,
            )
        return STATE.agent

    def _agent_state(self) -> dict[str, Any]:
        agent = STATE.agent
        if agent is None:
            return {"active": False, "config": STATE.config.to_dict()}
        return {
            "active": True,
            "phase": agent.phase.value,
            "finished": agent.finished,
            "steps": [s.to_dict() for s in agent.steps],
            "pending_question": agent.pending_question,
            "plan": agent.plan,
            "plan_approved": agent.plan_approved,
            "config": STATE.config.to_dict(),
            "selector": agent.selector.stats(),
            "events": STATE.events[-40:],
        }

    def _agent_task(self, body: dict[str, Any]) -> dict[str, Any]:
        task = str(body.get("task") or "").strip()
        if not task:
            return {"ok": False, "error": "Пустая задача"}
        agent = self._ensure_agent()
        agent.set_task(task)
        agent.messages.append({"role": "user", "content": _vision_hint(body)})
        STATE.note(f"Задача: {task[:80]}")
        return {"ok": True, "phase": agent.phase.value}

    def _agent_step(self, body: dict[str, Any]) -> dict[str, Any]:
        """Один шаг: ограничиваем цикл одной итерацией."""
        agent = self._ensure_agent()
        previous = agent.config.max_steps
        agent.config.max_steps = len(agent.steps) + 1
        try:
            result = run_async(agent.run())
        finally:
            agent.config.max_steps = previous
        return {"ok": True, **self._agent_state(), "result": result}

    def _agent_run(self, body: dict[str, Any]) -> dict[str, Any]:
        agent = self._ensure_agent()
        limit = int(body.get("max_steps") or STATE.config.max_steps)
        STATE.config.max_steps = limit
        agent.config.max_steps = limit
        result = run_async(agent.run())
        return {"ok": True, **self._agent_state(), "result": result}

    def _agent_answer(self, body: dict[str, Any]) -> dict[str, Any]:
        agent = self._ensure_agent()
        answer = str(body.get("answer") or "")
        if agent.plan and not agent.plan_approved and body.get("approve"):
            agent.approve_plan()
        else:
            agent.answer_question(answer)
        return {"ok": True, **self._agent_state()}

    def _agent_approve(self, body: dict[str, Any]) -> dict[str, Any]:
        agent = self._ensure_agent()
        agent.approve_plan()
        return {"ok": True, **self._agent_state()}

    def _agent_config(self, body: dict[str, Any]) -> dict[str, Any]:
        config = STATE.config
        if "access" in body:
            config.access = AccessLevel(int(body["access"]))
        if "autonomy" in body:
            config.autonomy = Autonomy(str(body["autonomy"]))
        if "escalation" in body:
            config.escalation = Escalation(str(body["escalation"]))
        if "max_steps" in body:
            config.max_steps = int(body["max_steps"])
        if "base_dir" in body:
            config.base_dir = str(body["base_dir"])
        if "require_vision" in body:
            config.require_vision = bool(body["require_vision"])

        if STATE.agent is not None:
            STATE.agent.config = config
            STATE.agent.guard = make_guard(config)
        STATE.note(
            f"Настройки: доступ {config.access.label}, "
            f"автономия {config.autonomy.label}, эскалация {config.escalation.label}"
        )
        return {"ok": True, "config": config.to_dict()}

    # ------------------------------------------------------------ API: shot

    def _shot(self) -> dict[str, Any]:
        result = capture_screen(ROOT / "screenshots" / "web.png", base=ROOT)
        if not result.ok:
            return {"ok": False, "error": result.error, "needs_user": result.needs_user}
        encoded = image_to_data_url(str(result.data["path"]))
        if not encoded.ok:
            return {"ok": False, "error": encoded.error}
        return {
            "ok": True,
            "path": result.data["path"],
            "width": result.data["width"],
            "height": result.data["height"],
            "data_url": encoded.data,
        }


def _vision_hint(body: dict[str, Any]) -> str:
    """Приложить картинку к задаче, если пользователь её прислал."""
    images = body.get("images") or []
    if not images:
        return "Выполни задачу."
    urls = [img["data_url"] for img in images if isinstance(img, dict) and img.get("data_url")]
    if not urls:
        return "Выполни задачу."
    parts = [{"type": "text", "text": "Выполни задачу с учётом изображения:"}]
    for url in urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts  # type: ignore[return-value]


def _short(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300]


INDEX_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>zagent</title>
<style>
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif;
       background: #0f1115; color: #e6e6e6; }
header { padding: 14px 20px; border-bottom: 1px solid #262b36; display: flex;
         align-items: center; gap: 16px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 17px; font-weight: 600; }
.sub { color: #8b93a3; font-size: 12px; }
nav { display: flex; gap: 4px; }
nav button { background: transparent; border: 1px solid transparent; color: #8b93a3;
             padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }
nav button.on { background: #1e2430; color: #e6e6e6; border-color: #2f3746; }
main { padding: 18px 20px 60px; }
section { display: none; }
section.on { display: block; }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
button.act { background: #2563eb; border: 0; color: #fff; padding: 7px 14px;
             border-radius: 6px; cursor: pointer; font-size: 13px; }
button.act:hover { background: #1d4ed8; }
button.ghost { background: #1e2430; border: 1px solid #2f3746; color: #c8cdd8;
               padding: 7px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }
select, input, textarea { background: #151a22; border: 1px solid #2f3746; color: #e6e6e6;
                          padding: 7px 10px; border-radius: 6px; font-size: 13px;
                          font-family: inherit; }
input { min-width: 220px; }
textarea { width: 100%; min-height: 80px; resize: vertical; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #1e2430; }
th { color: #8b93a3; font-weight: 500; font-size: 12px; }
tr:hover td { background: #141922; }
.pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px;
        font-weight: 600; letter-spacing: .3px; }
.ok, .good { background: #14532d; color: #86efac; }
.slow, .usable { background: #713f12; color: #fcd34d; }
.limited, .empty { background: #1e3a5f; color: #93c5fd; }
.blocked, .down, .poor { background: #7f1d1d; color: #fca5a5; }
.unknown, .skipped, .note, .unreachable { background: #272b36; color: #9aa3b2; }
pre { background: #0b0e13; border: 1px solid #1e2430; border-radius: 8px; padding: 12px;
      overflow: auto; font-size: 12.5px; white-space: pre-wrap; word-break: break-word;
      max-height: 460px; }
.card { background: #151a22; border: 1px solid #262b36; border-radius: 10px;
        padding: 14px 16px; margin-bottom: 12px; }
.stat { display: flex; gap: 22px; flex-wrap: wrap; }
.stat div { min-width: 88px; }
.stat b { display: block; font-size: 22px; font-weight: 600; }
.stat span { color: #8b93a3; font-size: 12px; }
.log { font-size: 12px; color: #8b93a3; max-height: 260px; overflow: auto; }
.log div { padding: 3px 0; border-bottom: 1px solid #141922; }
.muted { color: #8b93a3; }
.bar { height: 6px; background: #262b36; border-radius: 3px; overflow: hidden; width: 70px;
       display: inline-block; vertical-align: middle; }
.bar i { display: block; height: 100%; background: #2563eb; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
.tier { color: #6b7280; font-variant-numeric: tabular-nums; }
.mini { font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1>zagent</h1>
  <span class="sub" id="hdr">загрузка…</span>
  <nav>
    <button data-tab="status" class="on">Статус моделей</button>
    <button data-tab="check">Проверка моделей</button>
    <button data-tab="ask">Запрос</button>
    <button data-tab="agent">Агент</button>
    <button data-tab="shot">Скриншот</button>
  </nav>
</header>
<main>

<section id="tab-status" class="on">
  <div class="card">
    <div class="stat" id="stats"></div>
  </div>
  <div class="row">
    <button class="act" onclick="scan()">Пересобрать каталог</button>
    <button class="act" onclick="pingAll()">Пинговать все</button>
    <button class="ghost" onclick="modeSwitch()">Сменить режим</button>
    <span class="mini muted" id="pinginfo"></span>
  </div>
  <div class="row">
    <span class="mini muted">Режим:</span>
    <select id="modeSel" onchange="setMode(this.value)">
      <option value="auto">auto — лучшая доступная</option>
      <option value="manual">manual — выбранная вручную</option>
    </select>
    <select id="modelSel" onchange="setManual(this.value)"></select>
    <label class="mini"><input type="checkbox" id="speedChk"> быстрые приоритетнее</label>
    <label class="mini"><input type="checkbox" id="visChk"> только vision-модели</label>
  </div>
  <table id="tbl"><thead><tr>
    <th>Модель</th><th>Шлюз</th><th>Тир</th><th>Статус</th><th>Ответ</th>
    <th>Токены</th><th>Адекватность</th><th>Карантин</th><th></th>
  </tr></thead><tbody></tbody></table>
  <div class="card mini muted" id="legend"></div>
</section>

<section id="tab-check">
  <div class="row">
    <button class="act" onclick="pingAll()">1. Пинг всех</button>
    <button class="act" onclick="sanityAll()">2. Проверить адекватность всех</button>
    <button class="ghost" onclick="sanityOne()">Проверить выбранную</button>
    <select id="langSel"><option value="ru">русский</option><option value="en">english</option></select>
  </div>
  <div class="row mini muted">
    Проба: в начале длинного протокола спрятан код, в конце — просьба вернуть JSON
    с этим кодом. Так проверяются удержание контекста, следование формату,
    смешение языков и зацикливание.
  </div>
  <div id="sanityBox"></div>
</section>

<section id="tab-ask">
  <div class="row">
    <textarea id="q" placeholder="Вопрос модели…"></textarea>
  </div>
  <div class="row">
    <button class="act" onclick="ask()">Спросить (auto)</button>
    <button class="ghost" onclick="consult()">Спросить 3 модели</button>
    <span class="mini muted" id="askinfo"></span>
  </div>
  <div id="askOut"></div>
</section>

<section id="tab-agent">
  <div class="card">
    <div class="row">
      <span class="mini">Доступ:</span>
      <select id="accSel" onchange="agentCfg('access', this.value)">
        <option value="1">только чтение</option>
        <option value="2" selected>чтение и запись</option>
        <option value="3">полный доступ</option>
      </select>
      <span class="mini">Автономия:</span>
      <select id="autoSel" onchange="agentCfg('autonomy', this.value)">
        <option value="yolo">полная</option>
        <option value="normal" selected>обычная</option>
        <option value="strict">с подтверждением</option>
        <option value="plan">с планом</option>
      </select>
      <span class="mini">Помощь:</span>
      <select id="escSel" onchange="agentCfg('escalation', this.value)">
        <option value="off">не просить</option>
        <option value="auto" selected>когда иначе никак</option>
        <option value="on">при сомнении</option>
      </select>
    </div>
  </div>
  <div class="row">
    <textarea id="task" placeholder="Задача агенту, например: создай в tests/test_smoke.py проверку, что cli.py отвечает на --help"></textarea>
  </div>
  <div class="row">
    <button class="act" onclick="agentTask()">Поставить задачу</button>
    <button class="act" onclick="agentStep()">Шаг</button>
    <button class="act" onclick="agentRun()">Выполнить</button>
    <button class="ghost" onclick="agentApprove()">Одобрить план</button>
    <label class="mini"><input type="checkbox" id="agentVis"> задача со скриншотом</label>
    <span class="mini muted" id="agentinfo"></span>
  </div>
  <div id="questionBox"></div>
  <div class="grid2">
    <div class="card"><b>Шаги</b><div class="log" id="steps"></div></div>
    <div class="card"><b>События</b><div class="log" id="events"></div></div>
  </div>
</section>

<section id="tab-shot">
  <div class="row">
    <button class="act" onclick="takeShot()">Снять экран</button>
    <span class="mini muted" id="shotinfo"></span>
  </div>
  <div class="row">
    <textarea id="visq" placeholder="Что изображено на скриншоте?"></textarea>
    <button class="act" onclick="askVision()">Спросить vision-модель</button>
  </div>
  <div id="shotBox"></div>
  <div class="mini muted" id="visinfo"></div>
</section>

</main>
<script>
const $ = id => document.getElementById(id);
let STATE = null, SHOT = null;

document.querySelectorAll('nav button').forEach(b =>
  b.onclick = () => {
    document.querySelectorAll('nav button').forEach(x => x.classList.remove('on'));
    document.querySelectorAll('section').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    $('tab-' + b.dataset.tab).classList.add('on');
  });

async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  return r.json();
}

function pill(v) { return `<span class="pill ${v}">${v}</span>`; }

async function refresh() {
  STATE = await api('/api/state');
  render();
}

function render() {
  const s = STATE;
  const c = s.status_counts || {};
  const st = s.stats || {};
  $('hdr').textContent = `${s.gateways.length} шлюзов · ${s.candidates.length} моделей · пинг ${s.last_ping || 'не было'}`;
  $('stats').innerHTML = `
    <div><b>${s.candidates.length}</b><span>моделей</span></div>
    <div><b>${c.ok || 0}</b><span>ok</span></div>
    <div><b>${c.slow || 0}</b><span>slow</span></div>
    <div><b>${c.limited || 0}</b><span>лимит</span></div>
    <div><b>${c.blocked || 0}</b><span>заблокировано</span></div>
    <div><b>${st.cooling || 0}</b><span>в карантине</span></div>
    <div><b>${st.mode || '—'}</b><span>режим</span></div>`;

  $('legend').textContent = 'Статусы: ok — отвечает; slow — медленно; limited — лимит 429; blocked — доступ закрыт провайдером; down — недоступна.';

  const tb = $('tbl').querySelector('tbody');
  tb.innerHTML = (s.candidates || []).map(r => {
    const p = r.probe || {}, sn = r.sanity || {};
    const lat = p.duration_ms ? (p.duration_ms / 1000).toFixed(1) + 's' : '—';
    const tok = p.tokens_in ? `${p.tokens_in}+${p.tokens_out}` : '—';
    const bar = sn.score != null
      ? `<span class="bar"><i style="width:${Math.round(sn.score * 100)}%"></i></span> ${pill(sn.verdict || '')}`
      : '<span class="muted">—</span>';
    return `<tr>
      <td><code>${r.model}</code>${r.vision ? ' <span class="mini muted">👁</span>' : ''}
          ${r.notes ? `<div class="mini muted">${r.notes}</div>` : ''}</td>
      <td class="mini">${r.gateway}</td>
      <td class="tier">${r.tier}</td>
      <td>${pill(p.status || 'unknown')}</td>
      <td class="mini">${lat}${r.avg_ms ? `<div class="muted">ср ${(r.avg_ms/1000).toFixed(1)}s</div>` : ''}</td>
      <td class="mini">${tok}</td>
      <td class="mini">${bar}</td>
      <td class="mini">${r.in_cooldown ? `${r.cooldown_left}c` : '—'}</td>
      <td><button class="ghost" onclick="pingOne('${r.ref}')">пинг</button></td>
    </tr>`;
  }).join('');

  $('modelSel').innerHTML = (s.candidates || [])
    .map(r => `<option value="${r.ref}">${r.ref} (тир ${r.tier})</option>`).join('');
  if (st.mode) $('modeSel').value = st.mode;
  if (st.manual_ref) $('modelSel').value = st.manual_ref;

  (s.events || []).slice().reverse().forEach(e => {
    if (e.type === 'step') logStep(e.step);
  });
}

function logStep(st) {
  const box = $('steps');
  const div = document.createElement('div');
  div.textContent = `#${st.index} [${st.phase}] ${st.text}${st.model ? ' — ' + st.model : ''}`;
  if (!st.ok) div.style.color = '#fca5a5';
  box.prepend(div);
}

async function scan() {
  $('pinginfo').textContent = 'собираю…';
  await api('/api/scan', {});
  await refresh();
  $('pinginfo').textContent = '';
}

async function pingAll() {
  $('pinginfo').textContent = 'пингую все модели, это 2-4 минуты…';
  const r = await api('/api/ping', {});
  await refresh();
  $('pinginfo').textContent = `готово: ${r.pinged}`;
}

async function pingOne(ref) {
  $('pinginfo').textContent = 'пингую ' + ref + '…';
  await api('/api/ping', {ref});
  await refresh();
  $('pinginfo').textContent = '';
}

async function setMode(mode) {
  const body = {mode, prefer_speed: $('speedChk').checked, require_vision: $('visChk').checked};
  if (mode === 'manual') body.manual_ref = $('modelSel').value;
  const r = await api('/api/mode', body);
  if (!r.ok) alert(r.error);
  await refresh();
}

function setManual(ref) {
  if ($('modeSel').value === 'manual') setMode('manual');
}

async function modeSwitch() {
  $('modeSel').value = $('modeSel').value === 'auto' ? 'manual' : 'auto';
  setMode($('modeSel').value);
}

async function sanityAll() {
  $('sanityBox').innerHTML = '<div class="muted">проверяю модели, это 2-4 минуты…</div>';
  const r = await api('/api/sanity', {lang: $('langSel').value});
  renderSanity(r);
  await refresh();
}

async function sanityOne() {
  const ref = $('modelSel').value;
  $('sanityBox').innerHTML = '<div class="muted">проверяю…</div>';
  const r = await api('/api/sanity', {ref, lang: $('langSel').value});
  renderSanity(r);
  await refresh();
}

function renderSanity(r) {
  const rows = Object.values(r.reports || {}).sort((a, b) => (b.score || 0) - (a.score || 0));
  $('sanityBox').innerHTML = `<div class="card">Проверено ${r.checked}, пригодных ${r.good}</div>` +
    rows.map(x => `<div class="card">
      <div class="row" style="margin:0 0 8px">
        <code>${x.ref}</code> ${pill(x.verdict)}
        <span class="bar"><i style="width:${Math.round((x.score||0)*100)}%"></i></span>
        <span class="mini muted">${x.latency_ms} мс</span>
      </div>
      <div class="mini">${x.checks.map(c =>
        `${c.passed ? '✔' : '✘'} ${c.name}: ${c.detail}`).join(' · ')}</div>
      ${x.sample ? `<pre>${escapeHtml(x.sample.slice(0, 400))}</pre>` : ''}
    </div>`).join('');
}

async function ask() {
  $('askinfo').textContent = 'жду…';
  $('askOut').innerHTML = '';
  const r = await api('/api/ask', {text: $('q').value});
  $('askinfo').textContent = '';
  if (!r.ok) { $('askOut').innerHTML = `<div class="card">Ошибка: ${escapeHtml(r.error)}</div>`; return; }
  const hops = (r.attempts || []).filter(a => !a.ok);
  $('askOut').innerHTML = `<div class="card">
    <div class="row mini">
      <code>${r.model}</code> ${pill(r.status)} ${r.duration_ms} мс
      ${r.tokens_in}+${r.tokens_out} токенов ${r.cost != null ? '· cost ' + r.cost : ''}
      ${hops.length ? `· переключений: ${hops.length}` : ''}
    </div>
    <pre>${escapeHtml(r.answer)}</pre>
    ${hops.length ? `<div class="mini muted">Пробованы и отказали: ${hops.map(h => escapeHtml(h.ref)).join(', ')}</div>` : ''}
  </div>`;
  await refresh();
}

async function consult() {
  $('askinfo').textContent = 'спрашиваю 3 модели…';
  const r = await api('/api/consult', {question: $('q').value, models: 3});
  $('askinfo').textContent = '';
  $('askOut').innerHTML = (r.opinions || []).map(o => `<div class="card">
    <div class="mini"><code>${o.ref}</code> ${o.duration_ms} мс</div>
    <pre>${escapeHtml(o.error ? 'ошибка: ' + o.error : o.text)}</pre>
  </div>`).join('');
  await refresh();
}

async function agentCfg(key, value) {
  const body = {}; body[key] = value;
  await api('/api/agent/config', body);
}

async function agentTask() {
  const task = $('task').value.trim();
  if (!task) return;
  $('steps').innerHTML = ''; $('events').innerHTML = '';
  const body = {task};
  if ($('agentVis').checked) {
    body.require_vision = true;
    const shot = await api('/api/shot');
    if (shot.ok) body.images = [{data_url: shot.data_url}];
  }
  await api('/api/agent/task', body);
  $('agentinfo').textContent = 'задача поставлена';
}

async function agentStep() { await runAgent('/api/agent/step'); }
async function agentRun()  { await runAgent('/api/agent/run'); }

async function runAgent(path) {
  $('agentinfo').textContent = 'агент работает…';
  const r = await api(path, {});
  $('agentinfo').textContent = `фаза: ${r.phase} · шагов ${(r.steps||[]).length}`;
  (r.steps || []).forEach(logStep);
  (r.events || []).slice().reverse().forEach(e => {
    if (!e.step) {
      const d = document.createElement('div');
      d.textContent = e.at + ' ' + JSON.stringify(e).slice(0, 160);
      $('events').prepend(d);
    }
  });
  $('questionBox').innerHTML = r.pending_question
    ? `<div class="card"><b>Агент спрашивает:</b> ${escapeHtml(r.pending_question)}
        <div class="row" style="margin-top:8px">
        <input id="ans" placeholder="Ваш ответ" style="min-width:420px">
        <button class="act" onclick="agentAnswer()">Ответить</button></div></div>`
    : '';
  await refresh();
}

async function agentAnswer() {
  const v = $('ans').value;
  await api('/api/agent/answer', {answer: v, approve: true});
  await agentRun();
}

async function agentApprove() {
  await api('/api/agent/approve', {});
  $('questionBox').innerHTML = '';
  $('agentinfo').textContent = 'план одобрен';
}

async function takeShot() {
  $('shotinfo').textContent = 'снимаю…';
  const r = await api('/api/shot');
  $('shotinfo').textContent = r.ok ? `${r.width}×${r.height}` : ('ошибка: ' + r.error);
  if (r.ok) {
    SHOT = r.data_url;
    $('shotBox').innerHTML = `<img src="${r.data_url}" style="max-width:100%; border-radius:8px;
      border:1px solid #2f3746">`;
  } else $('shotBox').innerHTML = '';
}

async function askVision() {
  const q = $('visq').value.trim() || 'Что изображено на этом скриншоте?';
  if (!SHOT) { $('visinfo').textContent = 'сначала сделайте скриншот'; return; }
  $('visinfo').textContent = 'спрашиваю vision-модель…';
  // Переключаем селектор на vision-модели, спрашиваем, возвращаем как было.
  const prev = STATE.stats.mode;
  await api('/api/mode', {mode: 'auto', require_vision: true});
  const r = await api('/api/ask', {text: q, images: [SHOT]});
  await api('/api/mode', {mode: prev || 'auto', require_vision: false});
  $('visinfo').innerHTML = r.ok
    ? `<div class="mini"><code>${r.model}</code> ${pill(r.status)} ${r.duration_ms} мс</div>
       <pre>${escapeHtml(r.answer)}</pre>`
    : `<span class="mini">${escapeHtml(r.error)}</span>`;
  await refresh();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

refresh();
setInterval(() => { if (STATE) refresh(); }, 20000);
</script>
</body>
</html>
"""


def serve(host: str = HOST, port: int = PORT) -> None:
    """Запустить веб-интерфейс."""
    if STATE.loop is None:
        STATE.loop = asyncio.new_event_loop()
        threading.Thread(target=STATE.loop.run_forever, daemon=True).start()

    print("Загружаю реестр…", flush=True)
    try:
        asyncio.run_coroutine_threadsafe(STATE.bootstrap(), STATE.loop).result(timeout=180)
    except Exception as exc:
        # Реестр может не собраться (сеть, провайдеры лежат) — интерфейс всё равно
        # должен подняться, чтобы пользователь мог увидеть, что произошло, и
        # повторить попытку кнопкой «Пересобрать каталог».
        STATE.note(f"Не удалось собрать реестр при старте: {exc}")
        print(f"Реестр не собран: {exc}", file=sys.stderr)
        print("Интерфейс запущен, нажмите «Пересобрать каталог».", file=sys.stderr)
    else:
        count = len(STATE.selector.states) if STATE.selector else 0
        print(f"Готово: {count} моделей", flush=True)

    print(f"Открой http://{host}:{port}", flush=True)

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Веб-интерфейс zagent")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    serve(args.host, args.port)
