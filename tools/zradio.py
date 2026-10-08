#!/usr/bin/env python3
r"""zradio — консольный клиент радио с окном, которое можно скрыть и показать.

Запуск
------
    .venv\Scripts\python.exe tools\zradio.py             # окно + консоль
    .venv\Scripts\python.exe tools\zradio.py --no-window  # только консоль

Команды (вводятся в консоль, окно дублирует их кнопками)
-------------------------------------------------------
    list              список станций со статусами
    ping              проверить все станции (в фоне)
    play <N|имя>      играть станцию по номеру или части имени
    next              следующая станция
    stop              остановить
    vol <0-100>       громкость
    hide              скрыть окно (игра продолжается)
    show              показать окно снова
    status            состояние плеера
    quit              выход

Воспроизведение идёт через WMP ActiveX (WMPlayer.OCX) в отдельном
PowerShell-процессе: без насоса сообщений `Application::DoEvents()`
плеер висит в состоянии Transitioning и не доходит до Playing.
Проверено — с `DoEvents` локальный файл и HTTPS-поток играют, без него
`playState` навсегда остаётся 9.
"""

from __future__ import annotations

import argparse
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub import radio as radio_mod  # noqa: E402

#: Скрипт PowerShell: держит WMPlayer.OCX, крутит DoEvents, читает команды
#: из stdin в отдельном runspace (чтобы блокирующий ReadLine не останавливал
#: насос сообщений). Команды: play <url> / stop / vol <n> / state / exit.
PS_PLAYER = r"""
Add-Type -AssemblyName System.Windows.Forms
$q = New-Object System.Collections.Concurrent.ConcurrentQueue[string]
$rs = [runspacefactory]::CreateRunspace()
$rs.Open()
$reader = [powershell]::Create()
$reader.Runspace = $rs
[void]$reader.AddScript({
  param($queue)
  while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) { break }
    [void]$queue.Enqueue($line)
  }
}).AddArgument($q)
[void]$reader.BeginInvoke()

$w = New-Object -ComObject WMPlayer.OCX
$w.settings.volume = 50
$running = $true
$lastState = -1
function Log($m) { [Console]::Out.WriteLine($m); [Console]::Out.Flush() }
Log 'ready'
while ($running) {
  [System.Windows.Forms.Application]::DoEvents()
  $line = $null
  while ($q.TryDequeue([ref]$line)) {
    $i = $line.IndexOf(' ')
    if ($i -lt 0) { $cmd = $line; $arg = '' } else { $cmd = $line.Substring(0, $i); $arg = $line.Substring($i + 1) }
    switch ($cmd) {
      'play' { try { $w.URL = $arg; Log 'ok play' } catch { Log ('err ' + $_.Exception.Message) } }
      'stop' { try { $w.controls.stop(); $w.close(); Log 'ok stop' } catch { Log 'err stop' } }
      'vol'  { $w.settings.volume = [int]$arg; Log 'ok vol' }
      'state' { Log ('state ' + $w.playState) }
      'exit' { $running = $false; Log 'ok exit' }
      default { Log ('unknown ' + $cmd) }
    }
    if (-not $running) { break }
  }
  if ($w.playState -ne $lastState) {
    $lastState = $w.playState
    Log ('event state=' + $lastState)
  }
  Start-Sleep -Milliseconds 30
}
try { $w.close() } catch {}
Log 'bye'
"""

#: Состояния WMP: 3 = Playing, 1 = Stopped, 2 = Paused, 9 = Transitioning.
WMP_STATE_NAMES = {
    0: "undefined", 1: "stopped", 2: "paused", 3: "playing",
    4: "scanforward", 5: "scanreverse", 6: "buffering",
    7: "waiting", 8: "ended", 9: "transitioning", 10: "ready",
}


class Player:
    """Плеер WMP ActiveX в отдельном PowerShell-процессе.

    Команды уходят в stdin процесса, ответы и события состояния
    читаются из stdout в фоновом потоке и складываются в очередь.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._events: queue.Queue[str] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Запустить PowerShell-процесс с плеером."""
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_PLAYER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        """Читать stdout процесса в очередь событий."""
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            self._events.put(line.rstrip())

    def send(self, cmd: str, timeout: float = 5.0) -> str:
        """Отправить команду и дождаться ответа (ok/err/state)."""
        with self._lock:
            assert self._proc and self._proc.stdin
            self._proc.stdin.write(cmd + "\n")
            self._proc.stdin.flush()
        deadline = time.monotonic() + timeout
        pending: list[str] = []
        while time.monotonic() < deadline:
            try:
                line = self._events.get(timeout=0.1)
            except queue.Empty:
                continue
            pending.append(line)
            if line.startswith(("ok ", "err ", "state ")):
                return line
        return "err timeout: " + " | ".join(pending[-3:])

    def play(self, url: str) -> str:
        return self.send("play " + url)

    def stop(self) -> str:
        return self.send("stop")

    def volume(self, v: int) -> str:
        return self.send(f"vol {v}")

    def state(self) -> str:
        return self.send("state")

    def close(self) -> None:
        """Завершить процесс плеера."""
        if not self._proc:
            return
        try:
            self.send("exit", timeout=3.0)
        except Exception:
            pass
        try:
            # stdin закрывается обязательно: читатель в runspace блокируется
            # на ReadLine и держит процесс живым, пока канал открыт.
            self._proc.stdin.close()  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None


