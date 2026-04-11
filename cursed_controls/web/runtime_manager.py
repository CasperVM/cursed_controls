from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from cursed_controls.app_state import AppState, DeviceStatus
from cursed_controls.output import OutputSink, RawGadgetSink, StdoutSink
from cursed_controls.runtime import Runtime


def _kill_ep_out_procs() -> None:
    """Kill raw-gadget endpoint processes (ep0, ep_out_N) by open file descriptor.

    The raw-gadget library double-forks these processes so they are reparented to
    PID 1 — PPID matching misses them. Instead, find any process that has
    /dev/raw-gadget open. x360_close() blocks until they exit, so kill them first.
    Requires root (service runs as root for /dev/raw-gadget access anyway).
    """
    own_pid = os.getpid()
    try:
        raw_gadget = str(Path("/dev/raw-gadget").resolve())
    except OSError:
        raw_gadget = "/dev/raw-gadget"
    pids: list[int] = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid == own_pid:
            continue
        fd_dir = proc / "fd"
        try:
            for fd_link in fd_dir.iterdir():
                try:
                    target = os.readlink(str(fd_link))
                except OSError:
                    continue
                if "raw-gadget" in target or target == raw_gadget:
                    pids.append(pid)
                    break
        except OSError:
            continue
    print(
        f"[RuntimeManager] kill_ep_out_procs: found {len(pids)} gadget proc(s): {pids}",
        flush=True,
    )
    if not pids:
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"[RuntimeManager] SIGTERM → gadget proc {pid}", flush=True)
        except OSError:
            pass
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid in pids):
            break
        time.sleep(0.1)
    for pid in pids:
        if Path(f"/proc/{pid}").exists():
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"[RuntimeManager] SIGKILL → gadget proc {pid}", flush=True)
            except OSError:
                pass
    time.sleep(0.2)


def _kill_so_procs(library_path: str) -> None:
    """SIGTERM then SIGKILL any processes (other than ourselves) that have the gadget .so mapped."""
    so = str(Path(library_path).resolve())
    own_pid = os.getpid()
    pids = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid == own_pid:
            continue
        try:
            if so in (proc / "maps").read_text():
                pids.append(pid)
        except OSError:
            continue
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"[RuntimeManager] SIGTERM → stale gadget proc {pid}")
        except OSError:
            pass
    if pids:
        time.sleep(0.5)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"[RuntimeManager] SIGKILL → stale gadget proc {pid}")
            except OSError:
                pass  # already dead


def _make_sink(state: AppState) -> OutputSink:
    cfg = state.config
    if cfg is None or cfg.runtime.output_mode != "gadget":
        return StdoutSink()
    return RawGadgetSink(
        library_path=cfg.runtime.gadget_library,
        num_slots=cfg.runtime.interfaces,
        driver=cfg.runtime.gadget_driver,
        device=cfg.runtime.gadget_device,
    )


class _NoCloseSink(OutputSink):
    """Proxy that makes open()/close() no-ops so a persistent sink survives Runtime.run()."""

    def __init__(self, inner: OutputSink) -> None:
        self._inner = inner

    def open(self) -> None:
        pass  # already open

    def send(self, state, slot: int = 0) -> None:
        self._inner.send(state, slot)

    def close(self) -> None:
        pass  # don't close the underlying sink

    def poll_rumble(self, slot: int = 0):
        return self._inner.poll_rumble(slot)

    def poll_led(self, slot: int = 0):
        return self._inner.poll_led(slot)


