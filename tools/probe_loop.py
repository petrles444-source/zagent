"""Проверить, запущен ли loop воркера и выполняются ли задачи в нём."""
import asyncio
import sys
import threading

sys.path.insert(0, ".")

from hub.store import Store  # noqa: E402
from hub.worker import Worker  # noqa: E402

w = Worker(sys.argv[1] if len(sys.argv) > 1 else ".")
try:
    print("loop        :", w.loop)
    print("is_running  :", w.loop.is_running() if w.loop else None)
    print("ready       :", w._ready.is_set(), "| loop_ready:", w._loop_ready.is_set())
    print("thread alive:", w.thread.is_alive() if w.thread else None)
    print("pending task:", asyncio.all_tasks(w.loop) if w.loop else None)

    if w.loop and w.loop.is_running():
        # Может ли корутина вообще выполняться в этом loop прямо сейчас?
        got = []

        async def probe():
            got.append("выполнилась")

        fut = asyncio.run_coroutine_threadsafe(probe(), w.loop)
        try:
            fut.result(timeout=5)
            print("корутина в loop:", got)
        except Exception as exc:
            print("корутина в loop: ЗАСТРЯЛА —", type(exc).__name__, exc)
finally:
    w.store.close()
