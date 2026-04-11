from __future__ import annotations

import threading

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cursed_controls.app_state import AppState
from cursed_controls.bluetooth import connect_device
from cursed_controls.web.deps import get_runtime_manager, get_state

router = APIRouter()


class ConnectRequest(BaseModel):
    mac: str
    timeout: float = 15.0


class MacRequest(BaseModel):
    mac: str


@router.get("/bt/devices")
def list_bt_devices():
    """Return all devices known to bluetoothctl (name + MAC)."""
    import re
    import subprocess

    try:
        out = subprocess.check_output(["bluetoothctl", "devices"], text=True)
        devices = []
        for line in out.splitlines():
            m = re.match(r"Device ([0-9A-Fa-f:]{17})\s+(.*)", line)
            if m:
                devices.append({"mac": m.group(1), "name": m.group(2).strip()})
        return devices
    except (OSError, subprocess.CalledProcessError):
        return []


@router.post("/bt/scan")
def start_scan(state: AppState = Depends(get_state)):
    """Trigger a Bluetooth scan in a background thread; results arrive via WebSocket."""
    threading.Thread(target=_do_scan, args=(state,), daemon=True).start()
    return {"ok": True}


def _do_scan(state: AppState) -> None:
    import re
    import select
    import subprocess
    import time

    # Pre-load already-known devices so we can match [CHG] RSSI lines
    known: dict[str, str] = {}  # mac -> name
    try:
        out = subprocess.check_output(["bluetoothctl", "devices"], text=True)
        for line in out.splitlines():
            m = re.match(r"Device ([0-9A-Fa-f:]{17})\s+(.*)", line)
            if m:
                known[m.group(1)] = m.group(2).strip()
    except (OSError, subprocess.CalledProcessError):
        pass

    seen: set[str] = set()
    _strip = re.compile(r"[\x01\x02]|\x1b\[[0-9;]*m")

    state.broadcast({"type": "bt_scan", "event": "started"})
    try:
        proc = subprocess.Popen(
            ["stdbuf", "-oL", "bluetoothctl", "scan", "on"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.stdout is None:
            return
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue
            raw = proc.stdout.readline()
            if not raw:
                break
            line = _strip.sub("", raw)
            # Newly discovered device (name appears inline)
            m = re.search(r"\[NEW\] Device ([0-9A-Fa-f:]{17})\s+(.+)", line)
            if m:
                mac, name = m.group(1), m.group(2).strip()
                if mac not in seen:
                    seen.add(mac)
                    known[mac] = name
                    state.broadcast(
                        {"type": "bt_scan", "event": "found", "mac": mac, "name": name}
                    )
                continue
            # Already-known device signalling presence via RSSI update or direct reconnect
            m = re.search(
                r"\[CHG\] Device ([0-9A-Fa-f:]{17}) (?:RSSI:|Connected: yes)", line
            )
            if m:
                mac = m.group(1)
                if mac not in seen and mac in known:
                    seen.add(mac)
                    state.broadcast(
                        {
                            "type": "bt_scan",
                            "event": "found",
                            "mac": mac,
                            "name": known[mac],
                        }
                    )
        proc.terminate()
        proc.wait()
    except (OSError, FileNotFoundError):
        pass
    finally:
        state.broadcast({"type": "bt_scan", "event": "done"})


@router.post("/bt/connect")
def bt_connect(req: ConnectRequest, state: AppState = Depends(get_state)):
    ok = connect_device(req.mac, timeout=req.timeout)
    return {"ok": ok}


@router.get("/bt/paired")
def list_paired_devices():
    """Return all paired BT devices with their connected status."""
    import re
    import subprocess

    devices = []
    try:
        # Try "devices Paired" first (BlueZ 5.56+), fall back to all devices
        try:
            out = subprocess.check_output(
                ["bluetoothctl", "devices", "Paired"], text=True
            )
        except subprocess.CalledProcessError:
            out = subprocess.check_output(["bluetoothctl", "devices"], text=True)
        for line in out.splitlines():
            m = re.match(r"Device ([0-9A-Fa-f:]{17})\s+(.*)", line)
            if m:
                mac, name = m.group(1), m.group(2).strip()
                connected = False
                try:
                    info = subprocess.check_output(
                        ["bluetoothctl", "info", mac], text=True
                    )
                    if "Paired: yes" not in info:
                        continue
                    connected = "Connected: yes" in info
                except (OSError, subprocess.CalledProcessError):
                    pass
                devices.append({"mac": mac, "name": name, "connected": connected})
    except (OSError, subprocess.CalledProcessError):
        pass
    return devices


@router.post("/bt/disconnect")
def bt_disconnect(req: MacRequest, manager=Depends(get_runtime_manager)):
    import subprocess

    manager.suppress_reconnect(req.mac)
    try:
        subprocess.run(["bluetoothctl", "disconnect", req.mac], timeout=10, check=False)
        return {"ok": True}
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False}


@router.post("/bt/unpair")
def bt_unpair(req: MacRequest):
    import subprocess

    try:
        subprocess.run(["bluetoothctl", "remove", req.mac], timeout=10, check=False)
        return {"ok": True}
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False}