class RadioApp:
    """Приложение радио: станции, пинг, плеер, окно, консоль."""

    def __init__(self, no_window: bool = False) -> None:
        self.stations = radio_mod.load_stations(ROOT)
        self.statuses: dict[str, dict[str, Any]] = {}
        self.player = Player()
        self.idx = -1
        self.playing = False
        self.vol = 50
        self._no_window = no_window
        self._root: Any = None
        self._ui_queue: queue.Queue[str] = queue.Queue()
        self._ping_thread: threading.Thread | None = None

    # ---------------------------------------------------------- пинг

    def ping(self) -> None:
        """Запустить проверку всех станций в фоне."""
        if self._ping_thread and self._ping_thread.is_alive():
            self._log("пинг уже идёт")
            return
        self._ping_thread = threading.Thread(target=self._ping_all, daemon=True)
        self._ping_thread.start()

    def _ping_all(self) -> None:
        """Проверить станции и обновить статусы."""
        self._log(f"пинг {len(self.stations)} станций…")
        for s in self.stations:
            self.statuses[s["url"]] = radio_mod.ping(s["url"])
            self._ui_queue.put("render")
        self._log("пинг готов")

    # ---------------------------------------------------------- плеер

    def play(self, idx: int) -> None:
        """Играть станцию по индексу."""
        if not 0 <= idx < len(self.stations):
            self._log(f"нет станции {idx}")
            return
        self.idx = idx
        name = self.stations[idx]["name"]
        self._log(f"▶ {name}")
        resp = self.player.play(self.stations[idx]["url"])
        self.playing = resp.startswith("ok")
        if not self.playing:
            self._log(f"ошибка: {resp}")
        self._ui_queue.put("render")

    def next_station(self) -> None:
        """Следующая станция."""
        if self.stations:
            self.play((self.idx + 1) % len(self.stations))

    def stop(self) -> None:
        """Остановить воспроизведение."""
        self.player.stop()
        self.playing = False
        self._log("⏸ стоп")
        self._ui_queue.put("render")

    def set_volume(self, v: int) -> None:
        """Установить громкость 0-100."""
        self.vol = max(0, min(100, v))
        self.player.volume(self.vol)
        self._ui_queue.put("render")

    # ---------------------------------------------------------- окно

    def run_window(self) -> None:
        """Запустить tkinter-окно и консольный цикл."""
        import tkinter as tk

        self._root = tk.Tk()
        self._root.title("zradio")
        self._root.geometry("520x420")

        top = tk.Frame(self._root)
        top.pack(fill="x", padx=8, pady=6)

        tk.Button(top, text="▶/⏸", width=4, command=self._ui_toggle).pack(side="left")
        tk.Button(top, text="⏭", width=3, command=self._ui_next).pack(side="left")
        tk.Button(top, text="Проверить", command=self._ui_ping).pack(side="left", padx=(8, 0))
        tk.Button(top, text="Скрыть", command=self._ui_hide).pack(side="left", padx=(8, 0))

        self._now_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._now_var, anchor="w").pack(
            side="left", fill="x", expand=True, padx=(10, 0))

        vol_frame = tk.Frame(self._root)
        vol_frame.pack(fill="x", padx=8)
        tk.Label(vol_frame, text="громкость").pack(side="left")
        self._vol_var = tk.IntVar(value=self.vol)
        tk.Scale(vol_frame, from_=0, to=100, orient="horizontal",
                 variable=self._vol_var, command=self._ui_vol).pack(
            side="left", fill="x", expand=True)

        list_frame = tk.Frame(self._root)
        list_frame.pack(fill="both", expand=True, padx=8, pady=6)
        self._listbox = tk.Listbox(list_frame, selectmode="single")
        self._listbox.pack(side="left", fill="both", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._ui_select)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical",
                                 command=self._listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._listbox.config(yscrollcommand=scrollbar.set)

        self._log_text = tk.Text(self._root, height=6, state="disabled")
        self._log_text.pack(fill="x", padx=8, pady=(0, 8))

        # Крестик скрывает окно, а не убивает музыку: воспроизведение
        # живёт в отдельном процессе PowerShell и переживает окно.
        self._root.protocol("WM_DELETE_WINDOW", self._ui_hide)

        self._render_list()
        self._poll_ui()
        self._root.mainloop()

    def _ui_toggle(self) -> None:
        if self.playing:
            self.stop()
        elif 0 <= self.idx < len(self.stations):
            self.play(self.idx)
        elif self.stations:
            self.play(0)

    def _ui_next(self) -> None:
        self.next_station()

    def _ui_ping(self) -> None:
        self.ping()

    def _ui_hide(self) -> None:
        """Скрыть окно (игра продолжается)."""
        if self._root:
            self._root.withdraw()

    def _ui_show(self) -> None:
        """Показать окно снова."""
        if self._root:
            self._root.deiconify()
            self._root.lift()

    def _ui_select(self, _event: Any) -> None:
        sel = self._listbox.curselection()
        if sel:
            self.play(sel[0])

    def _ui_vol(self, value: str) -> None:
        self.set_volume(int(float(value)))

    def _poll_ui(self) -> None:
        """Обработка событий из фоновых потоков.

        Tkinter нельзя трогать из чужого потока — только из главного,
        поэтому фоновые потоки кладут событие в очередь, а этот опрос
        раз в 200 мс разбирает очередь уже в главном.
        """
        try:
            while True:
                if self._ui_queue.get_nowait() == "render":
                    self._render_list()
        except queue.Empty:
            pass
        if self._root:
            self._root.after(200, self._poll_ui)

    def _render_list(self) -> None:
        """Отрисовать список станций с точками статуса."""
        if not self._root:
            return
        self._listbox.delete(0, "end")
        for i, s in enumerate(self.stations):
            st = self.statuses.get(s["url"])
            dot = "○" if st is None else ("●" if st.get("ok") else "✕")
            self._listbox.insert("end", f"{dot} {i + 1}. {s['name']}")
            if i == self.idx and self.playing:
                self._listbox.itemconfig(i, {"fg": "#4ade80"})
        cur = self.stations[self.idx] if 0 <= self.idx < len(self.stations) else None
        self._now_var.set(f"▶ {cur['name']}" if cur and self.playing else "")

    # ---------------------------------------------------------- консоль

    def run_console(self) -> None:
        """Консольный цикл команд."""
        self._log(f"zradio: {len(self.stations)} станций. "
                  "Команды: list, ping, play N, next, stop, vol N, hide, show, "
                  "status, quit")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "quit":
                break
            elif cmd == "list":
                self._cmd_list()
            elif cmd == "ping":
                self.ping()
            elif cmd == "play":
                self._cmd_play(arg)
            elif cmd == "next":
                self.next_station()
            elif cmd == "stop":
                self.stop()
            elif cmd == "vol":
                self._cmd_vol(arg)
            elif cmd == "hide":
                self._ui_hide()
            elif cmd == "show":
                self._ui_show()
            elif cmd == "status":
                self._cmd_status()
            else:
                self._log(f"неизвестная команда: {cmd}")

    def _cmd_list(self) -> None:
        """Вывести список станций со статусами."""
        for i, s in enumerate(self.stations):
            st = self.statuses.get(s["url"])
            if st is None:
                status = "не проверена"
            elif st.get("ok"):
                status = f"online {st.get('ms', 0)}мс"
            else:
                status = f"offline ({st.get('error', '?')})"
            self._log(f"{i + 1}. {s['name']} [{status}]")

    def _cmd_play(self, arg: str) -> None:
        """Играть станцию по номеру или части имени."""
        idx = self._resolve(arg)
        if idx is None:
            self._log(f"не найдено: {arg}")
            return
        self.play(idx)

    def _cmd_vol(self, arg: str) -> None:
        """Установить громкость."""
        try:
            self.set_volume(int(arg))
        except ValueError:
            self._log("громкость: число 0-100")

    def _cmd_status(self) -> None:
        """Состояние плеера."""
        resp = self.player.state()
        name = WMP_STATE_NAMES.get(
            int(resp.partition(" ")[2]) if resp.startswith("state ") else -1,
            resp)
        self._log(f"плеер: {name}")

    def _resolve(self, arg: str) -> int | None:
        """Найти станцию по номеру (1-based) или части имени."""
        arg = arg.strip()
        if not arg:
            return None
        if arg.isdigit():
            n = int(arg) - 1
            return n if 0 <= n < len(self.stations) else None
        low = arg.lower()
        for i, s in enumerate(self.stations):
            if low in s["name"].lower():
                return i
        return None

    # ---------------------------------------------------------- лог

    def _log(self, msg: str) -> None:
        """Вывести сообщение в консоль и в лог окна."""
        print(msg, flush=True)
        if self._root:
            self._log_text.config(state="normal")
            self._log_text.insert("end", msg + "\n")
            self._log_text.see("end")
            self._log_text.config(state="disabled")

    # ---------------------------------------------------------- запуск

    def run(self) -> None:
        """Запустить приложение."""
        if not self.stations:
            self._log("станции не найдены (music/stations.json пуст или отсутствует)")
            return
        self.player.start()
        self.player.volume(self.vol)
        if self._no_window:
            self.run_console()
        else:
            # Консольный цикл живёт в отдельном потоке, окно — в главном.
            threading.Thread(target=self.run_console, daemon=True).start()
            self.run_window()
        self.player.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="zradio — клиент радио")
    parser.add_argument("--no-window", action="store_true",
                        help="только консоль, без окна")
    args = parser.parse_args()
    RadioApp(no_window=args.no_window).run()


if __name__ == "__main__":
    main()
