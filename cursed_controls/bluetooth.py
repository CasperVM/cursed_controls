from __future__ import annotations

import re
import select
import subprocess
import time

from cursed_controls.discovery import list_devices


def _run_bluetoothctl(*args: str, timeout: float) -> str:
    """Run a single bluetoothctl command and return stdout."""
    try:
        result = subprocess.run(
            ["bluetoothctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return ""


def connect_device(mac: str, timeout: float) -> bool:
    """Pair, trust, and connect a standard Bluetooth device by MAC.

    Returns True if connection was successful.
    """
    _run_bluetoothctl("pair", mac, timeout=timeout + 2)
    _run_bluetoothctl("trust", mac, timeout=5.0)
    out = _run_bluetoothctl("connect", mac, timeout=timeout + 2)
    return "Connection successful" in out


def connect_wiimote(mac: str, timeout: float) -> bool:
    """Connect a Wii Remote by MAC.

    Wiimotes use a non-standard HID pairing — skip 'pair', just trust+connect.
    The hid-wiimote kernel driver handles the PIN automatically.
    Returns True if connection was successful.
    """
    _run_bluetoothctl("trust", mac, timeout=5.0)
    out = _run_bluetoothctl("connect", mac, timeout=timeout + 2)
    return "Connection successful" in out


def scan_for_wiimote(timeout: float, known_mac: str | None = None) -> str | None:
    """Scan for a Nintendo Wii Remote and return its MAC address.

    If known_mac is provided, returns it directly without scanning.
    Otherwise, starts a bluetoothctl scan and watches for a Nintendo device.
    Uses stdbuf to force line-buffering so output isn't held in a block buffer.
    Returns the MAC address if found, or None if the scan timed out.
    """
    if known_mac is not None:
        return known_mac

    # Check already-known devices first. bluetoothctl only emits the full name
    # on [NEW] lines; re-seen devices only produce [CHG] RSSI lines with no name,
    # so a previously-discovered Wiimote would never match the scan regex below.
    out = _run_bluetoothctl("devices", timeout=5.0)
    for line in out.splitlines():
        m = re.search(r"Device ([0-9A-Fa-f:]{17}) Nintendo", line)
        if m:
            print(f"Found known Wiimote: {m.group(1)}")
            return m.group(1)

    # Put adapter in pairable mode so the Wiimote can be accepted
    _run_bluetoothctl("pairable", "on", timeout=5.0)

    try:
        proc = subprocess.Popen(
            # stdbuf -oL forces line-buffering on bluetoothctl's stdout
            # so we see each device line as it arrives, not in 4KB blocks
            ["stdbuf", "-oL", "bluetoothctl", "scan", "on"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            m = re.search(r"Device ([0-9A-Fa-f:]{17}) Nintendo", line)
            if m:
                proc.terminate()
                proc.wait()
                return m.group(1)

        proc.terminate()
        proc.wait()
    except Exception:
        pass
    return None


def wait_for_evdev(name: str, timeout: float) -> bool:
    """Poll list_devices() until a device with the given name appears.

    Returns True if found within timeout seconds, False otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(d.name == name for d in list_devices()):
            return True
        time.sleep(0.5)
    return False