class RuntimeManager:
    """Manages the Runtime lifecycle.

    The gadget sink is kept alive across stop/start cycles to avoid the UDC
    reset problem: after x360_close(), dwc2 keeps the USB link 'configured'
    indefinitely, making x360_open fail on the next attempt. By reusing the
    same sink handle we side-step this entirely. The sink is only truly closed
    at service shutdown via close_sink().
    """

    def __init__(self, state: AppState) -> None:
        self._state = state
        self._runtime: Runtime | None = None
        self._thread: threading.Thread | None = None
        self._gen: int = (
            0  # incremented on each start; stale threads detect they're old
        )
        self._persistent_sink: OutputSink | None = None

    def _get_sink(self) -> OutputSink:
        """Return the persistent sink, creating and opening it on first call."""
        if self._persistent_sink is None:
            cfg = self._state.config
            if cfg is not None and cfg.runtime.output_mode == "gadget":
                _kill_ep_out_procs()
                _kill_so_procs(cfg.runtime.gadget_library)
            sink = _make_sink(self._state)
            sink.open()
            self._persistent_sink = sink
        return self._persistent_sink

    def close_sink(self) -> None:
        """Close the persistent sink. Call once at service shutdown."""
        if self._persistent_sink is not None:
            _kill_ep_out_procs()
            try:
                self._persistent_sink.close()
            except Exception:
                pass
            self._persistent_sink = None

    def start(self, sink: OutputSink | None = None) -> None:
        if self._state.runtime_status == "running":
            return
        if self._state.config is None:
            raise ValueError("no config loaded")

        actual_sink: OutputSink
        if sink is not None:
            actual_sink = sink
        else:
            actual_sink = _NoCloseSink(self._get_sink())

        runtime = Runtime(
            self._state.config,
            actual_sink,
            on_event=self._on_runtime_event,
        )
        self._runtime = runtime
        self._gen += 1
        my_gen = self._gen
        self._thread = threading.Thread(target=lambda: self._run(my_gen), daemon=True)
        self._thread.start()
        self._state.runtime_status = "running"
        self._state.broadcast({"type": "runtime_status", "status": "running"})

    def get_ff_status(self) -> dict[str, bool]:
        """Return {profile_id: has_ff} for all currently bound devices."""
        if self._runtime is None:
            return {}
        return {
            bd.profile.id: bd.ff is not None
            for bd in self._runtime.bound_by_fd.values()
        }

    def rumble_test(self, profile_id: str) -> bool:
        """Trigger a short test rumble on bound devices matching profile_id. Returns True if FF was triggered."""
        if self._runtime is None:
            return False
        targets = [
            b
            for b in self._runtime.bound_by_fd.values()
            if b.profile.id == profile_id and b.ff is not None
        ]
        if not targets:
            return False

        def _buzz() -> None:
            deadline = time.monotonic() + 1.5
            for b in targets:
                b.rumble_test_until = deadline
                b.ff.set_rumble(200, 200)
            while time.monotonic() < deadline:
                time.sleep(0.05)
                for b in targets:
                    b.ff.heartbeat()
            for b in targets:
                b.rumble_test_until = 0.0
                b.ff.set_rumble(0, 0)

        threading.Thread(target=_buzz, daemon=True).start()
        return True

    def suppress_reconnect(self, mac: str) -> None:
        """Tell the runtime not to auto-reconnect this MAC (user-initiated disconnect)."""
        if self._runtime is not None:
            self._runtime.suppress_reconnect(mac)

    def stop(self) -> None:
        if self._runtime is not None:
            self._runtime.stop()
            # The sink is a _NoCloseSink proxy — close() is a no-op, which is what we want.
            # The persistent sink stays open for the next start().
            try:
                self._runtime.sink.close()
            except Exception:
                pass
        self._runtime = None
        self._thread = None
        self._state.runtime_status = "stopped"
        self._state.broadcast({"type": "runtime_status", "status": "stopped"})

    def _run(self, gen: int) -> None:
        try:
            if self._runtime is not None:
                self._runtime.run()
        except Exception as e:
            print(f"[RuntimeManager] runtime exited with error: {e}")
        finally:
            # Only update status if we're still the current generation (no newer start happened).
            if self._gen == gen and self._state.runtime_status != "stopped":
                self._state.runtime_status = "stopped"
                self._state.broadcast({"type": "runtime_status", "status": "stopped"})

    def _on_runtime_event(self, event: dict) -> None:
        ev_type = event.get("type")
        if ev_type == "device_bound":
            profile_id = event["profile_id"]
            self._state.device_statuses[profile_id] = DeviceStatus(
                profile_id=profile_id,
                path=event.get("path"),
                status="bound",
            )
        elif ev_type == "device_disconnected":
            profile_id = event["profile_id"]
            self._state.device_statuses[profile_id] = DeviceStatus(
                profile_id=profile_id,
                path=None,
                status="disconnected",
            )
        elif ev_type == "wiimote_mac_discovered":
            # Persist the discovered MAC to the config file so the next service
            # start can reconnect directly without scanning.
            profile_id = event["profile_id"]
            mac = event["mac"]
            if self._state.config_path:
                try:
                    from cursed_controls.config import patch_profile_mac

                    patch_profile_mac(self._state.config_path, profile_id, mac)
                    print(
                        f"[{profile_id}] Saved Wiimote MAC {mac} to config", flush=True
                    )
                except Exception as e:
                    print(
                        f"[{profile_id}] Failed to save MAC to config: {e!r}",
                        flush=True,
                    )
            return  # don't broadcast this internal event to WS clients
        self._state.broadcast(event)
